import httpx
from app.config import LLM_BASE_URL, LLM_MODEL
from app.services.embedding_service import get_embedding
from app.services.postgres_service import search_schema_chunks, search_sql_examples

BASE_PROMPT = """
You are an expert MySQL SQL generator.

Rules:
- Generate exactly one MySQL SELECT statement
- Only use existing tables and columns provided in the Context Schema below
- Prefer explicit column names
- Do not explain
- Do not output markdown code blocks, just raw SQL
"""

async def generate_sql_from_question(question: str) -> str:
    # 1. 问题向量化
    question_embedding = await get_embedding(question)
    
    # 2. 查表结构 (Context)
    relevant_schemas = search_schema_chunks(question_embedding, limit=3)
    schema_context = "\n\n".join(relevant_schemas)
    
    # 3. 查历史范例 (Few-shot) -> 【这是新增的魔法】
    similar_examples = search_sql_examples(question_embedding, limit=2)
    examples_context = ""
    if similar_examples:
        examples_context = "Here are some similar verified examples for reference:\n"
        for ex in similar_examples:
            examples_context += f"Question: {ex['question']}\nSQL: {ex['sql']}\n\n"
    
    # 4. 组装终极 Prompt
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

    # 5. 调用大模型
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/api/generate",
            json={
                "model": LLM_MODEL,
                "prompt": prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()["response"].strip()