import yaml
from httpx import AsyncClient

def assert_case(resp_json, case):
    behavior = case["expected_behavior"]

    if behavior == "answer":
        assert resp_json["error"] in (None, "")
        assert resp_json["sql"] is not None
        if "expected_rows" in case:
            assert resp_json["rows"] == case["expected_rows"]
        if "expected_row_set" in case:
            assert sorted(resp_json["rows"]) == sorted(case["expected_row_set"])
        if "assert_sql_contains" in case:
            sql = resp_json["sql"].lower()
            for token in case["assert_sql_contains"]:
                assert token.lower() in sql

    elif behavior == "refusal":
        assert resp_json["sql"] is None
        assert resp_json["error"]

    elif behavior == "refusal_or_validation_error":
        assert resp_json["error"]


async def test_eval_cases(app):
    cases = yaml.safe_load(open("tests/eval_cases.yaml", "r", encoding="utf-8"))
    async with AsyncClient(app=app, base_url="http://test") as ac:
        for case in cases:
            r = await ac.post("/query/run", json={"question": case["question"]})
            assert r.status_code == 200
            data = r.json()
            assert_case(data, case)

            if case.get("run_twice"):
                r2 = await ac.post("/query/run", json={"question": case["question"]})
                data2 = r2.json()
                assert_case(data2, case)
                if case.get("expect_second_is_cached"):
                    assert data2["is_cached"] is True