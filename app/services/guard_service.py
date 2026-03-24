import os
import sqlglot
from sqlglot import exp

# 建议把这行移到你的 app/config.py 里统一管理，这里为了直观先写在一起
# 默认关闭增删改，只有明确设为 "true" 时才放行
ENABLE_ADMIN_OPS = os.getenv("ENABLE_ADMIN_OPS", "false").lower() == "true"

ALLOWED_TABLES = {"users", "orders", "products", "order_items"}

def validate_sql(sql: str) -> str:
    # 尝试解析 SQL
    try:
        parsed = sqlglot.parse_one(sql, read="mysql")
    except Exception as e:
        raise ValueError(f"Failed to parse SQL: {e}")

    # 1. 提取 SQL 中涉及的所有表名（统一小写比对）
    tables = {t.name.lower() for t in parsed.find_all(exp.Table) if t.name}
    
    # 2. 表级白名单校验（拦截所有针对非业务表的操作）
    if not tables.issubset(ALLOWED_TABLES):
        raise ValueError(f"Forbidden tables detected: {tables - ALLOWED_TABLES}")

    # 3. 如果是查询操作 (SELECT)
    if isinstance(parsed, exp.Select):
        # 强制分页，保护数据库内存
        if parsed.args.get("limit") is None:
            parsed = parsed.limit(100)
        return parsed.sql(dialect="mysql")

    # 4. 如果是增删改操作 (INSERT / UPDATE / DELETE)
    elif isinstance(parsed, (exp.Insert, exp.Update, exp.Delete)):
        if not ENABLE_ADMIN_OPS:
            raise ValueError(f"Admin operations ({parsed.key.upper()}) are currently disabled by environment variable.")
        # 增删改放行，直接返回格式化后的 SQL
        return parsed.sql(dialect="mysql")

    # 5. 兜底：拦截 DROP, CREATE, ALTER 等危险高管操作
    else:
        raise ValueError(f"Unsupported or highly dangerous SQL operation: {parsed.key.upper()}")