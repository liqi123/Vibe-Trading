"""Route-level contracts for the 交易计划 endpoints.

Covers import (line splitting + persistence), list (merge with check results),
and check (auction gate + LLM result merge). The plan root, auction rows and
LLM call are redirected to temp/mocks so nothing touches the real DB or network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import trade_plan_routes


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(trade_plan_routes, "_PLAN_ROOT", tmp_path / "trade_plan")
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _seed_auction(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        trade_plan_routes,
        "_auction_rows",
        lambda date: [
            ("600001", "涨停股甲", 11.0, 10.0, 50000.0, 40000, 11.0),
            ("000002", "高开股乙", 5.3, 5.0, 8000.0, 6000, 5.3),
            ("300003", "低开股丙", 4.0, 4.2, 3000.0, 2000, 4.0),
        ],
    )
    monkeypatch.setattr(trade_plan_routes, "_auction_collect_time", lambda date: "09:25:26")


def test_import_splits_lines_and_drops_comments(client: TestClient):
    res = client.post(
        "/tools/trade-plan/import",
        json={"date": "2026-10-24", "text": "\n# 盘前计划\n甲 高开3%\n\n乙 平开\n"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["items"] == ["甲 高开3%", "乙 平开"]
    listed = client.get("/tools/trade-plan/list?date=2026-10-24").json()
    assert listed["exists"] is True
    assert [i["text"] for i in listed["items"]] == ["甲 高开3%", "乙 平开"]
    assert listed["items"][0]["achieved"] is None


def test_import_rejects_empty_and_bad_date(client: TestClient):
    assert client.post("/tools/trade-plan/import", json={"date": "2026-10-24", "text": "# 只有注释\n\n"}).json()["ok"] is False
    assert client.post("/tools/trade-plan/import", json={"date": "bad", "text": "甲"}).json()["ok"] is False


def test_check_requires_plan_and_auction(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    assert client.post("/tools/trade-plan/check", json={"date": "2026-10-24"}).json()["ok"] is False
    client.post("/tools/trade-plan/import", json={"date": "2026-10-24", "text": "涨停股甲 一字开"})
    monkeypatch.setattr(trade_plan_routes, "_auction_rows", lambda date: [])
    body = client.post("/tools/trade-plan/check", json={"date": "2026-10-24"}).json()
    assert body["ok"] is False
    assert "竞价" in body["error"]


def test_check_merges_llm_results_and_caches(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _seed_auction(monkeypatch)
    client.post("/tools/trade-plan/import", json={"date": "2026-10-24", "text": "涨停股甲 一字开\n低开股丙 高开"})
    called = {}

    def fake_llm(items, context):
        called["items"] = items
        assert context["gap_buckets"]["涨停开盘"] == 1
        assert context["mentioned_stocks"][0]["name"] == "涨停股甲"
        return [
            {"index": 0, "achieved": True, "reason": "11.00 涨停开盘达标"},
            {"index": 1, "achieved": False, "reason": "低开4.8%未达标"},
        ]

    monkeypatch.setattr(trade_plan_routes, "_llm_check", fake_llm)
    body = client.post("/tools/trade-plan/check", json={"date": "2026-10-24"}).json()
    assert body["ok"] is True
    assert called["items"] == ["涨停股甲 一字开", "低开股丙 高开"]
    assert [i["achieved"] for i in body["items"]] == [True, False]
    assert body["checked_at"]

    listed = client.get("/tools/trade-plan/list?date=2026-10-24").json()
    assert listed["checked_at"] == body["checked_at"]
    assert [i["achieved"] for i in listed["items"]] == [True, False]

    # 重新导入计划应清除旧核对结果
    client.post("/tools/trade-plan/import", json={"date": "2026-10-24", "text": "新计划"})
    listed = client.get("/tools/trade-plan/list?date=2026-10-24").json()
    assert listed["checked_at"] is None
    assert listed["items"][0]["achieved"] is None


def test_parse_check_handles_fenced_array():
    raw = '```json\n[{"index":0,"achieved":true,"reason":"达标"}]\n```'
    assert trade_plan_routes._parse_check(raw) == [{"index": 0, "achieved": True, "reason": "达标"}]
    with pytest.raises(ValueError):
        trade_plan_routes._parse_check("没有数组")
