import httpx
import json
from app.config import LLM_BASE_URL, LLM_MODEL
from app.services.embedding_service import get_embedding
from app.services.postgres_service import search_schema_chunks, search_sql_examples

# 提示词大升级：强制要求输出 JSON，并且必须先写 query_plan
BASE_PROMPT = """
You are an expert MySQL SQL generator. 

You MUST respond strictly in the following JSON format:
{
    "query_plan": "Step 1: ..., Step 2: ...",
    "sql": "SELECT ...",
    "uncertainty_note": "Optional: Describe any ambiguities or assumptions made."
}

Rules:
1. "query_plan": Provide a clear, step-by-step logical breakdown.
2. "sql": A single, executable MySQL SELECT statement.
3. "uncertainty_note": 
   - MANDATORY: If the user uses subjective terms (e.g., 'recent', 'top', 'active', 'big') that are not explicitly defined in the table schema, you MUST state your assumption here.
   - Example: "I assumed 'recent' means within the last 30 days as no specific timeframe was provided."
   - If the prompt is 100% clear based on the schema, set this to null.

Database Schema:
- Only use tables/columns provided in the Context Schema.
"""

async def generate_sql_from_question(question: str) -> tuple[str, str]:
    question_embedding = await get_embedding(question)
    
    relevant_schemas = search_schema_chunks(question_embedding, limit=3)
    schema_context = "\n\n".join(relevant_schemas)
    
    similar_examples = search_sql_examples(question_embedding, limit=2)
    examples_context = ""
    if similar_examples:
        examples_context = "Here are some similar verified examples for reference:\n"
        for ex in similar_examples:
            examples_context += f"Question: {ex['question']}\nSQL: {ex['sql']}\n\n"
    
    prompt = f"""{BASE_PROMPT}

Context Schema:
{schema_context}

{examples_context}
User question:
{question}
"""
    print("--- DYNAMIC PROMPT ---")
    print(prompt)
    print("----------------------")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/api/generate",
            json={
                "model": LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"  # Ollama 的特殊参数，强制约束模型按 JSON 格式吐字
            },
        )
        resp.raise_for_status()
        response_text = resp.json()["response"].strip()
        
        # 解析返回的 JSON
        try:
            result = json.loads(response_text)
            return result.get("query_plan", "No plan generated."), result.get("sql", ""), result.get("uncertainty_note", None)
        except json.JSONDecodeError:
            # 兜底：万一大模型没听话，带了 markdown 壳子
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            result = json.loads(response_text)
            return result.get("query_plan", ""), result.get("sql", ""), result.get("uncertainty_note", None)
        

async def repair_sql(question: str, error_msg: str, wrong_sql: str, schema_context: str) -> tuple[str, str]:
    """当 SQL 报错时，调模型进行自愈"""
    repair_prompt = f"""
You are a MySQL expert. The SQL you generated previously failed.
User Question: {question}
Wrong SQL: {wrong_sql}
Error Message: {error_msg}

Context Schema:
{schema_context}

Please analyze the error, fix the SQL, and return a new JSON with "query_plan" and "sql". 
Ensure the SQL is valid MySQL and follows the rules.
"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/api/generate",
            json={
                "model": LLM_MODEL,
                "prompt": repair_prompt,
                "stream": False,
                "format": "json"
            },
        )
        resp.raise_for_status()
        result = json.loads(resp.json()["response"].strip())
        return result.get("query_plan", ""), result.get("sql", ""), result.get("uncertainty_note", None)