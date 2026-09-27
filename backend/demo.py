"""Synthetic fixtures derived from biz module's 10 item descriptions and SUP-A/B/C IDs."""
import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path
from backend.agent.procurement import ProcurementAgent
from backend.db.session import SessionLocal
from backend.domain.schemas import RunRequest
from backend.tools.procurement import ProcurementTools

ROOT = Path(__file__).resolve().parents[1]


def dataset(as_of: date, with_exceptions=True):
    with (ROOT / "biz module" / "sku_supplier_map_template.csv").open(encoding="utf-8-sig", newline="") as f:
        examples = list(csv.DictReader(f))
    data = {k: [] for k in ("sku_master", "supplier_master", "supplier_sku", "inventory_snapshot", "demand", "open_po")}
    for letter in "ABC":
        data["supplier_master"].append(dict(supplier_id=f"SUP-{letter}", supplier_name=f"Synthetic Supplier {letter}", approved=True, currency="XTS"))
    for i, row in enumerate(examples):
        sku = row["sku"]
        data["sku_master"].append(dict(sku_id=sku, description=row["description"], uom=row["uom"], active=True, safety_stock=20, target_stock=60))
        data["supplier_sku"].append(dict(sku_id=sku, supplier_id=f"SUP-{'ABC'[i % 3]}", approved_for_sku=True,
            unit_price=str(i + 1), currency="XTS", moq=50, pack_multiple=10, lead_time_days=2, updated_at=as_of.isoformat()))
        data["inventory_snapshot"].append(dict(sku_id=sku, on_hand=100 if i == 9 else 10, snapshot_date=as_of.isoformat()))
        data["demand"].append(dict(sku_id=sku, quantity=30, need_date=(as_of + timedelta(days=3)).isoformat()))
    if with_exceptions:
        data["supplier_sku"][3]["unit_price"] = "TEAM TO DEFINE"
        data["supplier_sku"][5]["approved_for_sku"] = False
        data["inventory_snapshot"] = [r for r in data["inventory_snapshot"] if r["sku_id"] != "SKU-005"]
        data["open_po"].append(dict(sku_id="SKU-007", po_number="SYNTHETIC-OPEN-001", quantity=100,
            arrival_date=(as_of + timedelta(days=8)).isoformat(), status="OPEN"))
    return data


def run_request(batch_id, as_of):
    return RunRequest(batch_id=batch_id, as_of=as_of, horizon=14, currency="XTS", warehouse="SYNTHETIC-WH-1",
                      inventory_max_age_days=1, commercial_max_age_days=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--write-files", type=Path)
    args = parser.parse_args()
    data = dataset(args.date, with_exceptions=not args.clean)
    if args.write_files:
        args.write_files.mkdir(parents=True, exist_ok=True)
        (args.write_files / "dataset.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        for table, rows in data.items():
            # Keep headers even for a deliberately empty table.
            from backend.domain.schemas import Dataset
            row_model = Dataset.model_fields[table].annotation.__args__[0]
            with (args.write_files / f"{table}.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(row_model.model_fields))
                writer.writeheader()
                writer.writerows(rows)
        print(f"Synthetic-only files written to {args.write_files}")
        return
    with SessionLocal() as db:
        tools = ProcurementTools(db)
        batch = tools.import_dataset(data, "synthetic-demo")
        report = ProcurementAgent(tools).daily_review(run_request(batch["id"], args.date))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
