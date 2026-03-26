import pytest

def test_query_run_not_initialized(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.get_current_schema_version", lambda: None)

    resp = client.post("/query/run", json={"question": "check orders"})
    data = resp.json()

    assert resp.status_code == 200
    assert data["cache_status"] == "not_initialized"
    assert data["sql"] is None
    assert data["rows"] == []

def test_query_run_cache_hit(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.get_current_schema_version", lambda: "v1")
    monkeypatch.setattr(
        "app.api.routes.get_cached_response",
        lambda *args, **kwargs: {
            "query_plan": "cached plan",
            "sql": "SELECT 1",
            "uncertainty_note": None,
            "columns": ["x"],
            "rows": [[1]],
            "error": None,
            "status": "cache_hit",
            "cache_level": "redis",
        },
    )

    resp = client.post("/query/run", json={"question": "test"})
    data = resp.json()

    assert resp.status_code == 200
    assert data["is_cached"] is True
    assert data["sql"] == "SELECT 1"
    assert data["rows"] == [[1]]

@pytest.mark.asyncio
async def test_query_run_no_schema_context(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.get_current_schema_version", lambda: "v1")
    monkeypatch.setattr("app.api.routes.get_cached_response", lambda *args, **kwargs: None)

    async def fake_build_generation_context(question):
        return ("", "examples_context")

    monkeypatch.setattr("app.api.routes.build_generation_context", fake_build_generation_context)

    resp = client.post("/query/run", json={"question": "check orders"})
    data = resp.json()

    assert resp.status_code == 200
    assert data["sql"] is None
    assert "No relevant schema context found" in data["error"]

@pytest.mark.asyncio
async def test_query_run_generate_only(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.get_current_schema_version", lambda: "v1")
    monkeypatch.setattr("app.api.routes.get_cached_response", lambda *args, **kwargs: None)

    async def fake_build_generation_context(question):
        return ("schema_context", "examples_context")

    async def fake_generate_sql_from_question(question, schema_context, examples_context, debug):
        assert debug is False
        return ("plan", "SELECT * FROM users", None, True)

    monkeypatch.setattr("app.api.routes.build_generation_context", fake_build_generation_context)
    monkeypatch.setattr("app.api.routes.generate_sql_from_question", fake_generate_sql_from_question)

    resp = client.post("/query/run", json={"question": "check users"})
    data = resp.json()

    assert resp.status_code == 200
    assert data["sql"] == "SELECT * FROM users"
    assert data["rows"] == []
    assert data["error"] is None