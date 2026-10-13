from decimal import Decimal


def three_way_match(po: dict, receipts: list[dict], invoice: dict, tolerances: dict) -> dict:
    po_qty = int(po["quantity"])
    received = sum(int(row["quantity"]) for row in receipts if row.get("po_line_id") == po["line_id"])
    invoiced = int(invoice["quantity"])
    previously_invoiced = int(po.get("previously_invoiced_quantity", 0))
    po_price, invoice_price = Decimal(str(po["unit_price"])), Decimal(str(invoice["unit_price"]))
    qty_tolerance = int(tolerances.get("quantity", 0))
    price_tolerance = Decimal(str(tolerances.get("price_percent", 0))) / Decimal("100")
    if min(po_qty, invoiced, previously_invoiced, qty_tolerance) < 0 or not price_tolerance.is_finite() or price_tolerance < 0:
        raise ValueError("Matching quantities and tolerances must be nonnegative and finite")
    cumulative_invoiced = previously_invoiced + invoiced
    references_match = invoice.get("po_number") == po.get("po_number") and invoice.get("sku_id") == po.get("sku_id")
    quantity_match = cumulative_invoiced <= received + qty_tolerance and cumulative_invoiced <= po_qty + qty_tolerance
    variance = abs(invoice_price - po_price) / po_price if po_price else Decimal("Infinity")
    price_match = variance <= price_tolerance
    exceptions = []
    if not references_match:
        exceptions.append("REFERENCE_MISMATCH")
    if not quantity_match:
        exceptions.append("QUANTITY_MISMATCH")
    if not price_match:
        exceptions.append("PRICE_MISMATCH")
    return {"inputs": {"po": po, "receipts": receipts, "invoice": invoice, "tolerances": tolerances},
            "applied_rule": "PO_RECEIPT_INVOICE_THREE_WAY_MATCH",
            "intermediate": {"ordered_quantity": po_qty, "received_quantity": received,
                             "invoiced_quantity": invoiced, "previously_invoiced_quantity": previously_invoiced,
                             "cumulative_invoiced_quantity": cumulative_invoiced,
                             "price_variance_percent": str(variance * 100)},
            "result": {"status": "MATCHED" if not exceptions else "EXCEPTION", "exceptions": exceptions},
            "data_source": "po_goods_receipt_supplier_invoice", "rule_version": tolerances.get("rule_version", 1)}
