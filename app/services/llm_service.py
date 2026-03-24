import httpx
from app.config import LLM_BASE_URL, LLM_MODEL

SCHEMA_PROMPT = """
You are a MySQL SQL generator.

Database schema:
- users(id, email, country, signup_at, channel, is_vip)
- orders(id, user_id, status, total_amount, created_at, paid_at)
- products(id, name, category, price, created_at)
- order_items(id, order_id, product_id, quantity, unit_price, subtotal)

Rules:
- Output ONLY one SQL SELECT statement
- Do NOT explain anything
- Do NOT include markdown
- Only use given tables
- Always include LIMIT
- Prefer explicit column names
"""

async def generate_sql_from_question(question: str) -> str:
    prompt = f"""{SCHEMA_PROMPT}

User question:
{question}
"""
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