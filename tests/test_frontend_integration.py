import io
import json
from types import SimpleNamespace
from urllib.error import URLError
import pytest
from fastapi.testclient import TestClient
from backend.agent import messages
from backend.agent.messages import MessageRequest
from backend.config import settings
from backend.db.session import get_session
from backend.domain.schemas import SimulationRequest
from backend.main import app
from backend.tools.runtime import BusinessError


@pytest.fixture
def web(db):
    def override():
        yield db
    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        client.headers["X-API-Key"] = settings().api_key
        yield client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("scenario,reorder,blocked", [("normal",9,0),("incoming",8,0),("exceptions",6,3)])
def test_demo_routes_feed_real_agent(web, scenario, reorder, blocked):
    demo = web.get(f"/api/v1/demo/{scenario}").json()["data"]
    batch = web.post("/api/v1/imports", json=demo["dataset"]).json()["data"]
    response = web.post("/api/v1/agent/review", json={**demo["policy"], "batch_id":batch["id"]})
    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["processed_count"] == 10
    assert run["reorder_count"] == reorder and run["blocked_count"] == blocked


def test_get_drafts_does_not_generate_or_invalidate(web, t, start):
    run = start()
    assert web.get(f"/api/v1/runs/{run}/drafts").json()["data"] == []
    before = t.generate_po_drafts(run)
    assert web.get(f"/api/v1/runs/{run}/drafts").json()["data"] == before
    assert web.get(f"/api/v1/runs/{run}/drafts").json()["data"] == before


def test_agent_explanation_reads_stored_evidence(t, start, data):
    data["supplier_sku"][3]["unit_price"] = None
    run = start(data)
    reply = t.agent_message(MessageRequest(message="Why is SKU-004 missing a price?",run_id=run))
    assert reply["action"] == "EXPLAIN"
    assert "BLOCKED" in reply["message"] and "Positive unit price required" in reply["message"]


@pytest.mark.parametrize("text,expected", [
    ("Its unit price is 4.50.", "4.50"),
    ("SKU-004 price: 4.5000", "4.5000"),
    ("SKU-004 单价是 4.50。", "4.50"),
    ("SKU-004 price is -4.50", None),
    ("SKU-004 price is 4.50001", None),
    ("The price for SKU-004 is missing", None),
])
def test_agent_only_prefills_explicit_price_and_never_saves(t,start,text,expected):
    run=start()
    before=t.get_sku_context(run,"SKU-004")
    reply=t.agent_message(MessageRequest(message=text,run_id=run,sku_id="SKU-004"))
    assert reply["unit_price"] == expected
    assert reply["action"] == ("PRICE" if expected else "NONE")
    assert t.get_sku_context(run,"SKU-004") == before


def test_agent_cannot_approve_or_export(t,start):
    run=start()
    for text in ("Approve all drafts", "Export the order", "批准所有订单"):
        assert t.agent_message(MessageRequest(message=text,run_id=run))["action"] == "NONE"


def test_unknown_demo_and_message_request_validation(web):
    assert web.get("/api/v1/demo/unknown").status_code == 404
    assert web.post("/api/v1/agent/message",json={"message":""}).status_code == 422


def test_deepseek_failure_is_explicit(monkeypatch):
    monkeypatch.setattr(messages,"settings",lambda:SimpleNamespace(
        deepseek_api_key="test-only", deepseek_key_file="missing.txt", deepseek_model="test-model"))
    def fail(*args,**kwargs):
        raise URLError("test provider unavailable")
    monkeypatch.setattr(messages,"urlopen",fail)
    with pytest.raises(BusinessError) as exc:
        messages._deepseek_reply(SimpleNamespace(), MessageRequest(
            message="Could you assist me with my day?", history=[]), "test-only")
    assert exc.value.code == "AGENT_UNAVAILABLE"


def test_deepseek_cannot_supply_commercial_values(monkeypatch,t,start):
    monkeypatch.setattr(messages,"settings",lambda:SimpleNamespace(
        deepseek_api_key="test-only", deepseek_key_file="missing.txt", deepseek_model="test-model"))
    payload={"choices":[{"message":{"role":"assistant","content":"I suggest a price of 9999."}}]}
    monkeypatch.setattr(messages,"urlopen",lambda *a,**k:io.BytesIO(json.dumps(payload).encode()))
    reply=t.agent_message(MessageRequest(message="Amend SKU-004 please",run_id=start(),history=[]))
    assert reply["action"] == "NONE" and reply["unit_price"] is None


def test_deepseek_react_uses_grounded_tool_and_hides_reasoning(monkeypatch,t,start):
    monkeypatch.setattr(messages,"settings",lambda:SimpleNamespace(
        deepseek_api_key="test-only", deepseek_key_file="missing.txt", deepseek_model="test-model"))
    responses = iter([
        {"choices":[{"message":{"role":"assistant","content":None,
            "reasoning_content":"private chain of thought",
            "tool_calls":[{"id":"call-1","type":"function","function":{
                "name":"get_decision_cockpit","arguments":"{}"}}]}}]},
        {"choices":[{"message":{"role":"assistant","content":
            "Supplier SUP-01 has the highest grounded recommended spend."}}]},
    ])
    requests = []
    def respond(request, **kwargs):
        requests.append(json.loads(request.data.decode()))
        return io.BytesIO(json.dumps(next(responses)).encode())
    monkeypatch.setattr(messages,"urlopen",respond)
    reply=t.agent_message(MessageRequest(
        message="Which supplier has the highest recommended spend?",run_id=start(),history=[]))
    assert reply["provider"] == "DeepSeek ReAct"
    assert reply["tools_used"] == ["get_decision_cockpit"]
    assert "private chain" not in json.dumps(reply)
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert requests[1]["messages"][-2]["reasoning_content"] == "private chain of thought"
    assert "spend_by_supplier" in requests[1]["messages"][-1]["content"]


def test_deepseek_has_only_read_only_procurement_tools():
    names = {item["function"]["name"] for item in messages.TOOL_DEFINITIONS}
    assert {"get_sku_evidence", "simulate_scenario", "get_procurement_rules"} <= names
    assert not names & {"approve_po", "reject_po", "export_po", "update_po_line", "resolve_exception"}


def test_chat_navigation_opens_requested_page_instead_of_new_run():
    navigation = {"action": "NONE"}
    request = MessageRequest(message="Open the data page", history=[])
    messages._tool_result(None, request, "open_workspace_page", {"page": "data"}, navigation)
    assert navigation["action"] == "NAVIGATE" and navigation["page"] == "data"
    navigation = {"action": "NONE"}
    request = MessageRequest(message="What should I review first?", history=[])
    messages._tool_result(None, request, "open_workspace_page", {"page": "drafts"}, navigation)
    assert navigation["action"] == "NONE"


def test_open_ended_policy_questions_reach_model(monkeypatch):
    monkeypatch.setattr(messages, "_provider_key", lambda: "test-only")
    seen = []
    def answer(tools, request, key):
        seen.append(request.message)
        return {"action": "NONE", "message": "Policy evidence"}
    monkeypatch.setattr(messages, "_deepseek_reply", answer)
    for question in ("How does approval work?", "变化原因是什么？", "Explain supplier concentration"):
        messages.reply(None, MessageRequest(message=question, history=[], run_id="selected-run"))
    assert len(seen) == 3


def test_decision_cockpit_uses_stored_results_and_previous_run(t, start):
    first = start()
    second = start()
    cockpit = t.procurement_cockpit(second)
    assert cockpit["metrics"]["total_skus"] == 10
    assert cockpit["metrics"]["reorder"] + cockpit["metrics"]["no_reorder"] + cockpit["metrics"]["blocked"] == 10
    assert cockpit["metrics"]["recommendation_value"] != "0"
    assert cockpit["comparison"]["previous_run_id"] == first


def test_what_if_simulation_is_read_only_and_deterministic(t, start):
    run = start()
    before = t.get_all_skus(run)
    result = t.simulate_procurement(run, SimulationRequest(
        horizon=30, demand_percent=150, safety_stock_percent=120, lead_time_delta_days=5))
    assert result["scenario"]["total_skus"] == result["baseline"]["total_skus"] == 10
    assert "Read-only" in result["disclaimer"]
    assert t.get_all_skus(run) == before


def test_agent_daily_brief_and_insights_are_grounded_in_current_run(t, start):
    run = start()
    brief = t.agent_message(MessageRequest(message="Give me today's daily brief", run_id=run))
    assert brief["action"] == "BRIEF"
    assert "10 SKUs reviewed" in brief["message"] and "Recommended value" in brief["message"]
    insight = t.agent_message(MessageRequest(message="What changed since the last review?", run_id=run))
    assert insight["action"] == "INSIGHTS"
    assert "deterministic and read-only" in insight["message"]


def test_cockpit_and_simulation_http_endpoints(web, start):
    run = start()
    assert web.get(f"/api/v1/runs/{run}/cockpit").status_code == 200
    response = web.post(f"/api/v1/runs/{run}/simulate", json={
        "horizon": 21, "demand_percent": 110, "safety_stock_percent": 100,
        "lead_time_delta_days": 2})
    assert response.status_code == 200
    assert response.json()["data"]["inputs"]["horizon"] == 21
