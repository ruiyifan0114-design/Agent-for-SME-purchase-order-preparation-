"""CSV/XLSX adapters and explicit normalization of unusable template cells."""
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError
from backend.domain.schemas import Dataset

TABLES = tuple(Dataset.model_fields)
ALIASES = {"supplier_master_template": "supplier_master", "sku_supplier_map_template": "supplier_sku",
           "sku_supplier_map": "supplier_sku", "inventory": "inventory_snapshot"}
INT_FIELDS = {"safety_stock", "target_stock", "moq", "pack_multiple", "lead_time_days", "on_hand", "quantity"}
DATE_FIELDS = {"updated_at", "snapshot_date", "arrival_date", "need_date"}
BOOL_FIELDS = {"active", "approved", "approved_for_sku"}
IGNORED = {"data_status", "commercial_data_status"}
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50_000


def header(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def table_name(name):
    key = header(name.rsplit(".", 1)[0] if "." in name else name)
    return ALIASES.get(key, key)


def read_files(files: list[tuple[str, bytes]]) -> dict:
    data = {}
    if sum(len(content) for _, content in files) > MAX_BYTES:
        raise ValueError("Upload exceeds 10 MiB")
    for filename, content in files:
        if filename.lower().endswith(".csv"):
            reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("Missing or duplicate CSV headers")
            rows = list(reader)
            if any(None in row for row in rows):
                raise ValueError("CSV has more cells than headers")
            sheets = {table_name(filename): rows}
        elif filename.lower().endswith(".xlsx"):
            try:
                with ZipFile(io.BytesIO(content)) as archive:
                    if sum(i.file_size for i in archive.infolist()) > 50 * MAX_BYTES:
                        raise ValueError("Expanded workbook exceeds limit")
                workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
                sheets = {}
                for sheet in workbook:
                    rows = iter(sheet.values)
                    columns = next(rows, ())
                    if not columns or any(c is None for c in columns) or len(set(columns)) != len(columns):
                        raise ValueError("Missing or duplicate XLSX headers")
                    records = []
                    for row in rows:
                        if any(v is not None for v in row):
                            records.append(dict(zip(columns, row)))
                        if len(records) > MAX_ROWS:
                            raise ValueError("Too many rows")
                    name = table_name(sheet.title)
                    if name in sheets:
                        raise ValueError("Duplicate worksheet table")
                    sheets[name] = records
                workbook.close()
            except (BadZipFile, KeyError, ParseError, InvalidFileException) as exc:
                raise ValueError("Invalid XLSX file") from exc
        else:
            raise ValueError("Use CSV or XLSX uploads")
        for name, rows in sheets.items():
            if name not in TABLES or name in data:
                raise ValueError(f"Unknown or duplicate table: {name}")
            if len(rows) > MAX_ROWS:
                raise ValueError("Too many rows")
            data[name] = rows
    return data


def normalize(raw: dict) -> tuple[Dataset, list[dict]]:
    issues, data = [], {}
    for table, rows in raw.items():
        if table not in TABLES or not isinstance(rows, list):
            raise ValueError(f"Invalid table: {table}")
        if len(rows) > MAX_ROWS:
            raise ValueError("Too many rows")
        cleaned = []
        for index, row in enumerate(rows, 2):
            if not isinstance(row, dict):
                raise ValueError("Each row must be an object")
            result = {}
            for original, value in row.items():
                key = header(original)
                key = {"sku": "sku_id", "default_supplier_id": "supplier_id", "lead_time_days": "lead_time_days"}.get(key, key)
                if table == "supplier_sku" and key == "approved":
                    key = "approved_for_sku"
                if key in IGNORED or (table == "supplier_sku" and key in {"description", "uom"}):
                    continue
                if key in result:
                    raise ValueError(f"Duplicate normalized field {key}")
                original_value = value
                if isinstance(value, str):
                    value = value.strip() or None
                try:
                    if value is not None and key in INT_FIELDS:
                        n = Decimal(str(value))
                        if not n.is_finite() or n != n.to_integral_value() or n < 0 or n > 100_000_000:
                            raise ValueError()
                        if key == "pack_multiple" and n == 0:
                            raise ValueError()
                        if key == "lead_time_days" and n > 3650:
                            raise ValueError()
                        value = int(n)
                    elif value is not None and key == "unit_price":
                        n = Decimal(str(value))
                        if not n.is_finite() or n <= 0 or n >= Decimal("100000000000000") or n.as_tuple().exponent < -4:
                            raise ValueError()
                        value = n
                    elif value is not None and key in DATE_FIELDS:
                        value = value.date() if isinstance(value, datetime) else date.fromisoformat(str(value))
                    elif value is not None and key in BOOL_FIELDS:
                        if str(value).lower() not in {"true", "false", "yes", "no", "1", "0"}:
                            raise ValueError()
                        value = str(value).lower() in {"true", "yes", "1"}
                    elif value is not None and key == "currency":
                        value = str(value).upper()
                        if not re.fullmatch("[A-Z]{3}", value) or value == "TBD":
                            raise ValueError()
                except (ValueError, InvalidOperation):
                    value = None
                    issues.append(dict(table=table, row=index, field=key, original=str(original_value),
                                       code="NORMALIZED_INVALID_VALUE", message="Unusable value normalized to null; never guessed"))
                result[key] = value
            cleaned.append(result)
        data[table] = cleaned
    # Require all tables (empty demand/PO lists explicitly mean no records).
    try:
        dataset = Dataset.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    skus = [s.sku_id for s in dataset.sku_master]
    suppliers = [s.supplier_id for s in dataset.supplier_master]
    if not skus or len(skus) != len(set(skus)) or len(suppliers) != len(set(suppliers)):
        raise ValueError("SKU/supplier master IDs must be unique; SKU master cannot be empty")
    for name in ("supplier_sku", "inventory_snapshot", "demand", "open_po"):
        if any(row.sku_id not in skus for row in getattr(dataset, name)):
            raise ValueError(f"Unknown SKU in {name}")
    return dataset, issues
