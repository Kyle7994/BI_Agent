import psycopg
import json
from app.config import PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD

def get_pg_conn():
    return psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        autocommit=True
    )

def clear_and_save_schema_chunks(chunks: list[dict]):
    """清空旧数据并插入新的 Schema 向量"""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE schema_chunks;")
            for chunk in chunks:
                cur.execute(
                    """
                    INSERT INTO schema_chunks 
                    (chunk_type, source_name, content, metadata, embedding) 
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        chunk["chunk_type"],
                        chunk["source_name"],
                        chunk["content"],
                        json.dumps(chunk["metadata"]),
                        chunk["embedding"]
                    )
                )

def search_schema_chunks(query_embedding: list[float], limit: int = 3) -> list[str]:
    """使用 <-> (L2 距离) 检索最相关的表结构"""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            # 格式化向量为 pgvector 支持的字符串格式
            embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
            cur.execute(
                """
                SELECT content, metadata 
                FROM schema_chunks 
                ORDER BY embedding <-> %s::vector 
                LIMIT %s
                """,
                (embedding_str, limit)
            )
            rows = cur.fetchall()
            return [row[0] for row in rows]
        

def save_sql_example(question: str, sql_text: str, embedding: list[float]):
    """将优秀的 SQL 范例存入向量库"""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sql_examples (question, sql_text, features, embedding)
                VALUES (%s, %s, %s, %s)
                """,
                (question, sql_text, "{}", embedding) 
            )

def search_sql_examples(query_embedding: list[float], limit: int = 2) -> list[dict]:
    """根据用户问题，检索最相似的历史 SQL 范例"""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
            cur.execute(
                """
                SELECT question, sql_text 
                FROM sql_examples 
                ORDER BY embedding <-> %s::vector 
                LIMIT %s
                """,
                (embedding_str, limit)
            )
            rows = cur.fetchall()
            return [{"question": row[0], "sql": row[1]} for row in rows]