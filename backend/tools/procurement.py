import csv
import hashlib
import io
import json
from copy import deepcopy
from collections import Counter
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from backend.domain.engine import amount, evaluate
from backend.domain.intake import normalize, read_files
from backend.domain.schemas import LineEdit, Resolution, Review, RunRequest, SimulationRequest
from backend.models.entities import (ApprovalEvent, Demand, ExceptionRecord, ImportBatch, Inventory,
    OpenPO, PODraft, POLine, ProcurementRun, SKU, SKUCheckResult, Supplier, SupplierSKU, ToolExecutionLog, now)
from backend.tools.runtime import BusinessError, audited, serial

TABLE_MODELS = {"sku_master": SKU, "supplier_master": Supplier, "supplier_sku": SupplierSKU,
                "inventory_snapshot": Inventory, "demand": Demand, "open_po": OpenPO}


class ProcurementTools:
    def __init__(self, db, actor="service", human=False):
        self.db, self.actor, self.human = db, actor, human

    def _get(self, model, identifier, lock=False):
        query = select(model).where(model.id == identifier)
        if lock:
            query = query.with_for_update()
        obj = self.db.scalar(query.execution_options(populate_existing=True))
        if obj is None:
            raise BusinessError("Resource not found", "NOT_FOUND", 404)
        return obj

    def _rows(self, model, **filters):
        return list(self.db.scalars(select(model).filter_by(**filters).order_by(model.id)))

    def _human(self):
        if not self.human or not self.actor.strip():
            raise BusinessError("Explicit authenticated human action required", "HUMAN_REQUIRED", 403)

    def _import(self, raw, filename):
        try:
            data, issues = normalize(raw)
        except ValueError as exc:
            batch = ImportBatch(filename=filename, status="REJECTED", synthetic=True,
                raw_data=serial(raw), source_hash=hashlib.sha256(json.dumps(serial(raw), sort_keys=True).encode()).hexdigest(),
                issues=[{"code": "INVALID_DATASET", "message": str(exc)}])
            self.db.add(batch)
            self.db.flush()
            return batch
        batch = ImportBatch(filename=filename, status="VALIDATED_WITH_ISSUES" if issues else "VALIDATED",
            synthetic=True, raw_data=serial(raw), issues=issues,
            source_hash=hashlib.sha256(json.dumps(serial(raw), sort_keys=True).encode()).hexdigest())
        self.db.add(batch)
        self.db.flush()
        for table, model in TABLE_MODELS.items():
            for row in getattr(data, table):
                self.db.add(model(batch_id=batch.id, **row.model_dump()))
            self.db.flush()
        return batch

    @audited
    def import_dataset(self, raw: dict, filename="dataset.json"):
        return self._import(raw, filename)

    @audited
    def import_files(self, files):
        try:
            raw = read_files(files)
        except (ValueError, UnicodeError) as exc:
            raise BusinessError(str(exc), "INVALID_UPLOAD", 422) from exc
        return self._import(raw, ", ".join(name for name, _ in files))

    @audited
    def validate_import(self, batch_id):
        batch = self._get(ImportBatch, batch_id)
        return {"id": batch.id, "status": batch.status, "issues": batch.issues}

    def _context(self, batch_id, sku):
        def clean(row):
            return {k: v for k, v in serial(row).items() if k not in {"id", "batch_id"}}
        return dict(sku=clean(sku), suppliers=[clean(s) for s in self._rows(Supplier, batch_id=batch_id)],
            commercial=[clean(s) for s in self._rows(SupplierSKU, batch_id=batch_id, sku_id=sku.sku_id)],
            inventory=[clean(s) for s in self._rows(Inventory, batch_id=batch_id, sku_id=sku.sku_id)],
            demand=[clean(s) for s in self._rows(Demand, batch_id=batch_id, sku_id=sku.sku_id)],
            open_po=[clean(s) for s in self._rows(OpenPO, batch_id=batch_id, sku_id=sku.sku_id)])

    @audited
    def create_procurement_run(self, request: RunRequest):
        batch = self._get(ImportBatch, request.batch_id)
        if not batch.status.startswith("VALIDATED"):
            raise BusinessError("Cannot run a rejected import")
        skus = self._rows(SKU, batch_id=batch.id, active=True)
        if not skus:
            raise BusinessError("Import contains no active SKU")
        run = ProcurementRun(**request.model_dump(), expected_sku_count=len(skus))
        self.db.add(run)
        self.db.flush()
        for sku in skus:
            self.db.add(SKUCheckResult(run_id=run.id, sku_id=sku.sku_id, context=self._context(batch.id, sku),
                                     decision_reason="Pending deterministic evaluation"))
        return run

    def _policy(self, run):
        return RunRequest(**{k: getattr(run, k) for k in RunRequest.model_fields})

    def _summary(self, run):
        results = self._rows(SKUCheckResult, run_id=run.id)
        evaluated = [r for r in results if r.revision > 0]
        counts = Counter(r.status for r in evaluated)
        run.processed_count = len(evaluated)
        run.reorder_count, run.no_reorder_count, run.blocked_count = (counts[s] for s in ("REORDER", "NO_REORDER", "BLOCKED"))
        if run.processed_count == run.expected_sku_count:
            run.status = "NEEDS_ATTENTION" if run.blocked_count else "COMPLETED"
        else:
            run.status = "RUNNING"
        self.db.flush()
        return run

    def _event(self, draft, action, comment):
        self.db.flush()
        self.db.add(ApprovalEvent(draft_id=draft.id, action=action, actor=self.actor,
            version=draft.version, comment=comment, snapshot=self._draft(draft)))

    def _invalidate(self, draft, reason):
        draft.status = "NEEDS_REVIEW"
        draft.reviewer, draft.approved_at = None, None
        draft.version += 1
        self._event(draft, "INVALIDATED", reason)

    def _evaluate(self, run, result):
        previous = serial(result)
        answer = evaluate(result.context, self._policy(run))
        for exc in self._rows(ExceptionRecord, result_id=result.id, status="OPEN"):
            exc.status = "SUPERSEDED"
        for key, value in answer.items():
            if key != "exceptions":
                setattr(result, key, value)
        result.revision += 1
        for exc in answer["exceptions"]:
            self.db.add(ExceptionRecord(run_id=run.id, result_id=result.id, **exc))
        for line in self._rows(POLine, result_id=result.id):
            draft = self._get(PODraft, line.draft_id)
            self.db.delete(line)
            self.db.flush()
            draft.total = sum((r.amount for r in self._rows(POLine, draft_id=draft.id)), Decimal(0))
            self._invalidate(draft, "Source decision rerun; regenerate PO drafts before review")
        self.db.flush()
        self.db.add(ToolExecutionLog(tool_name="evaluate_sku", actor=self.actor, status="SUCCESS",
            input={"previous": previous}, output=serial(result)))
        return result

    @audited
    def run_full_check(self, run_id):
        run = self._get(ProcurementRun, run_id, lock=True)
        for result in self._rows(SKUCheckResult, run_id=run_id):
            if result.revision == 0:
                self._evaluate(run, result)
        return self._summary(run)

    @audited
    def rerun_sku(self, run_id, sku_id):
        run = self._get(ProcurementRun, run_id, lock=True)
        results = self._rows(SKUCheckResult, run_id=run_id, sku_id=sku_id)
        if not results:
            raise BusinessError("SKU not in run", "NOT_FOUND", 404)
        self._evaluate(run, results[0])
        self._summary(run)
        return results[0]

    @audited
    def get_all_skus(self, run_id):
        self._get(ProcurementRun, run_id)
        return self._rows(SKUCheckResult, run_id=run_id)

    @audited
    def get_sku_context(self, run_id, sku_id):
        rows = self._rows(SKUCheckResult, run_id=run_id, sku_id=sku_id)
        if not rows:
            raise BusinessError("SKU not in run", "NOT_FOUND", 404)
        return rows[0]

    @audited
    def get_run_summary(self, run_id):
        return self._get(ProcurementRun, run_id)

    @audited
    def list_exceptions(self, run_id):
        self._get(ProcurementRun, run_id)
        return self._rows(ExceptionRecord, run_id=run_id)

    @audited
    def resolve_exception(self, exception_id, request: Resolution):
        self._human()
        exc = self._get(ExceptionRecord, exception_id)
        run = self._get(ProcurementRun, exc.run_id, lock=True)
        exc = self._get(ExceptionRecord, exception_id)
        result = self._get(SKUCheckResult, exc.result_id)
        if exc.status != "OPEN" or result.revision != request.expected_revision:
            raise BusinessError("Exception/revision changed; refresh before correcting", "VERSION_CONFLICT")
        if request.context.sku.sku_id != result.sku_id or not request.context.sku.active:
            raise BusinessError("Cannot change SKU identity or deactivate an affected SKU")
        context = request.context.model_dump(mode="json")
        answer = evaluate(context, self._policy(run))
        if any(e["code"] == exc.code and e["required_field"] == exc.required_field for e in answer["exceptions"]):
            raise BusinessError("Correction does not resolve the selected exception", "UNRESOLVED_EXCEPTION")
        before = result.context
        result.context = context
        exc.status = "RESOLVED"
        exc.resolved_value = {"before": before, "after": context, "reason": request.reason,
                              "actor": self.actor, "resolved_at": now().isoformat()}
        self._evaluate(run, result)
        self._summary(run)
        return result

    @audited
    def update_sku_context(self, run_id, sku_id, request: Resolution):
        """Human correction of a default supplier or source evidence, never automatic optimization."""
        self._human()
        run = self._get(ProcurementRun, run_id, lock=True)
        rows = self._rows(SKUCheckResult, run_id=run_id, sku_id=sku_id)
        if not rows:
            raise BusinessError("SKU not in run", "NOT_FOUND", 404)
        result = rows[0]
        if request.expected_revision != result.revision:
            raise BusinessError("SKU decision changed; refresh before correcting", "VERSION_CONFLICT")
        if request.context.sku.sku_id != sku_id or not request.context.sku.active:
            raise BusinessError("Cannot change SKU identity or deactivate an affected SKU")
        before = result.context
        result.context = request.context.model_dump(mode="json")
        self._evaluate(run, result)
        self._summary(run)
        return {"result": serial(result), "before": before, "reason": request.reason}

    def _draft(self, draft):
        obj = serial(draft)
        obj["po_number"] = f"PO-{draft.id}"
        obj["tax_treatment"] = "PRE_TAX"
        obj["synthetic"] = True
        obj["lines"] = serial(self._rows(POLine, draft_id=draft.id))
        return obj

    @audited
    def generate_po_drafts(self, run_id):
        run = self._get(ProcurementRun, run_id, lock=True)
        if run.processed_count != run.expected_sku_count:
            raise BusinessError("Complete SKU scan before generating drafts")
        for result in self._rows(SKUCheckResult, run_id=run_id, status="REORDER"):
            if self._rows(POLine, result_id=result.id):
                continue
            evidence = result.evidence
            supplier_id = evidence["supplier_id"]
            drafts = self._rows(PODraft, run_id=run_id, supplier_id=supplier_id)
            if drafts:
                draft = drafts[0]
                self._invalidate(draft, "Added newly evaluated source line")
            else:
                supplier = next(s for s in result.context["suppliers"] if s["supplier_id"] == supplier_id)
                draft = PODraft(run_id=run_id, supplier_id=supplier_id, supplier_name=supplier["supplier_name"],
                    currency=run.currency, warehouse=run.warehouse, order_date=run.as_of)
                self.db.add(draft)
                self.db.flush()
            qty, price = result.final_order_qty, Decimal(evidence["unit_price"])
            self.db.add(POLine(draft_id=draft.id, result_id=result.id, result_revision=result.revision,
                sku_id=result.sku_id, description=result.context["sku"]["description"], uom=result.context["sku"]["uom"],
                quantity=qty, unit_price=price, amount=amount(qty, price),
                need_date=date.fromisoformat(evidence["need_date"]),
                expected_delivery_date=date.fromisoformat(evidence["expected_delivery_date"])))
            self.db.flush()
            draft.total = sum((r.amount for r in self._rows(POLine, draft_id=draft.id)), Decimal(0))
        return [self._draft(d) for d in self._rows(PODraft, run_id=run_id)]

    @audited
    def get_po_draft(self, draft_id):
        return self._draft(self._get(PODraft, draft_id))

    @audited
    def list_po_drafts(self, run_id):
        self._get(ProcurementRun, run_id)
        return [self._draft(d) for d in self._rows(PODraft, run_id=run_id)]

    def _decision_metrics(self, answers):
        counts = Counter(answer["status"] for answer in answers)
        value = Decimal(0)
        suppliers = Counter()
        warnings = 0
        for answer in answers:
            warnings += sum(e["severity"] == "WARNING" for e in answer.get("exceptions", []))
            if answer["status"] == "REORDER":
                evidence = answer.get("evidence", {})
                price = Decimal(str(evidence.get("unit_price", 0)))
                value += amount(answer["final_order_qty"], price)
                suppliers[evidence.get("supplier_id", "UNMAPPED")] += amount(answer["final_order_qty"], price)
        total = len(answers)
        return {
            "total_skus": total,
            "reorder": counts["REORDER"],
            "no_reorder": counts["NO_REORDER"],
            "blocked": counts["BLOCKED"],
            "decision_completion": round((counts["REORDER"] + counts["NO_REORDER"]) / total * 100) if total else 0,
            "recommendation_value": str(value),
            "supplier_count": len(suppliers),
            "warning_count": warnings,
            "spend_by_supplier": [{"supplier_id": key, "value": str(val)} for key, val in suppliers.most_common()],
        }

    @audited
    def procurement_cockpit(self, run_id):
        run = self._get(ProcurementRun, run_id)
        results = self._rows(SKUCheckResult, run_id=run_id)
        answers = [serial(result) for result in results if result.revision > 0]
        current = self._decision_metrics(answers)
        open_exceptions = self._rows(ExceptionRecord, run_id=run_id, status="OPEN")
        current["warning_count"] = sum(exc.severity == "WARNING" for exc in open_exceptions)
        drafts = self._rows(PODraft, run_id=run_id)
        current["approved_value"] = str(sum((d.total for d in drafts if d.status == "APPROVED"), Decimal(0)))
        current["approval_progress"] = round(sum(d.status == "APPROVED" for d in drafts) / len(drafts) * 100) if drafts else 0
        previous = self.db.scalar(select(ProcurementRun).where(
            ProcurementRun.id != run.id, ProcurementRun.created_at < run.created_at
        ).order_by(ProcurementRun.created_at.desc()).limit(1))
        comparison = {"previous_run_id": None, "changes": [], "summary": {}}
        if previous:
            old = {r.sku_id: r for r in self._rows(SKUCheckResult, run_id=previous.id) if r.revision > 0}
            changes = []
            for result in results:
                before = old.get(result.sku_id)
                if before and (before.status != result.status or before.final_order_qty != result.final_order_qty):
                    changes.append({"sku_id": result.sku_id, "before_status": before.status,
                        "after_status": result.status, "before_qty": before.final_order_qty,
                        "after_qty": result.final_order_qty, "reason": result.decision_reason})
            comparison = {"previous_run_id": previous.id, "changes": changes,
                "summary": {"status_changes": sum(c["before_status"] != c["after_status"] for c in changes),
                            "quantity_changes": sum(c["before_qty"] != c["after_qty"] for c in changes)}}
        return {"run_id": run.id, "as_of": run.as_of, "currency": run.currency,
                "metrics": current, "comparison": comparison}

    @audited
    def simulate_procurement(self, run_id, request: SimulationRequest):
        run = self._get(ProcurementRun, run_id)
        results = self._rows(SKUCheckResult, run_id=run_id)
        policy_data = self._policy(run).model_dump()
        if request.horizon is not None:
            policy_data["horizon"] = request.horizon
        policy = RunRequest(**policy_data)
        simulated = []
        changes = []
        for result in results:
            context = deepcopy(result.context)
            sku = context["sku"]
            if sku.get("safety_stock") is not None:
                sku["safety_stock"] = round(sku["safety_stock"] * request.safety_stock_percent / 100)
            if sku.get("target_stock") is not None and sku.get("safety_stock") is not None:
                sku["target_stock"] = max(sku["safety_stock"], round(sku["target_stock"] * request.safety_stock_percent / 100))
            for demand in context["demand"]:
                if demand.get("quantity") is not None:
                    demand["quantity"] = round(demand["quantity"] * request.demand_percent / 100)
            for commercial in context["commercial"]:
                if commercial.get("lead_time_days") is not None:
                    commercial["lead_time_days"] = max(0, commercial["lead_time_days"] + request.lead_time_delta_days)
            answer = evaluate(context, policy)
            simulated.append(answer)
            if result.revision > 0 and (result.status != answer["status"] or result.final_order_qty != answer["final_order_qty"]):
                changes.append({"sku_id": result.sku_id, "before_status": result.status,
                    "after_status": answer["status"], "before_qty": result.final_order_qty,
                    "after_qty": answer["final_order_qty"], "reason": answer["decision_reason"]})
        baseline = self._decision_metrics([serial(r) for r in results if r.revision > 0])
        baseline["warning_count"] = sum(
            exc.severity == "WARNING" for exc in self._rows(ExceptionRecord, run_id=run_id, status="OPEN"))
        return {"run_id": run.id, "inputs": request.model_dump(), "baseline": baseline,
                "scenario": self._decision_metrics(simulated), "changes": changes,
                "disclaimer": "Read-only deterministic scenario. No run, source data, draft or approval was changed."}

    @audited
    def agent_message(self, request):
        from backend.agent.messages import reply
        return reply(self, request)

    def _locked_draft(self, draft_id):
        draft = self._get(PODraft, draft_id)
        self._get(ProcurementRun, draft.run_id, lock=True)
        return self._get(PODraft, draft_id, lock=True)

    def _version(self, draft, version):
        if draft.version != version:
            raise BusinessError("Draft changed; refresh before acting", "VERSION_CONFLICT")

    @audited
    def update_po_line(self, draft_id, line_id, request: LineEdit):
        self._human()
        draft = self._locked_draft(draft_id)
        self._version(draft, request.expected_version)
        line = self._get(POLine, line_id)
        if line.draft_id != draft_id:
            raise BusinessError("Line is not in this draft", "NOT_FOUND", 404)
        result = self._get(SKUCheckResult, line.result_id)
        qty = request.quantity if request.quantity is not None else line.quantity
        price = request.unit_price if request.unit_price is not None else line.unit_price
        if qty < result.evidence["moq"] or qty % result.evidence["pack_multiple"]:
            raise BusinessError("Edited quantity violates MOQ or pack multiple")
        line.quantity, line.unit_price, line.amount = qty, price, amount(qty, price)
        self.db.flush()
        draft.total = sum((r.amount for r in self._rows(POLine, draft_id=draft_id)), Decimal(0))
        self._invalidate(draft, request.reason)
        return self._draft(draft)

    def _approval_gate(self, draft):
        run = self._get(ProcurementRun, draft.run_id)
        lines = self._rows(POLine, draft_id=draft.id)
        if not lines:
            raise BusinessError("Cannot approve/export an empty PO")
        for line in lines:
            result = self._get(SKUCheckResult, line.result_id)
            checked = evaluate(result.context, self._policy(run))
            if result.status != "REORDER" or result.revision != line.result_revision or checked["status"] != "REORDER":
                raise BusinessError("Source decision is blocked or superseded")
            if checked["evidence"]["supplier_id"] != draft.supplier_id or draft.currency != run.currency:
                raise BusinessError("Supplier/currency differs from approved default mapping")
            if any(e.severity == "BLOCKING" for e in self._rows(ExceptionRecord, result_id=result.id, status="OPEN")):
                raise BusinessError("Unresolved blocking exception on PO line")
            if line.quantity <= 0 or line.unit_price <= 0 or line.quantity < checked["evidence"]["moq"] or line.quantity % checked["evidence"]["pack_multiple"]:
                raise BusinessError("Invalid quantity, price, MOQ or pack multiple")
            if line.amount != amount(line.quantity, line.unit_price):
                raise BusinessError("Stored line amount does not recompute", "PO_AMOUNT_MISMATCH")
        if draft.total != sum((r.amount for r in lines), Decimal(0)):
            raise BusinessError("Stored PO total does not recompute", "PO_AMOUNT_MISMATCH")

    @audited
    def approve_po(self, draft_id, request: Review):
        self._human()
        draft = self._locked_draft(draft_id)
        self._version(draft, request.expected_version)
        if draft.status == "APPROVED":
            raise BusinessError("PO already approved")
        self._approval_gate(draft)
        draft.status, draft.reviewer, draft.approved_at = "APPROVED", self.actor, now()
        draft.version += 1
        self._event(draft, "APPROVED", request.comment)
        return self._draft(draft)

    @audited
    def reject_po(self, draft_id, request: Review):
        self._human()
        draft = self._locked_draft(draft_id)
        self._version(draft, request.expected_version)
        draft.status, draft.reviewer, draft.approved_at = "REJECTED", None, None
        draft.version += 1
        self._event(draft, "REJECTED", request.comment)
        return self._draft(draft)

    @audited
    def export_po(self, draft_id):
        draft = self._locked_draft(draft_id)
        if draft.status != "APPROVED" or not draft.reviewer or not draft.approved_at:
            raise BusinessError("Only explicitly human-approved POs may be exported", "APPROVAL_REQUIRED")
        self._approval_gate(draft)
        output = io.StringIO(newline="")
        columns = ["po_number", "run_id", "supplier_id", "supplier_name", "currency", "warehouse", "order_date",
                   "reviewer", "approved_at", "sku_id", "description", "uom", "quantity", "unit_price", "amount",
                   "need_date", "expected_delivery_date", "result_id", "result_revision", "total", "tax_treatment", "synthetic"]
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        document = self._draft(draft)
        for line in document["lines"]:
            row = {k: line.get(k, document.get(k, "")) for k in columns}
            # Prevent spreadsheet formulas in human-entered identifiers/descriptions.
            row = {k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v) for k, v in row.items()}
            writer.writerow(row)
        self._event(draft, "EXPORTED", "Approved pre-tax synthetic PO exported as CSV")
        return {"filename": f"PO-{draft.id}.csv", "content": output.getvalue(), "document": document}

    @audited
    def list_resources(self, kind, limit=100, offset=0):
        model = {"imports": ImportBatch, "runs": ProcurementRun, "audit": ToolExecutionLog}[kind]
        return list(self.db.scalars(select(model).order_by(model.created_at.desc(), model.id).offset(offset).limit(limit)))

    @audited
    def approval_history(self, draft_id):
        self._get(PODraft, draft_id)
        return self._rows(ApprovalEvent, draft_id=draft_id)
