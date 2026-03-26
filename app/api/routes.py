# -*- coding: utf-8 -*-

"""
app/api/routes.py

This module defines the API endpoints for the Text-to-SQL agent.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.models.schemas import QueryRequest
from app.services.embedding_service import get_embedding
from app.services.guard_service import semantic_guard, validate_sql
from app.services.llm_service import (
    build_generation_context,
    generate_sql_from_question,
    repair_sql,
)
from app.services.mysql_service import (
    check_explain_plan,
    explain_query,
    run_query,
)
from app.services.postgres_service import save_sql_example
from app.services.redis_service import (
    bump_examples_version,
    get_cached_response,
    get_current_schema_version,
    set_cached_rejection,
    set_cached_success,
    should_cache_rejection,
    should_cache_success,
)
from app.services.schema_service import sync_mysql_schema_to_pg


class ExampleRequest(BaseModel):
    question: str
    sql: str


router = APIRouter()


def _debug_payload(
    schema_context: str | None = None,
    examples_context: str | None = None,
    semantic_guard_passed: bool | None = None,
    semantic_guard_error: str | None = None,
    explain_passed: bool | None = None,
    explain_reason: str | None = None,
    explain_plan: list[dict] | None = None,
) -> dict:
    return {
        "schema_context": schema_context,
        "examples_context": examples_context,
        "semantic_guard_passed": semantic_guard_passed,
        "semantic_guard_error": semantic_guard_error,
        "explain_passed": explain_passed,
        "explain_reason": explain_reason,
        "explain_plan": explain_plan,
    }


def _validate_guard_and_explain(
    question: str,
    sql: str,
    schema_context: str,
) -> tuple[str, bool, str | None, list[dict], bool, str | None]:
    """
    Validate SQL, run semantic guard, and run EXPLAIN gate.

    Returns:
        (
            checked_sql,
            semantic_guard_passed,
            semantic_guard_error,
            explain_plan,
            explain_passed,
            explain_reason,
        )
    """
    checked_sql = validate_sql(sql)

    semantic_guard_passed, semantic_guard_error = semantic_guard(
        question=question,
        sql=checked_sql,
        schema_context=schema_context,
    )
    if not semantic_guard_passed:
        return (
            checked_sql,
            False,
            semantic_guard_error,
            [],
            False,
            "Semantic guard failed before EXPLAIN.",
        )

    explain_plan = explain_query(checked_sql)
    explain_passed, explain_reason = check_explain_plan(explain_plan)

    return (
        checked_sql,
        True,
        None,
        explain_plan,
        explain_passed,
        explain_reason,
    )


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/query/debug")
async def query_debug(req: QueryRequest):
    schema_version = get_current_schema_version()
    if not schema_version:
        return {
            "question": req.question,
            "query_plan": None,
            "generated_sql": None,
            "validated_sql": None,
            "uncertainty_note": None,
            "answerable": False,
            "schema_version": None,
            "cache_status": "not_initialized",
            "cache_level": None,
            "error": "Schema version not initialized. Please run /system/sync-schema first.",
            "is_cached": False,
            "debug": _debug_payload(),
        }

    cached = get_cached_response(req.question, schema_version=schema_version)
    if cached:
        checked_sql = None
        semantic_guard_passed = None
        semantic_guard_error = None
        explain_passed = None
        explain_reason = None
        explain_plan = None
        schema_context = None
        examples_context = None

        if cached.get("sql"):
            schema_context, examples_context = await build_generation_context(req.question)
            try:
                (
                    checked_sql,
                    semantic_guard_passed,
                    semantic_guard_error,
                    explain_plan,
                    explain_passed,
                    explain_reason,
                ) = _validate_guard_and_explain(
                    question=req.question,
                    sql=cached["sql"],
                    schema_context=schema_context,
                )
            except Exception as e:
                semantic_guard_error = f"Cached SQL validation failed: {str(e)}"

        return {
            "question": req.question,
            "query_plan": cached.get("query_plan"),
            "generated_sql": cached.get("sql"),
            "validated_sql": checked_sql,
            "uncertainty_note": cached.get("uncertainty_note"),
            "answerable": cached.get("answerable", True),
            "schema_version": schema_version,
            "cache_status": cached.get("status", "unknown"),
            "cache_level": cached.get("cache_level"),
            "error": cached.get("error"),
            "is_cached": True,
            "debug": _debug_payload(
                schema_context=schema_context,
                examples_context=examples_context,
                semantic_guard_passed=semantic_guard_passed,
                semantic_guard_error=semantic_guard_error,
                explain_passed=explain_passed,
                explain_reason=explain_reason,
                explain_plan=explain_plan,
            ),
        }

    schema_context, examples_context = await build_generation_context(req.question)

    query_plan, sql, uncertainty, answerable = await generate_sql_from_question(
        req.question,
        schema_context=schema_context,
        examples_context=examples_context,
        debug=True,
    )

    checked_sql = None
    error_msg = None
    semantic_guard_passed = False
    semantic_guard_error = None
    explain_passed = None
    explain_reason = None
    explain_plan = None

    if not answerable or not sql:
        rejection_reason = uncertainty or "Question cannot be answered from current schema."
        return {
            "question": req.question,
            "query_plan": query_plan,
            "generated_sql": None,
            "validated_sql": None,
            "uncertainty_note": uncertainty,
            "answerable": False,
            "schema_version": schema_version,
            "cache_status": "rejected",
            "cache_level": None,
            "error": rejection_reason,
            "is_cached": False,
            "debug": _debug_payload(
                schema_context=schema_context,
                examples_context=examples_context,
                semantic_guard_passed=False,
                semantic_guard_error="Model returned answerable=false or empty SQL.",
                explain_passed=None,
                explain_reason=None,
                explain_plan=None,
            ),
        }

    try:
        (
            checked_sql,
            semantic_guard_passed,
            semantic_guard_error,
            explain_plan,
            explain_passed,
            explain_reason,
        ) = _validate_guard_and_explain(
            question=req.question,
            sql=sql,
            schema_context=schema_context,
        )

        if not semantic_guard_passed:
            error_msg = f"Semantic validation failed: {semantic_guard_error}"
        elif not explain_passed:
            error_msg = f"Execution-time EXPLAIN rejected the query: {explain_reason}"
    except Exception as e:
        error_msg = f"SQL validation failed: {str(e)}"

    return {
        "question": req.question,
        "query_plan": query_plan,
        "generated_sql": sql,
        "validated_sql": checked_sql,
        "uncertainty_note": uncertainty,
        "answerable": answerable,
        "schema_version": schema_version,
        "cache_status": "not_cached",
        "cache_level": None,
        "error": error_msg,
        "is_cached": False,
        "debug": _debug_payload(
            schema_context=schema_context,
            examples_context=examples_context,
            semantic_guard_passed=semantic_guard_passed,
            semantic_guard_error=semantic_guard_error,
            explain_passed=explain_passed,
            explain_reason=explain_reason,
            explain_plan=explain_plan,
        ),
    }


@router.post("/query/run")
async def query_run(req: QueryRequest):
    uncertainty = None
    error_msg = None
    columns, rows = [], []
    checked_sql = None
    semantic_guard_passed = False
    is_cached = False

    schema_version = get_current_schema_version()
    if not schema_version:
        return {
            "question": req.question,
            "query_plan": None,
            "sql": None,
            "uncertainty_note": None,
            "columns": [],
            "rows": [],
            "error": "Schema version not initialized. Please run /system/sync-schema first.",
            "cache_status": "not_initialized",
            "cache_level": None,
            "is_cached": False,
        }

    cached = get_cached_response(req.question, schema_version=schema_version)
    if cached:
        return {
            "question": req.question,
            "query_plan": cached.get("query_plan"),
            "sql": cached.get("sql"),
            "uncertainty_note": cached.get("uncertainty_note"),
            "columns": cached.get("columns", []),
            "rows": cached.get("rows", []),
            "error": cached.get("error"),
            "cache_status": cached.get("status", "unknown"),
            "cache_level": cached.get("cache_level"),
            "is_cached": True,
        }

    schema_context, examples_context = await build_generation_context(req.question)
    if not schema_context:
        return {
            "question": req.question,
            "query_plan": None,
            "sql": None,
            "uncertainty_note": None,
            "columns": [],
            "rows": [],
            "error": "No relevant schema context found. Please run /system/sync-schema and retry.",
            "cache_status": "not_cached",
            "cache_level": None,
            "is_cached": False,
        }

    query_plan, sql, uncertainty, answerable = await generate_sql_from_question(
        req.question,
        schema_context=schema_context,
        examples_context=examples_context,
        debug=False,
    )

    if not answerable or not sql:
        rejection_reason = uncertainty or "Question cannot be answered from current schema."

        if should_cache_rejection(
            is_cached=is_cached,
            answerable=False,
            rejection_reason=rejection_reason,
        ):
            set_cached_rejection(
                question=req.question,
                schema_version=schema_version,
                query_plan=query_plan,
                reason=rejection_reason,
                uncertainty_note=uncertainty,
            )

        return {
            "question": req.question,
            "query_plan": query_plan,
            "sql": None,
            "uncertainty_note": uncertainty,
            "columns": [],
            "rows": [],
            "error": rejection_reason,
            "cache_status": "rejected",
            "cache_level": None,
            "is_cached": False,
        }

    try:
        (
            checked_sql,
            semantic_guard_passed,
            semantic_guard_error,
            explain_plan,
            explain_passed,
            explain_reason,
        ) = _validate_guard_and_explain(
            question=req.question,
            sql=sql,
            schema_context=schema_context,
        )

        if not semantic_guard_passed:
            raise ValueError(f"Semantic validation failed: {semantic_guard_error}")

        if not explain_passed:
            raise ValueError(f"Execution-time EXPLAIN rejected the query: {explain_reason}")

        columns, rows = run_query(checked_sql)

    except Exception as e:
        first_error = str(e)
        repair_input_sql = checked_sql or sql

        try:
            query_plan, repaired_sql, repaired_uncertainty = await repair_sql(
                req.question,
                first_error,
                repair_input_sql,
                schema_context,
            )

            if not repaired_sql:
                raise ValueError(
                    repaired_uncertainty or "AI could not generate a valid fix for this question."
                )

            (
                checked_sql,
                repaired_guard_passed,
                repaired_guard_reason,
                repaired_explain_plan,
                repaired_explain_passed,
                repaired_explain_reason,
            ) = _validate_guard_and_explain(
                question=req.question,
                sql=repaired_sql,
                schema_context=schema_context,
            )

            if not repaired_guard_passed:
                raise ValueError(
                    f"Repaired SQL failed semantic validation: {repaired_guard_reason}"
                )

            if not repaired_explain_passed:
                raise ValueError(
                    f"Repaired SQL still failed EXPLAIN checks: {repaired_explain_reason}"
                )

            columns, rows = run_query(checked_sql)
            uncertainty = repaired_uncertainty
            semantic_guard_passed = True

        except Exception as e2:
            checked_sql = None
            error_msg = f"Self-correction failed: {str(e2)}"
            columns, rows = [], []

    if should_cache_success(
        error_msg=error_msg,
        is_cached=is_cached,
        answerable=True,
        checked_sql=checked_sql,
        semantic_guard_passed=semantic_guard_passed,
    ):
        set_cached_success(
            question=req.question,
            schema_version=schema_version,
            query_plan=query_plan,
            sql=checked_sql,
            columns=columns,
            rows=rows,
            uncertainty_note=uncertainty,
        )
        cache_status = "success"
    else:
        cache_status = "not_cached"

    return {
        "question": req.question,
        "query_plan": query_plan,
        "sql": checked_sql,
        "uncertainty_note": uncertainty,
        "columns": columns,
        "rows": rows,
        "error": error_msg,
        "cache_status": cache_status,
        "cache_level": None,
        "is_cached": False,
    }


@router.post("/system/sync-schema")
async def api_sync_schema():
    result = await sync_mysql_schema_to_pg()
    return result


@router.post("/system/add-example")
async def add_example(req: ExampleRequest):
    checked_sql = validate_sql(req.sql)
    embedding = await get_embedding(req.question)
    save_sql_example(req.question, checked_sql, embedding)
    new_examples_version = bump_examples_version()

    return {
        "status": "success",
        "msg": "Example successfully added to knowledge base.",
        "examples_version": new_examples_version,
    }