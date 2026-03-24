import httpx
from app.config import LLM_BASE_URL

EMBEDDING_MODEL = "nomic-embed-text"

async def get_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/api/embeddings",
            json={
                "model": EMBEDDING_MODEL,
                "prompt": text
            }
        )
        resp.raise_for_status()
        return resp.json()["embedding"]