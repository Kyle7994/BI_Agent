import redis
import json
import hashlib
from app.config import REDIS_HOST, REDIS_PORT

# 连接 Redis（设置 decode_responses=True 方便直接处理字符串）
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

def _get_hash_key(question: str) -> str:
    """把长文本问题转换成短的 MD5 摘要，作为 Redis 的 Key"""
    question_md5 = hashlib.md5(question.strip().encode('utf-8')).hexdigest()
    return f"bi_agent:cache:{question_md5}"

def get_cached_response(question: str) -> dict | None:
    """尝试从 Redis 获取缓存的 SQL"""
    cache_key = _get_hash_key(question)
    cached_data = redis_client.get(cache_key)
    
    if cached_data:
        return json.loads(cached_data)
    return None

def set_cached_response(question: str, query_plan: str, sql: str, expire_seconds: int = 3600):
    """将大模型生成的结果存入 Redis，默认缓存 1 小时"""
    cache_key = _get_hash_key(question)
    data = {
        "query_plan": query_plan,
        "sql": sql
    }
    # 使用 setex 同时设置值和过期时间
    redis_client.setex(cache_key, expire_seconds, json.dumps(data))