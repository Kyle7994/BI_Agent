import pymysql
from fastapi import APIRouter
from pydantic import BaseModel

# 引入自定义服务
from app.models.schemas import QueryRequest
from app.services.llm_service import generate_sql_from_question, repair_sql # <--- 补上 repair_sql
from app.services.guard_service import validate_sql
from app.services.mysql_service import run_query
from app.services.schema_service import sync_mysql_schema_to_pg
from app.services.embedding_service import get_embedding
from app.services.redis_service import get_cached_response, set_cached_response

# 补上检索相关的服务
from app.services.postgres_service import (
    save_sql_example, 
    search_schema_chunks # <--- 补上这个，否则报错 NameError
)

# 定义接收数据的格式
class ExampleRequest(BaseModel):
    question: str
    sql: str


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/query/debug")
async def query_debug(req: QueryRequest):
    # 1. 查缓存
    cached = get_cached_response(req.question)
    if cached:
        # 如果命中缓存，直接走安全校验然后返回
        checked_sql = validate_sql(cached["sql"])
        return {
            "question": req.question,
            "query_plan": cached["query_plan"],
            "generated_sql": cached["sql"],
            "validated_sql": checked_sql,
            "is_cached": True  # 加个标记，前端可以据此显示一个“闪电”图标
        }

    # 2. 如果没命中，老老实实调大模型
    query_plan, sql = await generate_sql_from_question(req.question)
    
    # 3. 拿到结果后，存入缓存
    set_cached_response(req.question, query_plan, sql)
    
    checked_sql = validate_sql(sql)
    return {
        "question": req.question,
        "query_plan": query_plan,
        "generated_sql": sql,
        "validated_sql": checked_sql,
        "is_cached": False
    }


@router.post("/query/run")
async def query_run(req: QueryRequest):
    # 1. 尝试获取缓存
    cached = get_cached_response(req.question)
    uncertainty = None

    if cached:
        query_plan = cached["query_plan"]
        sql = cached["sql"]
        is_cached = True
    else:
        # 如果没有缓存，调大模型生成
        query_plan, sql, uncertainty = await generate_sql_from_question(req.question)
        is_cached = False

    # 2. 执行与自愈逻辑
    error_msg = None
    columns, rows = [], []
    
    try:
        # 第一次尝试
        print(f"🚀 [Attempt 1] Running SQL: {sql}")
        checked_sql = validate_sql(sql)
        columns, rows = run_query(checked_sql)
    except Exception as e:
        # --- 触发自愈逻辑 ---
        first_error = str(e)
        print(f"❌ [Attempt 1 Failed] Error: {first_error}. Starting repair...")
        
        try:
            # 重新检索 Schema 上下文
            q_emb = await get_embedding(req.question)
            schemas = search_schema_chunks(q_emb, limit=3)
            schema_context = "\n\n".join(schemas)
            
            # 调纠错模型
            query_plan, sql, uncertainty = await repair_sql(req.question, first_error, sql, schema_context)
            
            print(f"♻️ [Repair Success] New SQL: {sql}")
            checked_sql = validate_sql(sql)
            columns, rows = run_query(checked_sql)
            error_msg = None  # 修复成功
        except Exception as e2:
            checked_sql = sql # 即使失败也返回最后一次尝试的 SQL
            error_msg = f"Self-correction failed: {str(e2)}"
            columns, rows = [], []

    # 3. 如果运行成功且不是缓存，存入 Redis
    if not error_msg and not is_cached:
        set_cached_response(req.question, query_plan, checked_sql)

    return {
        "question": req.question,
        "query_plan": query_plan,
        "sql": checked_sql,
        "uncertainty_note": uncertainty, # 告诉用户：AI在这里犹豫了
        "columns": columns,
        "rows": rows,
        "error": error_msg,
        "is_cached": is_cached
    }


@router.post("/system/sync-schema")
async def api_sync_schema():
    """触发 MySQL 表结构抽取，向量化后存入 Postgres"""
    result = await sync_mysql_schema_to_pg()
    return result


@router.post("/system/add-example")
async def add_example(req: ExampleRequest):
    """人工喂给大模型一条标准 SQL 范例"""
    embedding = await get_embedding(req.question)
    save_sql_example(req.question, req.sql, embedding)
    return {"status": "success", "msg": "Example successfully added to knowledge base!"}