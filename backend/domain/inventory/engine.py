from decimal import Decimal, ROUND_CEILING
from statistics import NormalDist


def _ceil(value: float | Decimal) -> int:
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING))


def inventory_policy(inputs: dict, policy: dict) -> dict:
    """Evaluate simple target-stock or service-level/ROP/EOQ policy without an LLM."""
    on_hand = int(inputs["on_hand"])
    incoming = int(inputs.get("incoming", 0))
    demand = int(inputs.get("demand", 0))
    if min(on_hand, incoming, demand) < 0:
        raise ValueError("inventory and demand quantities must be non-negative")
    projected = on_hand + incoming - demand
    mode = policy.get("policy_type", "TARGET_STOCK")
    intermediate = {"projected_stock": projected}
    if mode == "TARGET_STOCK":
        safety, target = int(policy["safety_stock"]), int(policy["target_stock"])
        if safety < 0 or target < safety:
            raise ValueError("target stock must be at least non-negative safety stock")
        reorder = projected < safety
        quantity = max(0, target - projected) if reorder else 0
        intermediate.update(safety_stock=safety, target_stock=target)
        applied = "BELOW_SAFETY_TO_TARGET"
    elif mode == "ROP_EOQ":
        daily = Decimal(str(policy["average_daily_demand"]))
        lead = Decimal(str(policy["lead_time_days"]))
        stddev = Decimal(str(policy.get("daily_demand_stddev", 0)))
        seasonal = Decimal(str(policy.get("seasonal_factor", 1)))
        daily = Decimal(str(policy.get("forecast_daily_demand", daily))) * seasonal
        if any(not value.is_finite() or value < 0 for value in (daily, lead, stddev, seasonal)):
            raise ValueError("demand, lead time, deviation and seasonal factor must be finite and non-negative")
        service = float(policy.get("service_level", .95))
        if not 0.5 <= service < 1:
            raise ValueError("service level must be between 0.5 and 1")
        z = Decimal(str(NormalDist().inv_cdf(service)))
        safety = _ceil(z * stddev * lead.sqrt())
        reorder_point = _ceil(daily * lead) + safety
        annual = Decimal(str(policy["annual_demand"]))
        order_cost = Decimal(str(policy["order_cost"]))
        holding = Decimal(str(policy["annual_holding_cost_per_unit"]))
        if any(not value.is_finite() for value in (holding, order_cost, annual)) or holding <= 0 or min(order_cost, annual) < 0:
            raise ValueError("holding cost must be positive and order cost non-negative")
        eoq = _ceil((Decimal("2") * annual * order_cost / holding).sqrt())
        reorder = projected <= reorder_point
        quantity = max(eoq, reorder_point - projected + 1) if reorder else 0
        intermediate.update(z_score=str(z), safety_stock=safety, reorder_point=reorder_point, eoq=eoq,
                            abc_class=policy.get("abc_class"), xyz_class=policy.get("xyz_class"),
                            holding_cost=str(holding), stockout_cost=str(policy.get("stockout_cost", 0)),
                            seasonal_factor=str(seasonal), effective_daily_demand=str(daily))
        applied = "SERVICE_LEVEL_REORDER_POINT_EOQ"
    else:
        raise ValueError("unsupported inventory policy")
    return {"inputs": {**inputs, "policy": policy}, "applied_rule": applied, "intermediate": intermediate,
            "result": {"reorder": reorder, "order_quantity": quantity},
            "data_source": policy.get("data_source", "sku_inventory_policy"),
            "rule_version": policy.get("rule_version", 1)}
