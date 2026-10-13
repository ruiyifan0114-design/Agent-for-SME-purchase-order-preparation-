from datetime import datetime, timezone
from decimal import Decimal


def resolve_approval_steps(context: dict, rules: list[dict], delegations: list[dict], at: datetime) -> dict:
    def parsed(value):
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result

    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    amount = Decimal(str(context["amount"]))
    matched = []
    for rule in rules:
        if amount < Decimal(str(rule.get("minimum_amount", 0))):
            continue
        maximum = rule.get("maximum_amount")
        if maximum is not None and amount >= Decimal(str(maximum)):
            continue
        if rule.get("cost_center") and rule["cost_center"] != context.get("cost_center"):
            continue
        if rule.get("supplier_id") and rule["supplier_id"] != context.get("supplier_id"):
            continue
        if rule.get("risk_level") and rule["risk_level"] != context.get("risk_level"):
            continue
        matched.append(rule)
    matched.sort(key=lambda item: (int(item.get("sequence", 0)), item.get("id", "")))
    steps = []
    for rule in matched:
        role = rule["required_role"]
        delegate = next((item for item in delegations
                         if item["delegator_role"] == role
                         and parsed(item["valid_from"]) <= at
                         and parsed(item["valid_to"]) >= at), None)
        steps.append({"rule_id": rule.get("id"), "required_role": role,
                      "acting_role": delegate["delegate_role"] if delegate else role,
                      "delegated": bool(delegate), "delegation_id": delegate.get("id") if delegate else None,
                      "delegator_user_id": delegate.get("delegator_user_id") if delegate else None,
                      "delegate_user_id": delegate.get("delegate_user_id") if delegate else None})
    return {"inputs": context, "applied_rule": "ORDERED_APPROVAL_MATRIX",
            "intermediate": {"matched_rule_ids": [rule.get("id") for rule in matched]},
            "result": {"steps": steps, "approval_required": bool(steps)},
            "data_source": "workspace_approval_matrix", "rule_version": context.get("rule_version", 1)}
