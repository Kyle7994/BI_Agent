# -*- coding: utf-8 -*-

"""
app/services/redis_service.py

This module implements the caching layer for the Text-to-SQL application.

It provides a two-level cache:
- L1: process-local TTL cache for ultra-fast repeat hits within one API worker
- L2: Redis distributed cache for cross-worker / cross-instance sharing

The cache key is a versioned fingerprint over:
- normalized question
- schema version
- prompt/model/guard/validator/examples versions
- cache structure version
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import redis
from cachetools import TTLCache

from app.config import LLM_MODEL, REDIS_URL

# ===================================
# Cache Configuration
# ===================================
CACHE_ENV = os.getenv("CACHE_ENV", "dev")
SUCCESS_TTL_SECONDS = int(os.getenv("SUCCESS_TTL_SECONDS", "3600"))   # 1 hour
REJECT_TTL_SECONDS = int(os.getenv("REJECT_TTL_SECONDS", "300"))      # 5 minutes

# L1 local cache
L1_CACHE_MAXSIZE = int(os.getenv("L1_CACHE_MAXSIZE", "1024"))
L1_CACHE_TTL_SECONDS = int(os.getenv("L1_CACHE_TTL_SECONDS", "60"))
_l1_cache: TTLCache[str, dict[str, Any]] = TTLCache(
    maxsize=L1_CACHE_MAXSIZE,
    ttl=L1_CACHE_TTL_SECONDS,
)

# ===================================
# Cache Versioning
# ===================================
CACHE_VERSION = "v4"
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "prompt_v4")
GUARD_VERSION = os.getenv("GUARD_VERSION", "guard_v3")
VALIDATOR_VERSION = os.getenv("VALIDATOR_VERSION", "validator_v2")
DEFAULT_EXAMPLES_VERSION = os.getenv("EXAMPLES_VERSION", "examples_v1")
MODEL_NAME = os.getenv("LLM_MODEL", LLM_MODEL or "unknown_model")

# ===================================
# Redis Keys for Dynamic Versions
# ===================================
CURRENT_SCHEMA_VERSION_KEY = "nl2sql:current_schema_version"
CURRENT_EXAMPLES_VERSION_KEY = "nl2sql:current_examples_version"

# Initialize the Redis client.
redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
    health_check_interval=30,
    retry_on_timeout=True,
)

# ===================================
# Helper Functions
# ===================================

def _make_json_safe(value: Any) -> Any:
    """Recursively converts non-JSON-serializable types to JSON-safe values."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(v) for v in value]
    return value


def utc_now_iso() -> str:
    """Returns the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalize_question(question: str) -> str:
    """
    Normalizes a question for caching by converting to lowercase,
    stripping whitespace, and collapsing multiple spaces.
    """
    return " ".join(question.strip().lower().split())


def clear_local_cache() -> None:
    """Clears the in-process L1 cache. Useful in tests or manual admin flows."""
    _l1_cache.clear()


# ===================================
# Dynamic Version Management
# ===================================

def set_current_schema_version(schema_version: str) -> None:
    """Sets the current global schema version in Redis."""
    try:
        redis_client.set(CURRENT_SCHEMA_VERSION_KEY, schema_version)
    except redis.RedisError:
        pass


def get_current_schema_version() -> str | None:
    """Retrieves the current global schema version from Redis."""
    try:
        return redis_client.get(CURRENT_SCHEMA_VERSION_KEY)
    except redis.RedisError:
        return None


def get_current_examples_version() -> str:
    """Retrieves the current global few-shot examples version from Redis."""
    try:
        return redis_client.get(CURRENT_EXAMPLES_VERSION_KEY) or DEFAULT_EXAMPLES_VERSION
    except redis.RedisError:
        return DEFAULT_EXAMPLES_VERSION


def bump_examples_version() -> str:
    """Increments the few-shot examples version, invalidating related caches."""
    current = get_current_examples_version()
    try:
        suffix = int(current.rsplit("v", 1)[1])
        new_version = f"examples_v{suffix + 1}"
    except (IndexError, ValueError):
        new_version = f"{DEFAULT_EXAMPLES_VERSION}_bumped_at_{utc_now_iso()}"

    try:
        redis_client.set(CURRENT_EXAMPLES_VERSION_KEY, new_version)
    except redis.RedisError:
        pass
    return new_version


def _resolve_examples_version(examples_version: str | None = None) -> str:
    """Use the provided examples_version or fall back to the global one."""
    return examples_version or get_current_examples_version()


# ===================================
# Cache Key Generation
# ===================================

def compute_fingerprint(
    question: str,
    schema_version: str,
    prompt_version: str = PROMPT_VERSION,
    model_name: str = MODEL_NAME,
    guard_version: str = GUARD_VERSION,
    validator_version: str = VALIDATOR_VERSION,
    examples_version: str | None = None,
) -> str:
    """
    Computes a SHA256 fingerprint for the query context.
    """
    normalized_question = normalize_question(question)
    resolved_examples_version = _resolve_examples_version(examples_version)

    raw = "||".join(
        [
            normalized_question,
            schema_version,
            prompt_version,
            model_name,
            guard_version,
            validator_version,
            resolved_examples_version,
            CACHE_VERSION,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_cache_key(
    question: str,
    schema_version: str,
    prompt_version: str = PROMPT_VERSION,
    model_name: str = MODEL_NAME,
    guard_version: str = GUARD_VERSION,
    validator_version: str = VALIDATOR_VERSION,
    examples_version: str | None = None,
) -> str:
    """Constructs the full cache key from the computed fingerprint."""
    fp = compute_fingerprint(
        question=question,
        schema_version=schema_version,
        prompt_version=prompt_version,
        model_name=model_name,
        guard_version=guard_version,
        validator_version=validator_version,
        examples_version=examples_version,
    )
    return f"nl2sql:cache:{CACHE_ENV}:{fp}"


# ===================================
# Internal Read/Write Helpers
# ===================================

def _load_payload_from_redis(key: str) -> Optional[dict[str, Any]]:
    try:
        raw = redis_client.get(key)
    except redis.RedisError:
        return None

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        try:
            redis_client.delete(key)
        except redis.RedisError:
            pass
        return None

    if payload.get("cache_version") != CACHE_VERSION:
        try:
            redis_client.delete(key)
        except redis.RedisError:
            pass
        return None

    return payload


def _write_both_levels(key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
    safe_payload = _make_json_safe(payload)

    # L1 write
    _l1_cache[key] = copy.deepcopy(safe_payload)

    # L2 write
    try:
        redis_client.setex(key, ttl_seconds, json.dumps(safe_payload, ensure_ascii=False))
    except redis.RedisError:
        pass


# ===================================
# Cache Read/Write Operations
# ===================================

def get_cached_response(question: str, schema_version: str, **kwargs) -> Optional[dict[str, Any]]:
    """
    Retrieves a cached response.

    Order:
    1. L1 process-local TTL cache
    2. L2 Redis cache
    """
    key = build_cache_key(question=question, schema_version=schema_version, **kwargs)

    # L1
    local_payload = _l1_cache.get(key)
    if local_payload is not None:
        payload = copy.deepcopy(local_payload)
        payload["cache_level"] = "L1"
        return payload

    # L2
    payload = _load_payload_from_redis(key)
    if payload is None:
        return None

    # Promote to L1
    _l1_cache[key] = copy.deepcopy(payload)

    payload = copy.deepcopy(payload)
    payload["cache_level"] = "L2"
    return payload


def set_cached_success(
    question: str,
    schema_version: str,
    query_plan: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
    uncertainty_note: str | None = None,
    ttl_seconds: int = SUCCESS_TTL_SECONDS,
    **kwargs,
) -> None:
    """Stores a successful result in both L1 and L2 caches."""
    key = build_cache_key(question=question, schema_version=schema_version, **kwargs)
    payload = {
        "status": "success",
        "question": question,
        "sql": sql,
        "query_plan": query_plan,
        "columns": columns,
        "rows": rows,
        "uncertainty_note": uncertainty_note,
        "answerable": True,
        "error": None,
        "schema_version": schema_version,
        "cache_version": CACHE_VERSION,
        "created_at": utc_now_iso(),
        "ttl_seconds": ttl_seconds,
        **kwargs,
    }
    _write_both_levels(key, payload, ttl_seconds)


def set_cached_rejection(
    question: str,
    schema_version: str,
    query_plan: str,
    reason: str,
    uncertainty_note: str | None = None,
    ttl_seconds: int = REJECT_TTL_SECONDS,
    **kwargs,
) -> None:
    """Stores an explicit rejection result in both L1 and L2 caches."""
    key = build_cache_key(question=question, schema_version=schema_version, **kwargs)
    payload = {
        "status": "rejected",
        "question": question,
        "sql": None,
        "query_plan": query_plan,
        "columns": [],
        "rows": [],
        "uncertainty_note": uncertainty_note,
        "answerable": False,
        "error": reason,
        "schema_version": schema_version,
        "cache_version": CACHE_VERSION,
        "created_at": utc_now_iso(),
        "ttl_seconds": ttl_seconds,
        **kwargs,
    }
    _write_both_levels(key, payload, ttl_seconds)


# ===================================
# Cache Decision Logic
# ===================================

def should_cache_success(
    *,
    error_msg: str | None,
    is_cached: bool,
    answerable: bool,
    checked_sql: str | None,
    semantic_guard_passed: bool,
) -> bool:
    """Determines if a successful result is eligible for caching."""
    return (
        error_msg is None
        and not is_cached
        and answerable
        and checked_sql is not None
        and checked_sql.strip() != ""
        and semantic_guard_passed
    )


def should_cache_rejection(
    *,
    is_cached: bool,
    answerable: bool,
    rejection_reason: str | None,
) -> bool:
    """Determines if a rejection is eligible for caching."""
    return (
        not is_cached
        and not answerable
        and rejection_reason is not None
        and rejection_reason.strip() != ""
    )