# -*- coding: utf-8 -*-

"""
app/services/mysql_service.py

This module provides an interface for interacting with the MySQL database.

Responsibilities:
- Create resilient DB connections with retry logic
- Execute SQL queries
- Normalize result values to JSON-safe output
- Run pre-execution EXPLAIN checks to block obviously expensive plans
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor
from pymysql.err import InterfaceError, OperationalError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.config import MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER

EXPLAIN_MAX_ROWS = int(os.getenv("EXPLAIN_MAX_ROWS", "50000"))
EXPLAIN_BLOCK_FULL_SCAN_ROWS = int(os.getenv("EXPLAIN_BLOCK_FULL_SCAN_ROWS", "20000"))
EXPLAIN_TEMP_TABLE_ROWS = int(os.getenv("EXPLAIN_TEMP_TABLE_ROWS", "5000"))
EXPLAIN_FILESORT_ROWS = int(os.getenv("EXPLAIN_FILESORT_ROWS", "5000"))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=5),
    retry=retry_if_exception_type((OperationalError, InterfaceError)),
    reraise=True,
)
def get_conn():
    """
    Establishes and returns a connection to the MySQL database.
    """
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=pymysql.cursors.Cursor,
        autocommit=True,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=30,
        write_timeout=30,
    )


def _normalize_query_value(value: Any) -> Any:
    """
    Normalize DB values for JSON serialization.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def run_query(sql: str):
    """
    Executes a SQL query and returns (columns, rows).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            raw_rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [
                [_normalize_query_value(cell) for cell in row]
                for row in raw_rows
            ]
            return columns, rows
    finally:
        conn.close()


def explain_query(sql: str) -> list[dict[str, Any]]:
    """
    Runs EXPLAIN on the provided SQL and returns plan rows as dictionaries.
    """
    conn = get_conn()
    try:
        with conn.cursor(DictCursor) as cur:
            cur.execute(f"EXPLAIN {sql}")
            rows = cur.fetchall()
            return list(rows)
    finally:
        conn.close()


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def check_explain_plan(plan_rows: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """
    Applies lightweight heuristics to reject obviously risky query plans.

    Rejection rules:
    - Very large estimated row counts
    - Large full-table scans
    - Expensive temp table usage on non-trivial row counts
    - Filesort on non-trivial row counts
    """
    if not plan_rows:
        return False, "EXPLAIN returned no plan rows."

    problems: list[str] = []

    for row in plan_rows:
        access_type = str(row.get("type") or "").upper()
        table_name = str(row.get("table") or "<unknown>")
        est_rows = _safe_int(row.get("rows"))
        extra = str(row.get("Extra") or "")

        if est_rows > EXPLAIN_MAX_ROWS:
            problems.append(
                f"Estimated rows too high on table '{table_name}': {est_rows}"
            )

        if access_type == "ALL" and est_rows > EXPLAIN_BLOCK_FULL_SCAN_ROWS:
            problems.append(
                f"Full table scan detected on '{table_name}' with estimated rows={est_rows}"
            )

        if "Using temporary" in extra and est_rows > EXPLAIN_TEMP_TABLE_ROWS:
            problems.append(
                f"Temporary table usage detected on '{table_name}'"
            )

        if "Using filesort" in extra and est_rows > EXPLAIN_FILESORT_ROWS:
            problems.append(
                f"Filesort detected on '{table_name}'"
            )

    if problems:
        return False, "; ".join(problems)

    return True, None