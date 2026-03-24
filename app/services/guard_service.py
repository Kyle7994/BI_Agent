import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"users", "orders", "products", "order_items"}

def validate_sql(sql: str) -> str:
    parsed = sqlglot.parse_one(sql, read="mysql")

    if not isinstance(parsed, exp.Select):
        raise ValueError("Only SELECT is allowed")

    tables = {t.name for t in parsed.find_all(exp.Table)}
    if not tables.issubset(ALLOWED_TABLES):
        raise ValueError(f"Forbidden tables detected: {tables - ALLOWED_TABLES}")

    if parsed.args.get("limit") is None:
        parsed = parsed.limit(100)

    return parsed.sql(dialect="mysql")