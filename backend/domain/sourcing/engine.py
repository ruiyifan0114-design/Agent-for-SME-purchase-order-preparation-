from datetime import date
from decimal import Decimal

from backend.domain.pricing.engine import landed_cost


def performance_score(performance: dict) -> Decimal:
    def metric(name, default):
        value = performance.get(name)
        result = Decimal(str(default if value is None else value))
        if not result.is_finite() or result < 0 or (name != "lead_time_variance_days" and result > 1):
            raise ValueError(f"invalid supplier performance metric: {name}")
        return result
    on_time = metric("on_time_rate", ".5")
    variance = min(metric("lead_time_variance_days", "15") / Decimal("30"), Decimal("1"))
    rejection = metric("rejection_rate", ".5")
    historical = metric("historical_score", ".5")
    return max(Decimal("0"), min(Decimal("1"), on_time * Decimal("0.45") +
               (Decimal("1") - variance) * Decimal("0.20") +
               (Decimal("1") - rejection) * Decimal("0.20") + historical * Decimal("0.15")))


def _valid_quantity(offer: dict, quantity: int) -> bool:
    moq, pack = int(offer.get("moq", 0)), int(offer.get("pack_multiple", 1))
    capacity = offer.get("max_quantity")
    return quantity >= max(1, moq) and quantity % pack == 0 and (capacity is None or quantity <= int(capacity))


def _candidate(allocations: list[tuple[dict, int]], as_of: date, weights: dict) -> dict:
    lines, total, weighted_lead, weighted_perf, quantity = [], Decimal("0"), Decimal("0"), Decimal("0"), 0
    for offer, qty in allocations:
        cost = landed_cost(offer, qty, as_of, Decimal(str(offer.get("fx_rate", 1))))
        line_total = Decimal(cost["result"]["base_currency_total"])
        score = performance_score(offer.get("performance", {}))
        total += line_total
        quantity += qty
        weighted_lead += Decimal(str(offer.get("lead_time_days", 0))) * qty
        weighted_perf += score * qty
        lines.append({"supplier_id": offer["supplier_id"], "quantity": qty,
                      "missing_performance_assumption": "neutral score of 0.5 per missing metric",
                      "performance_score": str(score.quantize(Decimal('0.0001'))), "cost": cost})
    lead = weighted_lead / quantity
    perf = weighted_perf / quantity
    penalty = (lead * Decimal(str(weights.get("lead_time", 0))) +
               (Decimal("1") - perf) * Decimal(str(weights.get("performance", 0))))
    return {"allocations": lines, "landed_cost": str(total), "weighted_lead_days": str(lead),
            "weighted_performance": str(perf), "selection_score": str(total + penalty)}


def rank_suppliers(required_quantity: int, offers: list[dict], as_of: date,
                   weights: dict | None = None, allow_split: bool = True) -> dict:
    if required_quantity <= 0:
        raise ValueError("required quantity must be positive")
    weights = weights or {"lead_time": "0", "performance": "0"}
    approved = [offer for offer in offers if offer.get("approved", False)]
    if len({offer["supplier_id"] for offer in approved}) != len(approved):
        raise ValueError("duplicate supplier offers must be resolved before sourcing")
    for offer in approved:
        if int(offer.get("pack_multiple", 1)) <= 0 or int(offer.get("moq", 0)) < 0:
            raise ValueError("pack size must be positive and MOQ non-negative")
    candidates = []
    for offer in approved:
        pack = int(offer.get("pack_multiple", 1))
        qty = max(required_quantity, int(offer.get("moq", 0)))
        qty = ((qty + pack - 1) // pack) * pack
        if _valid_quantity(offer, qty):
            candidates.append(_candidate([(offer, qty)], as_of, weights))
    if allow_split:
        for index, first in enumerate(approved):
            for second in approved[index + 1:]:
                first_pack, second_pack = int(first.get("pack_multiple", 1)), int(second.get("pack_multiple", 1))
                minimum = max(1, int(first.get("moq", 0)))
                minimum = ((minimum + first_pack - 1) // first_pack) * first_pack
                attempts = 0
                for first_qty in range(minimum, required_quantity + first_pack, first_pack):
                    second_qty = required_quantity - first_qty
                    if second_qty <= 0:
                        continue
                    second_qty = max(second_qty, int(second.get("moq", 0)), 1)
                    second_qty = ((second_qty + second_pack - 1) // second_pack) * second_pack
                    attempts += 1
                    if attempts > 10_000:
                        raise ValueError("split search exceeds 10000 candidates per pair; narrow quantity or supplier capacity")
                    if _valid_quantity(first, first_qty) and _valid_quantity(second, second_qty):
                        candidates.append(_candidate([(first, first_qty), (second, second_qty)], as_of, weights))
    if not candidates:
        raise ValueError("no approved supplier allocation satisfies MOQ, pack and capacity")
    ranked = sorted(candidates, key=lambda item: (Decimal(item["selection_score"]),
                                                    len(item["allocations"]),
                                                    tuple(line["supplier_id"] for line in item["allocations"])))
    return {"inputs": {"required_quantity": required_quantity, "approved_supplier_count": len(approved),
                       "as_of": as_of.isoformat(), "offers": offers, "weights": weights,
                       "allow_split": allow_split},
            "applied_rule": "MIN_LANDED_COST_PLUS_CONFIGURED_RISK_PENALTY",
            "intermediate": {"candidate_count": len(ranked), "ranked_candidates": ranked[:20]},
            "result": ranked[0], "data_source": "approved_supplier_offers", "rule_version": 1}


def recommend_sources(*args, **kwargs):
    return rank_suppliers(*args, **kwargs)
