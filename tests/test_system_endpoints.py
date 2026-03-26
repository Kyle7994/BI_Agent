import pytest

def test_add_example(client, monkeypatch):
    called = {}

    def fake_validate_sql(sql):
        called["validated_sql"] = sql
        return "SELECT * FROM orders"

    async def fake_get_embedding(question):
        called["question"] = question
        return [0.1, 0.2, 0.3]

    def fake_save_sql_example(question, sql, embedding):
        called["saved"] = (question, sql, embedding)

    def fake_bump_examples_version():
        return 2

    monkeypatch.setattr("app.api.routes.validate_sql", fake_validate_sql)
    monkeypatch.setattr("app.api.routes.get_embedding", fake_get_embedding)
    monkeypatch.setattr("app.api.routes.save_sql_example", fake_save_sql_example)
    monkeypatch.setattr("app.api.routes.bump_examples_version", fake_bump_examples_version)

    resp = client.post(
        "/system/add-example",
        json={"question": "check orders", "sql": "select * from orders"},
    )
    data = resp.json()

    assert resp.status_code == 200
    assert data["status"] == "success"
    assert data["examples_version"] == 2
    assert called["saved"][0] == "check orders"
    assert called["saved"][1] == "SELECT * FROM orders"
    assert called["saved"][2] == [0.1, 0.2, 0.3]

@pytest.mark.asyncio
async def test_sync_schema(client, monkeypatch):
    async def fake_sync_mysql_schema_to_pg():
        return {"status": "ok", "tables": 10}

    monkeypatch.setattr("app.api.routes.sync_mysql_schema_to_pg", fake_sync_mysql_schema_to_pg)

    resp = client.post("/system/sync-schema")
    data = resp.json()

    assert resp.status_code == 200
    assert data["status"] == "ok"
    assert data["tables"] == 10