# -*- coding: utf-8 -*-

"""
app/services/llm_service.py

This module is the core of the Text-to-SQL agent, handling all interactions
with the Large Language Model (LLM).

It is responsible for:
- Constructing prompts for the LLM, including schema context and few-shot examples
- Calling the LLM API to generate SQL
- Calling the LLM API to repair incorrect SQL
- Parsing and validating JSON responses
- Retrying transient HTTP failures
"""

from __future__ import annotations

import json

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.config import (
    HTTP_CONNECT_TIMEOUT,
    HTTP_POOL_TIMEOUT,
    HTTP_READ_TIMEOUT,
    HTTP_WRITE_TIMEOUT,
    LLM_BASE_URL,
    LLM_MODEL,
    SQL_EXAMPLE_LIMIT
)
from app.services.embedding_service import get_embedding
from app.services.postgres_service import search_schema_chunks, search_sql_examples

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

BASE_PROMPT = """
Return exactly one JSON object:
{
  "sql": "single executable MySQL SELECT statement or null",
  "answerable": true,
  "uncertainty_note": "brief assumption note or null",
  "refusal_reason": "reason for refusal or null"
}

You are an expert MySQL SQL generator.

Decision policy:
1. Use only tables and columns present in Context Schema.
2. If the question requires a business metric or concept that is not explicitly defined in the schema, return:
   - answerable=false
   - sql=null
   - refusal_reason explaining the missing definition
3. Examples of undefined business metrics/concepts that should usually be refused unless explicitly defined:
   - ARPU
   - LTV
   - churn rate
   - retention rate
   - conversion rate
   - growth rate
4. If the question contains an ambiguous natural-language term that can be mapped to a reasonable schema-grounded interpretation, you may answer, but you MUST explain the interpretation in uncertainty_note.
5. Examples of ambiguous but interpretable terms:
   - active user -> may be interpreted as user with the most orders
   - popular product -> may be interpreted as product with highest order quantity
   - top country -> may be interpreted as country with highest order count or amount, depending on the question wording
6. Never invent tables, columns, joins, filters, or business definitions not supported by the schema.
7. If answerable=false:
   - sql must be null
   - refusal_reason must be non-null
8. If answerable=true:
   - sql must be a single executable MySQL SELECT statement
   - uncertainty_note must be non-null whenever you make an interpretation or assumption
9. Output JSON only. No markdown, no comments, no extra text.
"""

DEBUG_PROMPT = """
Return exactly one JSON object:
{
  "query_plan": "short plan for how to build the query",
  "sql": "single executable MySQL SELECT statement or null",
  "answerable": true,
  "uncertainty_note": "brief assumption note or null",
  "refusal_reason": "reason for refusal or null"
}

You are an expert MySQL SQL generator.

Decision policy:
1. Use only tables and columns present in Context Schema.
2. If the question requires a business metric or concept that is not explicitly defined in the schema, return:
   - answerable=false
   - sql=null
   - refusal_reason explaining the missing definition
3. Examples of undefined business metrics/concepts that should usually be refused unless explicitly defined:
   - ARPU
   - LTV
   - churn rate
   - retention rate
   - conversion rate
   - growth rate
4. If the question contains an ambiguous natural-language term that can be mapped to a reasonable schema-grounded interpretation, you may answer, but you MUST explain the interpretation in uncertainty_note.
5. Examples of ambiguous but interpretable terms:
   - active user -> may be interpreted as user with the most orders
   - popular product -> may be interpreted as product with highest order quantity
   - top country -> may be interpreted as country with highest order count or amount, depending on the question wording
6. query_plan must be concise.
7. Never invent tables, columns, joins, filters, or business definitions not supported by the schema.
8. If answerable=false:
   - sql must be null
   - refusal_reason must be non-null
9. If answerable=true:
   - sql must be a single executable MySQL SELECT statement
   - uncertainty_note must be non-null whenever you make an interpretation or assumption
10. Output JSON only. No markdown, no comments, no extra text.
"""


REPAIR_PROMPT = """
Return exactly one JSON object:
{
  "sql": "corrected executable MySQL SELECT statement or null",
  "answerable": true,
  "uncertainty_note": "brief assumption note or null",
  "refusal_reason": "reason for refusal or null"
}

You are an expert MySQL SQL repair assistant.

Rules:
1. Fix the SQL using only the provided schema.
2. Preserve the user's original intent.
3. Do not invent tables, columns, joins, filters, aliases, or business definitions not supported by the schema.
4. If the original question requires an undefined business metric or concept, return:
   - answerable=false
   - sql=null
   - refusal_reason explaining why the concept is not defined
5. If the question is ambiguous but still reasonably answerable from the schema, keep the interpretation and explain it in uncertainty_note.
6. Prefer minimal changes to the SQL instead of rewriting the entire query.
7. Output JSON only. No markdown, no comments, no extra text.
"""


def _should_retry_http(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


def _clean_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def parse_llm_json_response(raw_text: str) -> dict:
    text = _clean_json_text(raw_text)
    if not text:
        raise ValueError("LLM returned an empty response.")
    return json.loads(text)


def _format_examples_context(similar_examples: list[dict]) -> str:
    if not similar_examples:
        return ""
    parts = ["Here are some similar verified examples for reference:"]
    for ex in similar_examples:
        parts.append(f"Question: {ex['question']}")
        parts.append(f"SQL: {ex['sql']}")
        parts.append("")
    return "\n".join(parts).strip()


async def build_generation_context(question: str) -> tuple[str, str]:
    question_embedding = await get_embedding(question)

    relevant_schemas = search_schema_chunks(question_embedding, limit=4)
    schema_context = "\n\n".join(relevant_schemas).strip()
    schema_context = schema_context.replace("\\n", "\n")

    similar_examples = search_sql_examples(question_embedding, limit=SQL_EXAMPLE_LIMIT)
    examples_context = _format_examples_context(similar_examples)

    return schema_context, examples_context


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=8),
    retry=retry_if_exception(_should_retry_http),
    reraise=True,
)
async def _call_llm_json(prompt: str) -> dict:
    timeout = httpx.Timeout(
        connect=HTTP_CONNECT_TIMEOUT,
        read=HTTP_READ_TIMEOUT,
        write=HTTP_WRITE_TIMEOUT,
        pool=HTTP_POOL_TIMEOUT,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/api/generate",
            json={
                "model": LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()

    raw_text = payload.get("response", "")
    return parse_llm_json_response(raw_text)


async def generate_sql_from_question(
    question: str,
    schema_context: str | None = None,
    examples_context: str | None = None,
    debug: bool = False,
) -> tuple[str | None, str | None, str | None, bool]:
    if schema_context is None or examples_context is None:
        schema_context, examples_context = await build_generation_context(question)

    if not schema_context:
        return (
            "No relevant schema context was found." if debug else None,
            None,
            "No relevant schema context was found for this question.",
            False,
        )

    prompt_template = DEBUG_PROMPT if debug else BASE_PROMPT

    prompt = f"""{prompt_template}

Context Schema:
{schema_context}

{examples_context}

User question:
{question}
"""

    result = await _call_llm_json(prompt)

    query_plan = result.get("query_plan") if debug else None
    answerable = bool(result.get("answerable", False))
    refusal_reason = result.get("refusal_reason")
    uncertainty_note = result.get("uncertainty_note")
    sql = result.get("sql")

    if isinstance(sql, str):
        sql = sql.strip()
    else:
        sql = None

    if not answerable:
        sql = None
        uncertainty_note = (
            uncertainty_note
            or refusal_reason
            or "Question cannot be answered from the current schema."
        )
    elif not sql:
        return (
            query_plan,
            None,
            "Model returned answerable=true but did not provide SQL.",
            False,
        )

    return query_plan, sql, uncertainty_note, answerable


async def repair_sql(
    question: str,
    error_msg: str,
    wrong_sql: str,
    schema_context: str,
) -> tuple[str | None, str | None, str | None]:
    prompt = f"""{REPAIR_PROMPT}

User Question:
{question}

Previous Wrong SQL:
{wrong_sql}

Execution Error:
{error_msg}

Context Schema:
{schema_context}
"""

    result = await _call_llm_json(prompt)

    answerable = bool(result.get("answerable", False))
    refusal_reason = result.get("refusal_reason")
    uncertainty_note = result.get("uncertainty_note")
    sql = result.get("sql")

    if isinstance(sql, str):
        sql = sql.strip()
    else:
        sql = None

    if not answerable:
        return None, None, (
            uncertainty_note or refusal_reason or "Repair was refused."
        )

    if not sql:
        return None, None, "Repair returned answerable=true but the SQL was empty."

    return None, sql, uncertainty_note