# schema_service.py

from app.services.mysql_service import get_conn
from app.services.embedding_service import get_embedding
from app.services.postgres_service import clear_and_save_schema_chunks
from app.services.redis_service import set_current_schema_version
from app.config import MYSQL_DB
import hashlib

def compute_schema_version(schema_text: str) -> str:
    return hashlib.sha256(schema_text.encode("utf-8")).hexdigest()[:16]

async def sync_mysql_schema_to_pg():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 抽取表和字段信息
            cur.execute("""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """, (MYSQL_DB,))
            rows = cur.fetchall()

            # 按表名分组
            tables = {}
            for table_name, column_name, data_type in rows:
                if table_name not in tables:
                    tables[table_name] = []
                tables[table_name].append(f"{column_name} ({data_type})")

        # 1. 先构造一个“全局、稳定”的 schema 文本，用来算 version
        # 这里用排序后的 table 顺序，确保 hash 稳定
        all_schema_text_parts = []
        for table_name in sorted(tables.keys()):
            columns_text = ", ".join(tables[table_name])
            all_schema_text_parts.append(f"Table: {table_name}\nColumns: {columns_text}")

        full_schema_text = "\n\n".join(all_schema_text_parts)
        schema_version = compute_schema_version(full_schema_text)

        # 2. 构建 Chunk 并生成向量
        chunks = []
        for table_name in sorted(tables.keys()):
            content = f"Table: {table_name}\nColumns: {', '.join(tables[table_name])}"
            embedding = await get_embedding(content)

            chunks.append({
                "chunk_type": "table_schema",
                "source_name": table_name,
                "content": content,
                "metadata": {
                    "table": table_name,
                    "schema_version": schema_version
                },
                "embedding": embedding
            })

        # 3. 存入 Postgres
        if chunks:
            clear_and_save_schema_chunks(chunks)

        # 4. 把当前 schema version 存到 Redis
        set_current_schema_version(schema_version)

        return {
            "status": "success",
            "tables_synced": len(chunks),
            "schema_version": schema_version
        }

    finally:
        conn.close()