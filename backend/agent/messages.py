"""Natural language proposes actions; stored tools remain the only source of results.

DeepSeek receives the user's command only, never the imported data or credentials.
It may classify an intent, but cannot approve, resolve, or calculate commercial values.
"""
import json
import re
from pathlib import Path
from typing import Literal
from urllib.error import URLError
from urllib.request import Request, urlopen
from pydantic import BaseModel, Field, ValidationError
from backend.config import settings
from backend.tools.runtime import BusinessError


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    run_id: str | None = None
    sku_id: str | None = None


class Intent(BaseModel):
    action: Literal["NONE", "RUN", "DRAFTS", "PRICE", "EXPLAIN", "BRIEF", "INSIGHTS"] = "NONE"


def classify(message):
    text = message.lower()
    if any(w in text for w in ("approve", "reject", "批准", "审批", "拒绝", "export", "导出")):
        return "NONE", "workflow"
    if any(w in text for w in ("daily brief", "briefing", "today", "summary", "今日", "今天", "简报", "总结")):
        return "BRIEF", "workflow"
    if any(w in text for w in ("compare", "change", "trend", "cockpit", "insight", "对比", "变化", "趋势", "分析")):
        return "INSIGHTS", "workflow"
    if any(w in text for w in ("why", "explain", "为什么", "原因", "blocked", "阻塞")):
        return "EXPLAIN", "workflow"
    if re.search(r"(?:price|价格|单价).*?\d|\d.*?(?:price|价格|单价)", text):
        return "PRICE", "workflow"
    if any(w in text for w in ("draft", "草稿", "采购单")):
        return "DRAFTS", "workflow"
    if any(w in text for w in ("run", "start", "运行", "检查", "开始")):
        return "RUN", "workflow"
    cfg = settings()
    key = cfg.deepseek_api_key
    if not key:
        path = Path(cfg.deepseek_key_file)
        if path.is_file():
            key = path.read_text(encoding="utf-8").strip()
    if not key:
        return "NONE", "workflow"
    payload = {"model": cfg.deepseek_model, "stream": False, "max_tokens": 100,
        "messages": [
            {"role": "system", "content": 'Classify a procurement UI command. Return only JSON {"action":"RUN|DRAFTS|PRICE|EXPLAIN|BRIEF|INSIGHTS|NONE"}. BRIEF summarizes current stored work; INSIGHTS opens deterministic analytics/comparison. Never approve/reject/export or calculate values. Such commands are NONE. Do not return any other fields.'},
            {"role": "user", "content": message}], "response_format": {"type": "json_object"}}
    req = Request("https://api.deepseek.com/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as response:
            body = json.load(response)
        return Intent.model_validate_json(body["choices"][0]["message"]["content"]).action, "DeepSeek"
    except (URLError, TimeoutError, ValueError, KeyError, IndexError, ValidationError) as exc:
        raise BusinessError("DeepSeek could not interpret the command. No action was performed; use the dashboard controls.", "AGENT_UNAVAILABLE", 502) from exc


def reply(tools, request: MessageRequest):
    action, provider = classify(request.message)
    explicit_sku = re.search(r"SKU-\d+", request.message, re.I)
    sku = explicit_sku.group(0).upper() if explicit_sku else request.sku_id
    result = None
    if sku and request.run_id:
        result = tools.get_sku_context(request.run_id, sku)
    price_match = re.search(
        r"(?:unit\s+price|price|价格|单价)\s*(?:(?:is|为|是)\s*|[:=]\s*)?(\d+(?:\.\d{1,4})?)(?!\d|\.\d)",
        request.message, re.I)
    price = price_match.group(1) if price_match else None
    if action == "EXPLAIN" and result:
        exceptions = [e for e in tools.list_exceptions(request.run_id) if e["result_id"] == result["id"] and e["status"] == "OPEN"]
        message = f"{sku}: {result['status']}. {result['decision_reason']}"
        if exceptions:
            message += " " + " ".join(e["message"] for e in exceptions)
    elif action == "EXPLAIN":
        action, message = "NONE", "Select a run and tell me the SKU, for example: Why is SKU-004 blocked?"
    elif action == "PRICE" and result and price:
        message = f"I can open the price correction for {sku} with your value {price}. Review the form and save it to rerun the SKU. Nothing has been changed yet."
    elif action == "PRICE":
        action, message = "NONE", "Specify a SKU and an explicit unit price, for example: SKU-004 unit price is 4.50."
    elif action == "RUN":
        message = "Open the daily check setup, confirm the input batch and policy, then start the check."
    elif action == "DRAFTS":
        message = "Opening supplier-grouped PO drafts from the current run. Approval remains an explicit human action."
    elif action == "BRIEF" and request.run_id:
        cockpit = tools.procurement_cockpit(request.run_id)
        metrics = cockpit["metrics"]
        changes = cockpit["comparison"]["changes"]
        message = (f"Daily brief for {cockpit['as_of']}: {metrics['total_skus']} SKUs reviewed; "
            f"{metrics['reorder']} ready to reorder, {metrics['no_reorder']} covered, and "
            f"{metrics['blocked']} blocked. Recommended value is {cockpit['currency']} "
            f"{metrics['recommendation_value']} across {metrics['supplier_count']} suppliers. "
            f"There are {metrics['warning_count']} open timing warnings and {len(changes)} material changes versus the previous review. "
            "Open Decision cockpit for the evidence and scenario controls.")
    elif action == "BRIEF":
        action, message = "NONE", "Select a procurement run first, then ask for today's daily brief."
    elif action == "INSIGHTS" and request.run_id:
        cockpit = tools.procurement_cockpit(request.run_id)
        count = len(cockpit["comparison"]["changes"])
        message = (f"Opening Decision cockpit. The current review has {count} material SKU changes versus the previous run. "
                   "The comparison and what-if simulation are deterministic and read-only.")
    elif action == "INSIGHTS":
        action, message = "NONE", "Select a procurement run before opening analytics or comparing changes."
    else:
        message = "I can prepare a daily brief, compare reviews, explain a SKU, open a price correction, start a check, or show drafts. Use the PO review controls to approve, reject or export."
    return {"action": action, "message": message, "sku_id": sku, "unit_price": price, "provider": provider}
