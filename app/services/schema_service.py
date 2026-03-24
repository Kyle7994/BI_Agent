from app.services.mysql_service import get_conn
from app.services.embedding_service import get_embedding
from app.services.postgres_service import clear_and_save_schema_chunks
from app.config import MYSQL_DB

async def sync_mysql_schema_to_pg():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 抽取表和字段信息
            cur.execute("""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = %s
            """, (MYSQL_DB,))
            rows = cur.fetchall()
            
            # 按表名分组
            tables = {}
            for table_name, column_name, data_type in rows:
                if table_name not in tables:
                    tables[table_name] = []
                tables[table_name].append(f"{column_name} ({data_type})")

        # 构建 Chunk 并生成向量
        chunks = []
        for table_name, columns in tables.items():
            # 构造要被检索的文本内容
            content = f"Table: {table_name}\nColumns: {', '.join(columns)}"
            
            # 调用 Ollama 生成向量
            embedding = await get_embedding(content)
            
            chunks.append({
                "chunk_type": "table_schema",
                "source_name": table_name,
                "content": content,
                "metadata": {"table": table_name},
                "embedding": embedding
            })
        
        # 存入 Postgres
        if chunks:
            clear_and_save_schema_chunks(chunks)
            
        return {"status": "success", "tables_synced": len(chunks)}
        
    finally:
        conn.close()