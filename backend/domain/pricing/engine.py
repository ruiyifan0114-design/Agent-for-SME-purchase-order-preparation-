from datetime import date
from decimal import Decimal, ROUND_HALF_UP


MONEY = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def landed_cost(offer: dict, quantity: int, as_of: date, fx_rate: Decimal = Decimal("1")) -> dict:
    """Deterministic commercial price and landed-cost calculation."""
    if quantity <= 0 or not fx_rate.is_finite() or fx_rate <= 0:
        raise ValueError("quantity and exchange rate must be positive")
    valid_from = date.fromisoformat(offer["valid_from"]) if offer.get("valid_from") else None
    valid_to = date.fromisoformat(offer["valid_to"]) if offer.get("valid_to") else None
    if (valid_from and as_of < valid_from) or (valid_to and as_of > valid_to):
        raise ValueError("commercial agreement is not effective on the pricing date")
    source = "base_price"
    unit_price = Decimal(str(offer["unit_price"]))
    if offer.get("contract_price") is not None:
        unit_price, source = Decimal(str(offer["contract_price"])), "contract_price"
    else:
        eligible = [tier for tier in offer.get("tiers", []) if quantity >= int(tier["minimum_quantity"])]
        if eligible:
            tier = max(eligible, key=lambda item: int(item["minimum_quantity"]))
            unit_price, source = Decimal(str(tier["unit_price"])), "tier_price"
    if not unit_price.is_finite() or unit_price <= 0:
        raise ValueError("unit price must be finite and positive")
    for field in ("freight_fixed", "freight_per_unit", "additional_cost", "duty_rate", "tax_rate"):
        value = Decimal(str(offer.get(field, 0)))
        if not value.is_finite() or value < 0:
            raise ValueError(f"{field} must be finite and non-negative")
    goods = _money(unit_price * quantity)
    freight = _money(Decimal(str(offer.get("freight_fixed", 0))) +
                     Decimal(str(offer.get("freight_per_unit", 0))) * quantity)
    additional = _money(Decimal(str(offer.get("additional_cost", 0))))
    duty = _money(goods * Decimal(str(offer.get("duty_rate", 0))))
    taxable = goods + freight + additional + duty
    tax = _money(taxable * Decimal(str(offer.get("tax_rate", 0))))
    transaction_total = _money(taxable + tax)
    base_total = _money(transaction_total * fx_rate)
    return {
        "inputs": {"quantity": quantity, "pricing_date": as_of.isoformat(), "fx_rate": str(fx_rate), "offer": offer},
        "applied_rule": source,
        "intermediate": {"unit_price": str(unit_price), "goods": str(goods), "freight": str(freight),
                         "additional_cost": str(additional), "duty": str(duty), "tax": str(tax)},
        "result": {"transaction_total": str(transaction_total), "base_currency_total": str(base_total)},
        "data_source": offer.get("data_source", "commercial_agreement"),
        "rule_version": offer.get("rule_version", 1),
    }
