import csv
import hashlib
import io
import json
from copy import deepcopy
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import delete, func, select
from backend.domain.engine import amount, evaluate
from backend.domain.intake import normalize
from backend.integrations.adapters import CSVAdapter, JSONAdapter, SourceEnvelope
from backend.domain.schemas import (AgentConversationCreate, AgentConversationUpdate, AgentProposalCreate,
                                    LineEdit, Resolution, Review, RuleSetCreate, RunRequest, SimulationRequest)
from backend.models.entities import (ApprovalEvent, Demand, ExceptionRecord, ImportBatch, Inventory,
    LEGACY_WORKSPACE_ID, OpenPO, PODraft, POLine, ProcurementRun, SKU, SKUCheckResult,
    RuleSet, Supplier, SupplierSKU, ToolExecutionLog, Workspace, now, GoodsReceipt,
    GoodsReceiptLine, SupplierInvoice, SupplierInvoiceLine, MatchResult, SourcingDecision)
from backend.models.entities import (SupplierPerformance, CommercialAgreement, SKUInventoryPolicy,
    ApprovalMatrixRule, ApprovalDelegation, Budget, AgentChatMessage, AgentConversation,
    AgentInteraction, AgentProposal)
from backend.tools.runtime import BusinessError, audited, serial
from backend.observability import increment
from backend.domain.receiving.engine import apply_receipt, transition_po
from backend.domain.matching.engine import three_way_match
from backend.domain.approval.engine import resolve_approval_steps
from backend.domain.sourcing.engine import rank_suppliers

TABLE_MODELS = {"sku_master": SKU, "supplier_master": Supplier, "supplier_sku": SupplierSKU,
                "inventory_snapshot": Inventory, "demand": Demand, "open_po": OpenPO}
class ProcurementTools:
    def __init__(self, db, actor="service", human=False, role="purchasing", workspace_id=LEGACY_WORKSPACE_ID,
                 user_id="", correlation_id=""):
        self.db, self.actor, self.human, self.role = db, actor, human, role
        self.workspace_id = workspace_id
        self.user_id, self.correlation_id = user_id, correlation_id

    def _resource_workspace(self, obj):
        if isinstance(obj, (ImportBatch, ToolExecutionLog, RuleSet, AgentInteraction, AgentProposal,
                            AgentConversation)):
            return obj.workspace_id
        if isinstance(obj, AgentChatMessage):
            conversation = self.db.get(AgentConversation, obj.conversation_id)
            return conversation.workspace_id if conversation else None
        if isinstance(obj, (SKU, Supplier, SupplierSKU, Inventory, Demand, OpenPO)):
            batch = self.db.get(ImportBatch, obj.batch_id)
            return batch.workspace_id if batch else None
        if isinstance(obj, ProcurementRun):
            batch = self.db.get(ImportBatch, obj.batch_id)
            return batch.workspace_id if batch else None
        if isinstance(obj, (SKUCheckResult, ExceptionRecord, PODraft)):
            run = self.db.get(ProcurementRun, obj.run_id)
            return self._resource_workspace(run) if run else None
        if isinstance(obj, (POLine, ApprovalEvent)):
            draft = self.db.get(PODraft, obj.draft_id)
            return self._resource_workspace(draft) if draft else None
        if isinstance(obj, GoodsReceipt):
            return obj.workspace_id
        if isinstance(obj, GoodsReceiptLine):
            receipt = self.db.get(GoodsReceipt, obj.receipt_id)
            return receipt.workspace_id if receipt else None
        if isinstance(obj, SupplierInvoice):
            return obj.workspace_id
        if isinstance(obj, (SupplierInvoiceLine, MatchResult)):
            invoice = self.db.get(SupplierInvoice, obj.invoice_id)
            return invoice.workspace_id if invoice else None
        if isinstance(obj, SourcingDecision):
            result = self.db.get(SKUCheckResult, obj.result_id)
            return self._resource_workspace(result) if result else None
        return None

    def _get(self, model, identifier, lock=False):
        query = select(model).where(model.id == identifier)
        if lock:
            query = query.with_for_update()
        obj = self.db.scalar(query.execution_options(populate_existing=True))
        if obj is None or self._resource_workspace(obj) != self.workspace_id:
            raise BusinessError("Resource not found", "NOT_FOUND", 404)
        return obj

    def _rows(self, model, **filters):
        return list(self.db.scalars(select(model).filter_by(**filters).order_by(model.id)))

    def _human(self, role="purchasing"):
        if not self.human or not self.actor.strip():
            raise BusinessError("Explicit authenticated human action required", "HUMAN_REQUIRED", 403)
        aliases = {"purchasing": {"purchasing", "approver"}, "finance": {"finance", "approver"}}
        if self.role not in aliases.get(role, {role}) | {"owner", "admin"}:
            raise BusinessError(f"This action requires the {role} reviewer role", "REVIEWER_ROLE_REQUIRED", 403)

    def _active_rules(self, at: datetime | None = None):
        at = at or datetime.now(timezone.utc)
        query = select(RuleSet).where(
            RuleSet.workspace_id == self.workspace_id,
            RuleSet.effective_from <= at,
            (RuleSet.effective_to.is_(None) | (RuleSet.effective_to > at)),
        ).order_by(RuleSet.rule_version.desc())
        rules = self.db.scalar(query.limit(1))
        if rules:
            return rules
        workspace = self.db.get(Workspace, self.workspace_id)
        if workspace is None:
            raise BusinessError("Workspace not found", "NOT_FOUND", 404)
        rules = RuleSet(
            workspace_id=self.workspace_id, rule_version=1,
            effective_from=datetime(1970, 1, 1, tzinfo=timezone.utc),
            rules={"replenishment_policy": "BELOW_SAFETY_TO_TARGET", "rounding_policy": "MOQ_PACK_CEILING"},
            approval_policy={"currency": workspace.currency, "finance_threshold": str(workspace.finance_threshold)},
            created_by="system-migration",
        )
        self.db.add(rules)
        self.db.flush()
        return rules

    @audited
    def list_rule_sets(self):
        return list(self.db.scalars(select(RuleSet).where(
            RuleSet.workspace_id == self.workspace_id
        ).order_by(RuleSet.rule_version.desc())))

    @audited
    def create_rule_set(self, request: RuleSetCreate):
        if self.role not in {"owner", "admin"}:
            raise BusinessError("Workspace administrator permission required", "FORBIDDEN", 403)
        latest = self.db.scalar(select(RuleSet).where(
            RuleSet.workspace_id == self.workspace_id
        ).order_by(RuleSet.rule_version.desc()).limit(1))
        version = (latest.rule_version if latest else 0) + 1
        requested_at = request.effective_from
        latest_at = latest.effective_from if latest else None
        if latest_at and latest_at.tzinfo is None and requested_at.tzinfo is not None:
            latest_at = latest_at.replace(tzinfo=timezone.utc)
        if latest and requested_at <= latest_at:
            raise BusinessError("A new rule version must start after the latest version", "RULE_DATE_CONFLICT", 409)
        if latest and latest.effective_to is None:
            latest.effective_to = request.effective_from
        rule = RuleSet(
            workspace_id=self.workspace_id, rule_version=version,
            effective_from=request.effective_from, effective_to=request.effective_to,
            rules={
                "replenishment_policy": "BELOW_SAFETY_TO_TARGET",
                "rounding_policy": "MOQ_PACK_CEILING",
                "default_horizon_days": request.default_horizon_days,
                "inventory_max_age_days": request.inventory_max_age_days,
                "commercial_max_age_days": request.commercial_max_age_days,
                "matching_tolerances": {"quantity": request.matching_quantity_tolerance,
                                        "price_percent": str(request.matching_price_tolerance_percent)},
            },
            approval_policy={"currency": request.currency,
                             "finance_threshold": str(request.finance_threshold)},
            created_by=self.actor,
        )
        self.db.add(rule)
        self.db.flush()
        return rule

    @audited
    def create_domain_record(self, kind, request):
        models = {
            "supplier-performance": SupplierPerformance,
            "commercial-agreements": CommercialAgreement,
            "inventory-policies": SKUInventoryPolicy,
            "approval-rules": ApprovalMatrixRule,
            "delegations": ApprovalDelegation,
            "budgets": Budget,
        }
        model = models.get(kind)
        if model is None:
            raise BusinessError("Unknown domain resource", "NOT_FOUND", 404)
        if kind in {"approval-rules", "delegations", "budgets"} and self.role not in {"owner", "admin"}:
            raise BusinessError("Workspace administrator permission required", "FORBIDDEN", 403)
        values = request.model_dump()
        if model is ApprovalMatrixRule:
            conditions = values.pop("conditions")
            values.update(conditions=conditions)
        if model is ApprovalDelegation:
            values["created_by"] = self.actor
        record = model(workspace_id=self.workspace_id, **values)
        self.db.add(record)
        self.db.flush()
        return record

    @audited
    def list_domain_records(self, kind):
        models = {
            "supplier-performance": SupplierPerformance,
            "commercial-agreements": CommercialAgreement,
            "inventory-policies": SKUInventoryPolicy,
            "approval-rules": ApprovalMatrixRule,
            "delegations": ApprovalDelegation,
            "budgets": Budget,
        }
        model = models.get(kind)
        if model is None:
            raise BusinessError("Unknown domain resource", "NOT_FOUND", 404)
        return list(self.db.scalars(select(model).where(model.workspace_id == self.workspace_id).order_by(model.id)))

    @audited
    def source_sku(self, run_id, sku_id, request):
        run = self._get(ProcurementRun, run_id, lock=True)
        if request.as_of != run.as_of:
            raise BusinessError("Sourcing date must match the procurement run date", "PRICING_DATE_CONFLICT")
        offers = deepcopy(request.offers)
        snapshots = run.rules_snapshot or {}
        for offer in offers:
            agreements = [item for item in snapshots.get("commercial_agreements", [])
                          if item["sku_id"] == sku_id and item["supplier_id"] == offer["supplier_id"]]
            if agreements:
                agreement = max(agreements, key=lambda item: item["rule_version"])
                if sum(item["rule_version"] == agreement["rule_version"] for item in agreements) > 1:
                    raise BusinessError("Overlapping agreements have the same rule version", "AGREEMENT_CONFLICT")
                commercial_fields = {"unit_price", "contract_price", "tiers", "freight_fixed", "freight_per_unit",
                                     "additional_cost", "duty_rate", "tax_rate", "moq", "pack_multiple",
                                     "lead_time_days", "max_quantity", "fx_rate", "fx_date", "fx_source"}
                offer.update({key: value for key, value in agreement["terms"].items() if key in commercial_fields})
                offer.update(currency=agreement["currency"], valid_from=agreement["valid_from"],
                             valid_to=agreement["valid_to"], rule_version=agreement["rule_version"],
                             data_source=f"commercial_agreement:{agreement['id']}")
            performance = [item for item in snapshots.get("supplier_performance", [])
                           if item["supplier_id"] == offer["supplier_id"]]
            if performance:
                offer["performance"] = max(performance, key=lambda item: item["period_end"])
            if offer.get("currency", run.currency) != run.currency:
                if not all(offer.get(key) for key in ("fx_rate", "fx_date", "fx_source")):
                    raise BusinessError("Foreign offers require an explicit FX rate, date and source", "FX_SNAPSHOT_REQUIRED")
            elif Decimal(str(offer.get("fx_rate", 1))) != 1:
                raise BusinessError("Same-currency offers must use an FX rate of one", "INVALID_FX")
        rows = self._rows(SKUCheckResult, run_id=run_id, sku_id=sku_id)
        if not rows:
            raise BusinessError("SKU not in run", "NOT_FOUND", 404)
        record = rows[0]
        for line in self._rows(POLine, result_id=record.id):
            if self._get(PODraft, line.draft_id).lifecycle_status != "DRAFT":
                raise BusinessError("Cannot re-source a decision linked to an issued PO", "PO_IMMUTABLE")
        sourcing_block = record.status == "BLOCKED" and record.raw_order_qty and all(
            exc.code == "MISSING_SUPPLIER_MAPPING" for exc in self._rows(
                ExceptionRecord, result_id=record.id, status="OPEN"))
        if record.status != "REORDER" and not sourcing_block:
            raise BusinessError("Only a reorder need or supplier-selection block can be sourced",
                                "SOURCING_NOT_REQUIRED")
        required_quantity = record.final_order_qty or record.raw_order_qty
        if request.required_quantity != required_quantity:
            raise BusinessError("Requested sourcing quantity differs from the current SKU decision",
                                "VERSION_CONFLICT", 409)
        trace = rank_suppliers(required_quantity, offers, request.as_of,
                               request.weights, request.allow_split)
        existing = self.db.scalar(select(SourcingDecision).where(SourcingDecision.result_id == record.id))
        if existing:
            existing.trace, existing.rule_version, existing.created_by = trace, int(trace["rule_version"]), self.actor
            decision = existing
        else:
            decision = SourcingDecision(result_id=record.id, rule_version=int(trace["rule_version"]),
                                         trace=trace, created_by=self.actor)
            self.db.add(decision)
        self.db.flush()
        if sourcing_block:
            for exc in self._rows(ExceptionRecord, result_id=record.id, status="OPEN"):
                exc.status = "SUPERSEDED"
            record.status = "REORDER"
            record.final_order_qty = sum(row["quantity"] for row in trace["result"]["allocations"])
            first_risk = record.evidence["binding_date"] if record.evidence.get("inventory_policy") else next(
                item["date"] for item in record.evidence["timeline"]
                if item["projected_stock"] < record.context["sku"]["safety_stock"])
            record.evidence = {**record.evidence, "need_date": first_risk,
                               "sourcing_decision_id": decision.id, "sourcing_rule_version": decision.rule_version}
            record.decision_reason = (
                f"Projected stock requires {required_quantity} units; supplier allocation selected "
                f"{record.final_order_qty} units across {len(trace['result']['allocations'])} supplier(s)"
            )
            run = self._get(ProcurementRun, run_id, lock=True)
            self._summary(run)
        for line in self._rows(POLine, result_id=record.id):
            draft = self._get(PODraft, line.draft_id)
            self.db.delete(line)
            self.db.flush()
            draft.total = sum((row.amount for row in self._rows(POLine, draft_id=draft.id)), Decimal("0"))
            self._invalidate(draft, "Supplier allocation changed; regenerate drafts")
        self.db.flush()
        return decision

    def _import(self, envelope: SourceEnvelope, filename, idempotency_key=None):
        raw = envelope.dataset
        if idempotency_key:
            existing = self.db.scalar(select(ImportBatch).where(
                ImportBatch.workspace_id == self.workspace_id,
                ImportBatch.idempotency_key == idempotency_key,
            ))
            if existing:
                return existing
        if envelope.external_id:
            existing = self.db.scalar(select(ImportBatch).where(
                ImportBatch.workspace_id == self.workspace_id,
                ImportBatch.source_system == envelope.source_system,
                ImportBatch.external_id == envelope.external_id,
            ))
            if existing:
                return existing
        source_fields = dict(source_system=envelope.source_system, external_id=envelope.external_id,
                             synced_at=envelope.synced_at, source_metadata=envelope.metadata)
        try:
            data, issues = normalize(raw)
        except ValueError as exc:
            batch = ImportBatch(workspace_id=self.workspace_id, filename=filename, status="REJECTED", synthetic=True,
                raw_data=serial(raw), source_hash=hashlib.sha256(json.dumps(serial(raw), sort_keys=True).encode()).hexdigest(),
                issues=[{"code": "INVALID_DATASET", "message": str(exc)}],
                idempotency_key=idempotency_key, **source_fields)
            self.db.add(batch)
            self.db.flush()
            return batch
        batch = ImportBatch(workspace_id=self.workspace_id, filename=filename, status="VALIDATED_WITH_ISSUES" if issues else "VALIDATED",
            synthetic=True, raw_data=serial(raw), issues=issues,
            source_hash=hashlib.sha256(json.dumps(serial(raw), sort_keys=True).encode()).hexdigest(),
            idempotency_key=idempotency_key, **source_fields)
        self.db.add(batch)
        self.db.flush()
        for table, model in TABLE_MODELS.items():
            for row in getattr(data, table):
                row_external_id = getattr(row, "sku_id", None) or getattr(row, "supplier_id", None)
                self.db.add(model(batch_id=batch.id, source_system=envelope.source_system,
                                  external_id=row_external_id, synced_at=envelope.synced_at,
                                  source_metadata=envelope.metadata, **row.model_dump()))
            self.db.flush()
        return batch

    @audited
    def import_dataset(self, raw: dict, filename="dataset.json", idempotency_key=None):
        return self._import(JSONAdapter(raw).fetch(), filename, idempotency_key)

    @audited
    def import_files(self, files, idempotency_key=None):
        try:
            envelope = CSVAdapter(files).fetch()
        except (ValueError, UnicodeError) as exc:
            raise BusinessError(str(exc), "INVALID_UPLOAD", 422) from exc
        return self._import(envelope, ", ".join(name for name, _ in files), idempotency_key)

    @audited
    def validate_import(self, batch_id):
        batch = self._get(ImportBatch, batch_id)
        return {"id": batch.id, "status": batch.status, "issues": batch.issues}

    @audited
    def delete_import(self, batch_id):
        batch = self._get(ImportBatch, batch_id)
        run_id = self.db.scalar(
            select(ProcurementRun.id).where(ProcurementRun.batch_id == batch.id).limit(1)
        )
        if run_id:
            raise BusinessError(
                "This import is already used by a procurement review and must be retained for audit history",
                "IMPORT_IN_USE",
                409,
            )
        for model in (SupplierSKU, Inventory, Demand, OpenPO, Supplier, SKU):
            self.db.execute(delete(model).where(model.batch_id == batch.id))
        self.db.delete(batch)
        return {"id": batch_id, "deleted": True}

    def _context(self, batch_id, sku):
        def clean(row):
            source_fields = {"id", "batch_id", "source_system", "external_id", "synced_at", "source_metadata"}
            return {k: v for k, v in serial(row).items() if k not in source_fields}
        return dict(sku=clean(sku), suppliers=[clean(s) for s in self._rows(Supplier, batch_id=batch_id)],
            commercial=[clean(s) for s in self._rows(SupplierSKU, batch_id=batch_id, sku_id=sku.sku_id)],
            inventory=[clean(s) for s in self._rows(Inventory, batch_id=batch_id, sku_id=sku.sku_id)],
            demand=[clean(s) for s in self._rows(Demand, batch_id=batch_id, sku_id=sku.sku_id)],
            open_po=[clean(s) for s in self._rows(OpenPO, batch_id=batch_id, sku_id=sku.sku_id)])

    @audited
    def create_procurement_run(self, request: RunRequest, idempotency_key=None):
        batch = self._get(ImportBatch, request.batch_id)
        if not batch.status.startswith("VALIDATED"):
            raise BusinessError("Cannot run a rejected import")
        if idempotency_key:
            existing = self.db.scalar(select(ProcurementRun).where(
                ProcurementRun.batch_id == batch.id,
                ProcurementRun.idempotency_key == idempotency_key,
            ))
            if existing:
                return existing
        skus = self._rows(SKU, batch_id=batch.id, active=True)
        if not skus:
            raise BusinessError("Import contains no active SKU")
        rule_set = self._active_rules()
        rule_time = now()
        matrix_rules = self.db.scalars(select(ApprovalMatrixRule).where(
            ApprovalMatrixRule.workspace_id == self.workspace_id,
            ApprovalMatrixRule.effective_from <= rule_time,
            ApprovalMatrixRule.effective_to.is_(None) | (ApprovalMatrixRule.effective_to > rule_time),
        ).order_by(ApprovalMatrixRule.sequence, ApprovalMatrixRule.id)).all()
        matrix_snapshot = [{**rule.conditions, "id": rule.id, "sequence": rule.sequence,
                            "required_role": rule.required_role, "rule_version": rule.rule_version}
                           for rule in matrix_rules]
        inventory_snapshots = {}
        commercial_snapshots = serial(list(self.db.scalars(select(CommercialAgreement).where(
            CommercialAgreement.workspace_id == self.workspace_id,
            CommercialAgreement.valid_from <= request.as_of,
            CommercialAgreement.valid_to.is_(None) | (CommercialAgreement.valid_to >= request.as_of)))))
        performance_snapshots = serial(list(self.db.scalars(select(SupplierPerformance).where(
            SupplierPerformance.workspace_id == self.workspace_id,
            SupplierPerformance.period_end <= request.as_of))))
        for inventory_rule in self.db.scalars(select(SKUInventoryPolicy).where(
                SKUInventoryPolicy.workspace_id == self.workspace_id,
                SKUInventoryPolicy.effective_from <= rule_time,
                SKUInventoryPolicy.effective_to.is_(None) | (SKUInventoryPolicy.effective_to > rule_time),
        ).order_by(SKUInventoryPolicy.rule_version)):
            previous = inventory_snapshots.get(inventory_rule.sku_id)
            if previous and previous["rule_version"] == inventory_rule.rule_version:
                raise BusinessError("Overlapping inventory policies have the same version", "POLICY_CONFLICT")
            inventory_snapshots[inventory_rule.sku_id] = {
                **inventory_rule.parameters, "policy_type": inventory_rule.policy_type,
                "rule_version": inventory_rule.rule_version, "policy_id": inventory_rule.id}
        run = ProcurementRun(
            **request.model_dump(), expected_sku_count=len(skus), idempotency_key=idempotency_key,
            rule_set_id=rule_set.id, rule_version=rule_set.rule_version,
            rules_snapshot={**rule_set.rules, "run_policy": request.model_dump(mode="json"),
                            "approval_matrix": matrix_snapshot, "inventory_policies": inventory_snapshots,
                            "commercial_agreements": commercial_snapshots,
                            "supplier_performance": performance_snapshots},
            approval_policy_snapshot=rule_set.approval_policy,
        )
        self.db.add(run)
        self.db.flush()
        for sku in skus:
            self.db.add(SKUCheckResult(run_id=run.id, sku_id=sku.sku_id, context=self._context(batch.id, sku),
                                     decision_reason="Pending deterministic evaluation"))
        return run

    def _policy(self, run):
        snapshot = (run.rules_snapshot or {}).get("run_policy")
        return RunRequest(**snapshot) if snapshot else RunRequest(**{k: getattr(run, k) for k in RunRequest.model_fields})

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
        if draft.lifecycle_status != "DRAFT":
            raise BusinessError("Issued or closed POs cannot be edited; create a new procurement run", "PO_IMMUTABLE")
        self._release_budget(draft)
        draft.status = "NEEDS_REVIEW"
        draft.reviewer, draft.approved_at = None, None
        draft.finance_reviewer, draft.finance_approved_at = None, None
        draft.version += 1
        self._event(draft, "INVALIDATED", reason)

    def _evaluate(self, run, result):
        for line in self._rows(POLine, result_id=result.id):
            if self._get(PODraft, line.draft_id).lifecycle_status != "DRAFT":
                raise BusinessError("Cannot rerun a decision linked to an issued PO", "PO_IMMUTABLE")
        self.db.execute(delete(SourcingDecision).where(SourcingDecision.result_id == result.id))
        previous = serial(result)
        answer = evaluate(result.context, self._policy(run),
                          (run.rules_snapshot or {}).get("inventory_policies", {}).get(result.sku_id))
        for exc in self._rows(ExceptionRecord, result_id=result.id, status="OPEN"):
            exc.status = "SUPERSEDED"
        for key, value in answer.items():
            if key != "exceptions":
                setattr(result, key, value)
        result.revision += 1
        for exc in answer["exceptions"]:
            self.db.add(ExceptionRecord(run_id=run.id, result_id=result.id, **exc))
            increment("procurement_exceptions_total", code=exc["code"], severity=exc["severity"])
        for line in self._rows(POLine, result_id=result.id):
            draft = self._get(PODraft, line.draft_id)
            self.db.delete(line)
            self.db.flush()
            draft.total = sum((r.amount for r in self._rows(POLine, draft_id=draft.id)), Decimal(0))
            self._invalidate(draft, "Source decision rerun; regenerate PO drafts before review")
        self.db.flush()
        self.db.add(ToolExecutionLog(workspace_id=self.workspace_id, tool_name="evaluate_sku", actor=self.actor, status="SUCCESS",
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
        self._get(ProcurementRun, run_id)
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
        answer = evaluate(context, self._policy(run),
                          (run.rules_snapshot or {}).get("inventory_policies", {}).get(result.sku_id))
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
        run = self._get(ProcurementRun, draft.run_id)
        obj = serial(draft)
        for field in ("total", "tax", "freight", "duty", "landed_cost"):
            obj[field] = format(Decimal(str(obj.get(field) or 0)), ".2f")
        obj["po_number"] = f"PO-{draft.id}"
        obj["tax_treatment"] = "PRE_TAX"
        obj["synthetic"] = True
        obj["requires_finance_review"] = self._requires_finance(draft)
        obj["approval_policy"] = run.approval_policy_snapshot
        obj["approval_stage"] = (
            "COMPLETE" if draft.status == "APPROVED" else
            "FINANCE" if draft.status == "FINANCE_REVIEW" else "PURCHASING"
        )
        obj["lines"] = serial(self._rows(POLine, draft_id=draft.id))
        return obj

    def _requires_finance(self, draft):
        run = self._get(ProcurementRun, draft.run_id) if getattr(draft, "run_id", None) else None
        workspace = self.db.get(Workspace, self.workspace_id)
        policy = (run.approval_policy_snapshot if run else None) or {
            "currency": workspace.currency, "finance_threshold": str(workspace.finance_threshold)
        }
        currency = policy.get("currency", run.currency if run else workspace.currency)
        threshold = Decimal(str(policy.get("finance_threshold", "5000")))
        value = getattr(draft, "landed_cost", None) or draft.total
        return (getattr(draft, "base_currency", None) or draft.currency) == currency and value >= threshold

    @audited
    def generate_po_drafts(self, run_id):
        run = self._get(ProcurementRun, run_id, lock=True)
        if run.processed_count != run.expected_sku_count:
            raise BusinessError("Complete SKU scan before generating drafts")
        for result in self._rows(SKUCheckResult, run_id=run_id, status="REORDER"):
            if self._rows(POLine, result_id=result.id):
                continue
            evidence = result.evidence
            sourcing = self.db.scalar(select(SourcingDecision).where(SourcingDecision.result_id == result.id))
            if sourcing:
                offers = {offer["supplier_id"]: offer for offer in sourcing.trace["inputs"]["offers"]}
                allocations = [{"supplier_id": row["supplier_id"], "quantity": row["quantity"],
                                "offer": offers[row["supplier_id"]], "cost": row["cost"],
                                "unit_price": row["cost"]["intermediate"]["unit_price"],
                                "lead_time_days": offers[row["supplier_id"]].get("lead_time_days", 0),
                                "supplier_name": offers[row["supplier_id"]].get("supplier_name", row["supplier_id"])}
                               for row in sourcing.trace["result"]["allocations"]]
            else:
                supplier_id = evidence["supplier_id"]
                supplier = next(s for s in result.context["suppliers"] if s["supplier_id"] == supplier_id)
                allocations = [{"supplier_id": supplier_id, "quantity": result.final_order_qty,
                                "unit_price": evidence["unit_price"], "supplier_name": supplier["supplier_name"],
                                "expected_delivery_date": evidence["expected_delivery_date"]}]
            for allocation in allocations:
                drafts = self._rows(PODraft, run_id=run_id, supplier_id=allocation["supplier_id"])
                if drafts:
                    draft = drafts[0]
                    if draft.currency != allocation.get("offer", {}).get("currency", run.currency):
                        raise BusinessError("A supplier PO cannot mix transaction currencies", "CURRENCY_CONFLICT")
                    self._invalidate(draft, "Added newly evaluated source line")
                else:
                    draft = PODraft(run_id=run_id, supplier_id=allocation["supplier_id"],
                        supplier_name=allocation["supplier_name"], currency=allocation.get("offer", {}).get("currency", run.currency),
                        warehouse=run.warehouse, order_date=run.as_of, base_currency=run.currency,
                        exchange_rate=Decimal("1"), exchange_rate_date=run.as_of,
                        exchange_rate_source="same-currency")
                    self.db.add(draft)
                    self.db.flush()
                qty, price = allocation["quantity"], Decimal(str(allocation["unit_price"]))
                expected = allocation.get("expected_delivery_date") or (
                    run.as_of + timedelta(days=int(allocation["lead_time_days"]))).isoformat()
                self.db.add(POLine(draft_id=draft.id, result_id=result.id, result_revision=result.revision,
                    sku_id=result.sku_id, description=result.context["sku"]["description"],
                    uom=result.context["sku"]["uom"], quantity=qty, unit_price=price,
                    amount=amount(qty, price), open_quantity=qty,
                    need_date=date.fromisoformat(evidence["need_date"]),
                    expected_delivery_date=date.fromisoformat(expected)))
                self.db.flush()
                draft.total = sum((r.amount for r in self._rows(POLine, draft_id=draft.id)), Decimal(0))
                if "cost" in allocation:
                    offer = allocation["offer"]
                    rate = Decimal(str(offer.get("fx_rate", 1)))
                    if draft.exchange_rate is not None and draft.exchange_rate != rate:
                        raise BusinessError("A supplier PO cannot mix FX snapshots", "FX_CONFLICT")
                    draft.base_currency, draft.exchange_rate = run.currency, rate
                    draft.exchange_rate_date = date.fromisoformat(offer.get("fx_date", run.as_of.isoformat()))
                    draft.exchange_rate_source = offer.get("fx_source", "same-currency")
                draft.tax = draft.freight = draft.duty = Decimal("0")
                for priced_line in self._rows(POLine, draft_id=draft.id):
                    decision = self.db.scalar(select(SourcingDecision).where(
                        SourcingDecision.result_id == priced_line.result_id))
                    if decision:
                        priced = next(item for item in decision.trace["result"]["allocations"]
                                      if item["supplier_id"] == draft.supplier_id)["cost"]["intermediate"]
                        draft.tax += Decimal(priced["tax"])
                        draft.freight += Decimal(priced["freight"]) + Decimal(priced["additional_cost"])
                        draft.duty += Decimal(priced["duty"])
                draft.landed_cost = ((draft.total + draft.tax + draft.freight + draft.duty) *
                                     (draft.exchange_rate or Decimal(1))).quantize(Decimal("0.01"))
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
        previous = self.db.scalar(select(ProcurementRun).join(
            ImportBatch, ProcurementRun.batch_id == ImportBatch.id
        ).where(
            ImportBatch.workspace_id == self.workspace_id,
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
            answer = evaluate(context, policy,
                              (run.rules_snapshot or {}).get("inventory_policies", {}).get(result.sku_id))
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
        from backend.agent.messages import ChatTurn, MessageRequest, reply
        if not request.conversation_id:
            return reply(self, request)
        conversation = self._conversation(request.conversation_id, lock=True)
        history_rows = list(self.db.scalars(select(AgentChatMessage).where(
            AgentChatMessage.conversation_id == conversation.id
        ).order_by(AgentChatMessage.sequence.desc()).limit(12)))
        history = [ChatTurn(role=row.role, content=row.content[:4000]) for row in reversed(history_rows)]
        effective = MessageRequest(message=request.message, run_id=request.run_id or conversation.run_id,
                                   sku_id=request.sku_id, conversation_id=conversation.id, history=history)
        result = reply(self, effective)
        last_sequence = self.db.scalar(select(func.max(AgentChatMessage.sequence)).where(
            AgentChatMessage.conversation_id == conversation.id)) or 0
        self.db.add(AgentChatMessage(conversation_id=conversation.id, sequence=last_sequence + 1, role="user",
                                    content=request.message, message_metadata={"run_id": effective.run_id}))
        self.db.add(AgentChatMessage(
            conversation_id=conversation.id, sequence=last_sequence + 2, role="assistant", content=result["message"],
            interaction_id=result.get("interaction_id"),
            message_metadata={key: serial(result.get(key)) for key in (
                "provider", "tools_used", "evidence", "evidence_complete", "unresolved",
                "confirmation_required", "action", "page", "sku_id") if result.get(key) is not None},
        ))
        if conversation.title == "New procurement chat":
            conversation.title = request.message.strip()[:120]
        if effective.run_id:
            conversation.run_id = effective.run_id
        conversation.updated_at = now()
        result["conversation_id"] = conversation.id
        return result

    def _chat_owner(self):
        return self.user_id or f"{self.role}:{self.actor}"

    def _conversation(self, conversation_id, lock=False):
        conversation = self._get(AgentConversation, conversation_id, lock=lock)
        if conversation.owner_id != self._chat_owner():
            raise BusinessError("Conversation not found", "NOT_FOUND", 404)
        return conversation

    @audited
    def create_agent_conversation(self, request: AgentConversationCreate):
        if request.run_id:
            self._get(ProcurementRun, request.run_id)
        conversation = AgentConversation(
            workspace_id=self.workspace_id, owner_id=self._chat_owner(), title=request.title.strip(),
            run_id=request.run_id, created_by=self.actor,
        )
        self.db.add(conversation)
        self.db.flush()
        return serial(conversation)

    @audited
    def list_agent_conversations(self, limit=50, offset=0):
        rows = list(self.db.scalars(select(AgentConversation).where(
            AgentConversation.workspace_id == self.workspace_id,
            AgentConversation.owner_id == self._chat_owner(),
        ).order_by(AgentConversation.updated_at.desc(), AgentConversation.id.desc()).offset(offset).limit(limit)))
        output = []
        for row in rows:
            messages = list(self.db.scalars(select(AgentChatMessage).where(
                AgentChatMessage.conversation_id == row.id
            ).order_by(AgentChatMessage.sequence.desc()).limit(1)))
            count = self.db.scalar(select(func.count()).select_from(AgentChatMessage).where(
                AgentChatMessage.conversation_id == row.id)) or 0
            data = serial(row)
            data.update(message_count=count, last_message=messages[0].content[:160] if messages else "")
            output.append(data)
        return output

    @audited
    def get_agent_conversation(self, conversation_id, limit=200, before=None):
        conversation = self._conversation(conversation_id)
        query = select(AgentChatMessage).where(AgentChatMessage.conversation_id == conversation.id)
        if before:
            anchor = self._get(AgentChatMessage, before)
            if anchor.conversation_id != conversation.id:
                raise BusinessError("Message not found", "NOT_FOUND", 404)
            query = query.where(AgentChatMessage.sequence < anchor.sequence)
        rows = list(self.db.scalars(query.order_by(
            AgentChatMessage.sequence.desc()).limit(limit + 1)))
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        return {"conversation": serial(conversation), "messages": [serial(row) for row in rows],
                "has_more": has_more, "oldest_message_id": rows[0].id if rows else None}

    @audited
    def update_agent_conversation(self, conversation_id, request: AgentConversationUpdate):
        conversation = self._conversation(conversation_id)
        conversation.title = request.title.strip()
        conversation.updated_at = now()
        return serial(conversation)

    @audited
    def delete_agent_conversation(self, conversation_id):
        conversation = self._conversation(conversation_id)
        self.db.execute(delete(AgentChatMessage).where(AgentChatMessage.conversation_id == conversation.id))
        self.db.delete(conversation)
        return {"id": conversation_id, "deleted": True}

    @audited
    def list_agent_interactions(self, limit=50, offset=0):
        query = select(AgentInteraction).where(AgentInteraction.workspace_id == self.workspace_id)
        if self.role not in {"owner", "admin"}:
            query = query.where(AgentInteraction.user_id == self.user_id) if self.user_id else query.where(
                AgentInteraction.actor == self.actor)
        rows = self.db.scalars(query.order_by(
            AgentInteraction.started_at.desc()).offset(offset).limit(limit))
        return [serial(row) for row in rows]

    def _interaction(self, interaction_id):
        interaction = self._get(AgentInteraction, interaction_id)
        if self.role not in {"owner", "admin"}:
            same_user = interaction.user_id == self.user_id if self.user_id else interaction.actor == self.actor
            if not same_user:
                raise BusinessError("Agent interaction not found", "NOT_FOUND", 404)
        return interaction

    @audited
    def get_agent_interaction(self, interaction_id):
        return serial(self._interaction(interaction_id))

    @audited
    def replay_agent_interaction(self, interaction_id):
        from backend.agent.messages import MessageRequest, reply
        original = self._interaction(interaction_id)
        request = MessageRequest(**original.request)
        # Replay re-reads current authoritative state and exposes only read-only tools.
        return reply(self, request, replay_of_id=original.id)

    @audited
    def create_agent_proposal(self, request: AgentProposalCreate):
        if not self.human:
            raise BusinessError("Explicit authenticated human action required", "HUMAN_REQUIRED", 403)
        if self.role not in {"owner", "admin", "procurement", "procurement_user", "purchasing", "approver"}:
            raise BusinessError("Your role cannot propose procurement changes", "FORBIDDEN", 403)
        change = request.exact_change
        if request.proposal_type == "PO_LINE_EDIT":
            line = self._get(POLine, request.target_id)
            draft = self._get(PODraft, line.draft_id)
            self._version(draft, request.expected_version)
            allowed = {"quantity", "unit_price"}
            if not change or set(change) - allowed:
                raise BusinessError("A PO line proposal may change only quantity or unit_price", "INVALID_PROPOSAL", 422)
            # Pydantic performs the same numeric validation used by the domain write.
            LineEdit(expected_version=request.expected_version, reason=request.reason, **change)
            target_type = "po_line"
        else:
            draft = self._get(PODraft, request.target_id)
            self._version(draft, request.expected_version)
            if set(change) - {"comment"}:
                raise BusinessError("An approval proposal may contain only a comment", "INVALID_PROPOSAL", 422)
            Review(expected_version=request.expected_version, comment=str(change.get("comment") or request.reason), confirm=True)
            target_type = "po_draft"
        proposal = AgentProposal(
            workspace_id=self.workspace_id, interaction_id=request.interaction_id,
            proposal_type=request.proposal_type, target_type=target_type, target_id=request.target_id,
            expected_version=request.expected_version, exact_change=serial(change), reason=request.reason,
            status="PENDING", created_by=self.actor,
        )
        self.db.add(proposal)
        self.db.flush()
        return serial(proposal)

    @audited
    def list_agent_proposals(self, status=None, limit=50, offset=0):
        query = select(AgentProposal).where(AgentProposal.workspace_id == self.workspace_id)
        if status:
            query = query.where(AgentProposal.status == status)
        rows = self.db.scalars(query.order_by(AgentProposal.created_at.desc()).offset(offset).limit(limit))
        return [serial(row) for row in rows]

    @audited
    def confirm_agent_proposal(self, proposal_id):
        self._human()
        proposal = self._get(AgentProposal, proposal_id, lock=True)
        if proposal.status != "PENDING":
            raise BusinessError("Only a pending proposal can be confirmed", "INVALID_STATE")
        if proposal.proposal_type == "PO_APPROVAL" and self.role not in {"owner", "admin", "purchasing", "finance", "approver"}:
            raise BusinessError("Your role cannot confirm this approval", "FORBIDDEN", 403)
        proposal.status = "CONFIRMED"
        proposal.confirmed_by = self.actor
        proposal.confirmed_at = now()
        return serial(proposal)

    @audited
    def execute_agent_proposal(self, proposal_id):
        self._human()
        proposal = self._get(AgentProposal, proposal_id, lock=True)
        if proposal.status != "CONFIRMED" or not proposal.confirmed_by:
            raise BusinessError("Confirm the exact change before execution", "CONFIRMATION_REQUIRED")
        if proposal.proposal_type == "PO_LINE_EDIT":
            line = self._get(POLine, proposal.target_id)
            result = self.update_po_line(line.draft_id, line.id, LineEdit(
                expected_version=proposal.expected_version, reason=proposal.reason, **proposal.exact_change))
        elif proposal.proposal_type == "PO_APPROVAL":
            result = self.matrix_approve(proposal.target_id, Review(
                expected_version=proposal.expected_version,
                comment=str(proposal.exact_change.get("comment") or proposal.reason), confirm=True))
        else:
            raise BusinessError("Unsupported proposal type", "INVALID_PROPOSAL", 422)
        proposal = self._get(AgentProposal, proposal_id, lock=True)
        proposal.status = "EXECUTED"
        proposal.executed_at = now()
        proposal.execution_result = serial(result)
        return serial(proposal)

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
        if self.db.scalar(select(SourcingDecision.id).where(SourcingDecision.result_id == result.id)):
            raise BusinessError("Re-run supplier sourcing to change an allocated line", "SOURCING_RECALC_REQUIRED")
        qty = request.quantity if request.quantity is not None else line.quantity
        price = request.unit_price if request.unit_price is not None else line.unit_price
        if qty < result.evidence["moq"] or qty % result.evidence["pack_multiple"]:
            raise BusinessError("Edited quantity violates MOQ or pack multiple")
        line.quantity, line.unit_price, line.amount = qty, price, amount(qty, price)
        line.open_quantity = qty - line.received_quantity + line.returned_quantity
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
            checked = evaluate(result.context, self._policy(run),
                               (run.rules_snapshot or {}).get("inventory_policies", {}).get(result.sku_id))
            sourcing = self.db.scalar(select(SourcingDecision).where(SourcingDecision.result_id == result.id))
            source_only_block = sourcing and checked["status"] == "BLOCKED" and checked["raw_order_qty"] and all(
                exc["code"] == "MISSING_SUPPLIER_MAPPING" for exc in checked["exceptions"])
            if (result.status != "REORDER" or result.revision != line.result_revision or
                    (checked["status"] != "REORDER" and not source_only_block)):
                raise BusinessError("Source decision is blocked or superseded")
            if sourcing:
                offer = next((item for item in sourcing.trace["inputs"]["offers"]
                              if item["supplier_id"] == draft.supplier_id), None)
                allocation = next((item for item in sourcing.trace["result"]["allocations"]
                                   if item["supplier_id"] == draft.supplier_id), None)
                if not offer or not allocation or draft.currency != run.currency:
                    raise BusinessError("Supplier allocation differs from the approved sourcing decision")
                moq, pack = int(offer.get("moq", 0)), int(offer.get("pack_multiple", 1))
                selected_price = Decimal(allocation["cost"]["intermediate"]["unit_price"])
                if line.quantity != allocation["quantity"] or line.unit_price != selected_price:
                    raise BusinessError("PO line differs from the approved sourcing allocation")
            else:
                if checked["evidence"]["supplier_id"] != draft.supplier_id or draft.currency != run.currency:
                    raise BusinessError("Supplier/currency differs from approved default mapping")
                moq, pack = checked["evidence"]["moq"], checked["evidence"]["pack_multiple"]
            if any(e.severity == "BLOCKING" for e in self._rows(ExceptionRecord, result_id=result.id, status="OPEN")):
                raise BusinessError("Unresolved blocking exception on PO line")
            if line.quantity <= 0 or line.unit_price <= 0 or line.quantity < moq or line.quantity % pack:
                raise BusinessError("Invalid quantity, price, MOQ or pack multiple")
            if line.amount != amount(line.quantity, line.unit_price):
                raise BusinessError("Stored line amount does not recompute", "PO_AMOUNT_MISMATCH")
        if draft.total != sum((r.amount for r in lines), Decimal(0)):
            raise BusinessError("Stored PO total does not recompute", "PO_AMOUNT_MISMATCH")
        if draft.budget_code:
            budget = self.db.scalar(select(Budget).where(
                Budget.workspace_id == self.workspace_id, Budget.budget_code == draft.budget_code,
                Budget.currency == (draft.base_currency or draft.currency)))
            if not budget:
                raise BusinessError("Referenced budget does not exist in the PO base currency", "BUDGET_NOT_FOUND")
            commitment = draft.landed_cost or draft.total
            already_committed = self._budget_commitment(draft) is not None
            if not already_committed and budget.committed_amount + commitment > budget.authorized_amount:
                raise BusinessError("PO exceeds available budget", "BUDGET_EXCEEDED")
        plan = self.approval_plan(draft.id)
        approved_rules = self._approved_matrix_rules(draft)
        pending = [step for step in plan["result"]["steps"] if step["rule_id"] not in approved_rules]
        if pending:
            raise BusinessError("Configured approval matrix steps remain incomplete", "APPROVAL_MATRIX_REQUIRED")

    def _budget_commitment(self, draft):
        events = self._rows(ApprovalEvent, draft_id=draft.id)
        released = {event.snapshot.get("released_commitment_id") for event in events
                    if event.action == "BUDGET_RELEASED"}
        return next((event for event in events if event.action == "BUDGET_COMMITTED" and event.id not in released), None)

    def _release_budget(self, draft):
        committed = self._budget_commitment(draft)
        if committed is None:
            return
        snapshot = committed.snapshot
        budget = self.db.scalar(select(Budget).where(
            Budget.workspace_id == self.workspace_id, Budget.budget_code == snapshot["budget_code"],
            Budget.currency == (snapshot.get("base_currency") or snapshot["currency"])).with_for_update())
        value = Decimal(snapshot.get("landed_cost") or snapshot["total"])
        if budget is None or budget.committed_amount < value:
            raise BusinessError("Budget commitment requires reconciliation", "BUDGET_INCONSISTENT")
        budget.committed_amount -= value
        self.db.add(ApprovalEvent(draft_id=draft.id, action="BUDGET_RELEASED", actor=self.actor,
            version=draft.version, comment="Released prior PO commitment",
            snapshot={"released_commitment_id": committed.id, "amount": str(value)}))
        self.db.flush()

    def _commit_budget(self, draft):
        if not draft.budget_code or self._budget_commitment(draft) is not None:
            return
        budget = self.db.scalar(select(Budget).where(
            Budget.workspace_id == self.workspace_id, Budget.budget_code == draft.budget_code,
            Budget.currency == (draft.base_currency or draft.currency)).with_for_update())
        if not budget:
            raise BusinessError("Referenced budget does not exist", "BUDGET_NOT_FOUND")
        commitment = draft.landed_cost or draft.total
        if budget.committed_amount + commitment > budget.authorized_amount:
            raise BusinessError("PO exceeds available budget", "BUDGET_EXCEEDED")
        budget.committed_amount += commitment
        self._event(draft, "BUDGET_COMMITTED", f"Committed {commitment} {budget.currency} to {budget.budget_code}")

    def _approved_matrix_rules(self, draft):
        events = self._rows(ApprovalEvent, draft_id=draft.id)
        last_invalidation = max((event.version for event in events if event.action in {"INVALIDATED", "REJECTED"}), default=0)
        return {event.snapshot.get("matrix_rule_id") for event in events
                if event.action == "MATRIX_APPROVED" and event.version >= last_invalidation}

    def approval_plan(self, draft_id):
        draft = self._get(PODraft, draft_id)
        current = now()
        run = self._get(ProcurementRun, draft.run_id)
        rule_payload = (run.rules_snapshot or {}).get("approval_matrix", [])
        delegations = list(self.db.scalars(select(ApprovalDelegation).where(
            ApprovalDelegation.workspace_id == self.workspace_id,
            ApprovalDelegation.valid_from <= current, ApprovalDelegation.valid_to >= current)))
        risk = "HIGH" if any(e.severity == "BLOCKING" for e in self._rows(
            ExceptionRecord, run_id=draft.run_id, status="OPEN")) else "NORMAL"
        delegation_payload = [{"id": item.id, "delegator_role": item.delegator_role,
                               "delegate_role": item.delegate_role,
                               "delegator_user_id": item.delegator_user_id,
                               "delegate_user_id": item.delegate_user_id,
                               "valid_from": item.valid_from.isoformat(), "valid_to": item.valid_to.isoformat()}
                              for item in delegations]
        return resolve_approval_steps(
            {"amount": str(draft.landed_cost or draft.total), "cost_center": draft.cost_center,
             "supplier_id": draft.supplier_id, "risk_level": risk,
             "rule_version": max((rule["rule_version"] for rule in rule_payload), default=1)},
            rule_payload, delegation_payload, current)

    @audited
    def matrix_approve(self, draft_id, request):
        self._human(self.role)
        draft = self._locked_draft(draft_id)
        self._version(draft, request.expected_version)
        plan = self.approval_plan(draft.id)
        approved = self._approved_matrix_rules(draft)
        pending = [step for step in plan["result"]["steps"] if step["rule_id"] not in approved]
        if not pending:
            raise BusinessError("Approval matrix is already complete", "ALREADY_APPROVED")
        step = pending[0]
        if self.role not in {step["required_role"], step["acting_role"], "owner", "admin"}:
            raise BusinessError("The next approval matrix step requires another role", "FORBIDDEN", 403)
        if step["delegated"] and step.get("delegate_user_id") and self.role not in {"owner", "admin"}:
            if self.user_id != step["delegate_user_id"]:
                raise BusinessError("This delegated approval belongs to another user", "FORBIDDEN", 403)
        self.db.add(ApprovalEvent(draft_id=draft.id, action="MATRIX_APPROVED", actor=self.actor,
            version=draft.version, comment=request.comment,
            snapshot={"matrix_rule_id": step["rule_id"], "step": step, "draft": self._draft(draft)}))
        return {"approved_step": step, "plan": plan}

    @audited
    def approve_po(self, draft_id, request: Review):
        self._human("purchasing")
        draft = self._locked_draft(draft_id)
        self._version(draft, request.expected_version)
        if draft.status in {"APPROVED", "FINANCE_REVIEW"}:
            raise BusinessError("Purchasing approval already recorded")
        self._approval_gate(draft)
        draft.reviewer, draft.approved_at = self.actor, now()
        draft.finance_reviewer, draft.finance_approved_at = None, None
        draft.status = "FINANCE_REVIEW" if self._requires_finance(draft) else "APPROVED"
        draft.version += 1
        self._event(draft, "PURCHASING_APPROVED" if draft.status == "FINANCE_REVIEW" else "APPROVED", request.comment)
        if draft.status == "APPROVED":
            self._commit_budget(draft)
        return self._draft(draft)

    @audited
    def finance_approve_po(self, draft_id, request: Review):
        self._human("finance")
        draft = self._locked_draft(draft_id)
        self._version(draft, request.expected_version)
        if not self._requires_finance(draft):
            raise BusinessError("This draft does not meet the workspace Finance review threshold")
        if draft.status != "FINANCE_REVIEW" or not draft.reviewer or not draft.approved_at:
            raise BusinessError("Purchasing Manager approval is required before Finance review", "PURCHASING_APPROVAL_REQUIRED")
        self._approval_gate(draft)
        draft.status = "APPROVED"
        draft.finance_reviewer, draft.finance_approved_at = self.actor, now()
        draft.version += 1
        self._event(draft, "FINANCE_APPROVED", request.comment)
        self._commit_budget(draft)
        return self._draft(draft)

    @audited
    def reject_po(self, draft_id, request: Review):
        draft = self._locked_draft(draft_id)
        required_role = "finance" if draft.status == "FINANCE_REVIEW" else "purchasing"
        self._human(required_role)
        self._version(draft, request.expected_version)
        if draft.lifecycle_status != "DRAFT":
            raise BusinessError("An issued PO cannot be rejected as a draft", "PO_IMMUTABLE")
        self._release_budget(draft)
        if self.role == "finance" and draft.status != "FINANCE_REVIEW":
            raise BusinessError("Finance can reject only drafts awaiting Finance review")
        draft.status, draft.reviewer, draft.approved_at = "REJECTED", None, None
        draft.finance_reviewer, draft.finance_approved_at = None, None
        draft.version += 1
        self._event(draft, "REJECTED", request.comment)
        return self._draft(draft)

    @audited
    def export_po(self, draft_id):
        draft = self._locked_draft(draft_id)
        if draft.status != "APPROVED" or not draft.reviewer or not draft.approved_at:
            raise BusinessError("Only explicitly human-approved POs may be exported", "APPROVAL_REQUIRED")
        if self._requires_finance(draft) and (not draft.finance_reviewer or not draft.finance_approved_at):
            raise BusinessError("Finance Manager approval is required by the workspace policy", "FINANCE_APPROVAL_REQUIRED")
        self._approval_gate(draft)
        output = io.StringIO(newline="")
        columns = ["po_number", "run_id", "supplier_id", "supplier_name", "currency", "warehouse", "order_date",
                   "reviewer", "approved_at", "finance_reviewer", "finance_approved_at",
                   "sku_id", "description", "uom", "quantity", "unit_price", "amount",
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
    def set_finance_dimensions(self, draft_id, request):
        draft = self._locked_draft(draft_id)
        if draft.status == "APPROVED":
            raise BusinessError("Finance dimensions must be fixed before final approval", "APPROVED_IMMUTABLE")
        for key, value in request.model_dump().items():
            setattr(draft, key, value)
        draft.landed_cost = ((draft.total + draft.tax + draft.freight + draft.duty) *
                             draft.exchange_rate).quantize(Decimal("0.01"))
        self._invalidate(draft, "Finance dimensions or exchange-rate snapshot changed")
        return self._draft(draft)

    @audited
    def transition_po_lifecycle(self, draft_id, target_status, reason):
        self._human()
        draft = self._locked_draft(draft_id)
        if target_status in {"PARTIALLY_RECEIVED", "RECEIVED", "RETURNED"}:
            raise BusinessError("Record a goods receipt or return to update quantities and receipt status", "RECEIPT_REQUIRED")
        if target_status == "SENT" and draft.status != "APPROVED":
            raise BusinessError("Only an approved PO may be sent", "APPROVAL_REQUIRED")
        if target_status == "CANCELLED" and (
                any(line.received_quantity for line in self._rows(POLine, draft_id=draft.id)) or
                self._rows(SupplierInvoice, draft_id=draft.id)):
            raise BusinessError("Received or invoiced POs require financial reconciliation before cancellation",
                                "RECONCILIATION_REQUIRED")
        draft.lifecycle_status = transition_po(draft.lifecycle_status, target_status)
        if target_status == "CANCELLED":
            self._release_budget(draft)
        self._event(draft, f"LIFECYCLE_{target_status}", reason)
        return self._draft(draft)

    @audited
    def record_goods_receipt(self, draft_id, request):
        draft = self._locked_draft(draft_id)
        existing = self.db.scalar(select(GoodsReceipt).where(
            GoodsReceipt.workspace_id == self.workspace_id, GoodsReceipt.external_id == request.external_id))
        if existing:
            if existing.draft_id != draft.id:
                raise BusinessError("Receipt external ID is already linked to another PO", "DUPLICATE_EXTERNAL_ID")
            expected = sorted((line.po_line_id, line.quantity, line.rejected_quantity, line.returned_quantity)
                              for line in request.lines)
            recorded = sorted((line.po_line_id, line.quantity, line.rejected_quantity, line.returned_quantity)
                              for line in self._rows(GoodsReceiptLine, receipt_id=existing.id))
            if expected != recorded:
                raise BusinessError("Receipt reference was already used with different quantities", "IDEMPOTENCY_CONFLICT", 409)
            return existing
        if draft.lifecycle_status not in {"SENT", "DELAYED", "PARTIALLY_RECEIVED", "RECEIVED", "RETURNED"}:
            raise BusinessError("PO must be sent before receipt", "INVALID_PO_LIFECYCLE")
        receipt = GoodsReceipt(workspace_id=self.workspace_id, draft_id=draft.id,
            external_id=request.external_id, received_at=request.received_at, created_by=self.actor)
        self.db.add(receipt)
        self.db.flush()
        for submitted in request.lines:
            line = self._get(POLine, submitted.po_line_id, lock=True)
            if line.draft_id != draft.id:
                raise BusinessError("Receipt line does not belong to PO", "REFERENCE_MISMATCH")
            accepted = submitted.quantity - submitted.rejected_quantity
            if accepted < 0:
                raise BusinessError("Rejected quantity exceeds receipt quantity", "INVALID_RECEIPT")
            try:
                result = apply_receipt(line.quantity, line.received_quantity, accepted,
                                       line.returned_quantity, submitted.returned_quantity)
            except ValueError as exc:
                raise BusinessError(str(exc), "INVALID_RECEIPT") from exc
            line.received_quantity = result["intermediate"]["received_total"]
            line.returned_quantity = result["intermediate"]["returned_total"]
            line.open_quantity = result["result"]["open_quantity"]
            self.db.add(GoodsReceiptLine(receipt_id=receipt.id, po_line_id=line.id, sku_id=line.sku_id,
                quantity=submitted.quantity, rejected_quantity=submitted.rejected_quantity,
                returned_quantity=submitted.returned_quantity))
        lines = self._rows(POLine, draft_id=draft.id)
        draft.lifecycle_status = "RECEIVED" if all(line.open_quantity == 0 for line in lines) else "PARTIALLY_RECEIVED"
        if any(line.returned_quantity for line in lines) and all(
                line.received_quantity == line.returned_quantity for line in lines):
            draft.lifecycle_status = "RETURNED"
        self._event(draft, f"LIFECYCLE_{draft.lifecycle_status}", f"Goods receipt {request.external_id}")
        return receipt

    @audited
    def record_and_match_invoice(self, draft_id, request):
        draft = self._locked_draft(draft_id)
        existing = self.db.scalar(select(SupplierInvoice).where(
            SupplierInvoice.workspace_id == self.workspace_id,
            SupplierInvoice.supplier_id == request.supplier_id,
            SupplierInvoice.invoice_number == request.invoice_number))
        if existing:
            if existing.draft_id != draft.id:
                raise BusinessError("Invoice number is already linked to another PO", "DUPLICATE_EXTERNAL_ID")
            expected = sorted((line.po_line_id, line.sku_id, line.quantity, line.unit_price) for line in request.lines)
            recorded = sorted((line.po_line_id, line.sku_id, line.quantity, line.unit_price)
                              for line in self._rows(SupplierInvoiceLine, invoice_id=existing.id))
            if expected != recorded or request.currency != existing.currency or request.exchange_rate != existing.exchange_rate:
                raise BusinessError("Invoice reference was already used with different values", "IDEMPOTENCY_CONFLICT", 409)
            return {**serial(existing), "matches": serial(self._rows(MatchResult, invoice_id=existing.id))}
        if request.supplier_id != draft.supplier_id or request.currency != draft.currency:
            raise BusinessError("Invoice supplier or currency differs from PO", "REFERENCE_MISMATCH")
        run = self._get(ProcurementRun, draft.run_id)
        tolerances = (run.rules_snapshot or {}).get("matching_tolerances", {})
        quantity_tolerance = int(tolerances.get("quantity", 0))
        price_tolerance = Decimal(str(tolerances.get("price_percent", 0)))
        if request.quantity_tolerance != quantity_tolerance or request.price_tolerance_percent != price_tolerance:
            raise BusinessError("Invoice tolerances must match the run's frozen policy", "TOLERANCE_POLICY_MISMATCH")
        total = sum((amount(line.quantity, line.unit_price) for line in request.lines), Decimal("0"))
        invoice = SupplierInvoice(workspace_id=self.workspace_id, draft_id=draft.id,
            supplier_id=request.supplier_id, invoice_number=request.invoice_number,
            invoice_date=request.invoice_date, currency=request.currency,
            exchange_rate=request.exchange_rate, exchange_rate_date=request.exchange_rate_date,
            exchange_rate_source=request.exchange_rate_source, total=total)
        self.db.add(invoice)
        self.db.flush()
        has_exception = False
        for submitted in request.lines:
            line = self._get(POLine, submitted.po_line_id)
            if line.draft_id != draft.id or line.sku_id != submitted.sku_id:
                raise BusinessError("Invoice line does not reference the PO line", "REFERENCE_MISMATCH")
            previous_lines = self.db.scalars(select(SupplierInvoiceLine).join(SupplierInvoice).where(
                SupplierInvoice.workspace_id == self.workspace_id,
                SupplierInvoiceLine.po_line_id == line.id)).all()
            previously_invoiced = sum(row.quantity for row in previous_lines)
            self.db.add(SupplierInvoiceLine(invoice_id=invoice.id, po_line_id=line.id,
                sku_id=line.sku_id, quantity=submitted.quantity, unit_price=submitted.unit_price,
                amount=amount(submitted.quantity, submitted.unit_price)))
            receipts = self.db.execute(select(GoodsReceiptLine).join(GoodsReceipt).where(
                GoodsReceipt.workspace_id == self.workspace_id, GoodsReceiptLine.po_line_id == line.id,
                GoodsReceipt.status == "POSTED")).scalars().all()
            trace = three_way_match(
                {"line_id": line.id, "po_number": f"PO-{draft.id}", "sku_id": line.sku_id,
                 "quantity": line.quantity, "unit_price": str(line.unit_price),
                 "previously_invoiced_quantity": previously_invoiced},
                [{"po_line_id": row.po_line_id, "quantity": row.quantity - row.rejected_quantity - row.returned_quantity}
                 for row in receipts],
                {"po_number": f"PO-{draft.id}", "sku_id": submitted.sku_id,
                 "quantity": submitted.quantity, "unit_price": str(submitted.unit_price)},
                {"quantity": quantity_tolerance,
                 "price_percent": str(price_tolerance), "rule_version": run.rule_version})
            has_exception |= trace["result"]["status"] == "EXCEPTION"
            self.db.add(MatchResult(invoice_id=invoice.id, po_line_id=line.id,
                                    status=trace["result"]["status"], rule_version=run.rule_version, trace=trace))
        invoice.status = "MATCH_EXCEPTION" if has_exception else "MATCHED"
        self.db.flush()
        return {**serial(invoice), "matches": serial(self._rows(MatchResult, invoice_id=invoice.id))}

    @audited
    def list_resources(self, kind, limit=100, offset=0):
        model = {"imports": ImportBatch, "runs": ProcurementRun, "audit": ToolExecutionLog}[kind]
        if kind in {"imports", "audit"}:
            query = select(model).where(model.workspace_id == self.workspace_id)
        else:
            query = select(ProcurementRun).join(
                ImportBatch, ProcurementRun.batch_id == ImportBatch.id
            ).where(ImportBatch.workspace_id == self.workspace_id)
        return list(self.db.scalars(query.order_by(model.created_at.desc(), model.id).offset(offset).limit(limit)))

    @audited
    def approval_history(self, draft_id):
        self._get(PODraft, draft_id)
        return self._rows(ApprovalEvent, draft_id=draft_id)
