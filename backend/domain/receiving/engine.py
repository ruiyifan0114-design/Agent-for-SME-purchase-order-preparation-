ALLOWED = {
    "DRAFT": {"SENT", "CANCELLED"},
    "SENT": {"PARTIALLY_RECEIVED", "RECEIVED", "DELAYED", "CANCELLED"},
    "DELAYED": {"PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"},
    "PARTIALLY_RECEIVED": {"PARTIALLY_RECEIVED", "RECEIVED", "DELAYED", "CANCELLED", "RETURNED"},
    "RECEIVED": {"RETURNED"},
    "RETURNED": set(), "CANCELLED": set(),
}


def transition_po(current: str, target: str) -> str:
    if target not in ALLOWED.get(current, set()):
        raise ValueError(f"invalid PO lifecycle transition {current} -> {target}")
    return target


def apply_receipt(ordered: int, received_before: int, receipt_quantity: int,
                  returned_before: int = 0, return_quantity: int = 0) -> dict:
    if min(ordered, received_before, receipt_quantity, returned_before, return_quantity) < 0:
        raise ValueError("quantities cannot be negative")
    received = received_before + receipt_quantity
    returned = returned_before + return_quantity
    if returned_before > received_before or returned > received or received - returned > ordered:
        raise ValueError("receipt/return exceeds valid ordered or received quantity")
    net_received = received - returned
    open_quantity = ordered - net_received
    status = "RECEIVED" if open_quantity == 0 else "PARTIALLY_RECEIVED"
    if return_quantity:
        status = "RETURNED" if open_quantity == ordered else "PARTIALLY_RECEIVED"
    return {"inputs": {"ordered": ordered, "received_before": received_before,
                       "receipt_quantity": receipt_quantity, "returned_before": returned_before,
                       "return_quantity": return_quantity},
            "applied_rule": "ORDERED_EQUALS_NET_RECEIVED_CLOSES_LINE",
            "intermediate": {"received_total": received, "returned_total": returned,
                             "net_received": net_received},
            "result": {"open_quantity": open_quantity, "status": status},
            "data_source": "goods_receipt", "rule_version": 1}
