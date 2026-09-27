"""Business workflows compose atomic tools. No calculations or inferred tool output."""
from backend.domain.schemas import RunRequest


class DataIntake:
    def __init__(self, tools):
        self.tools = tools

    def execute(self, raw):
        batch = self.tools.import_dataset(raw)
        validation = self.tools.validate_import(batch["id"])
        return {"batch": batch, "validation": validation}


class ProcurementCheck:
    def __init__(self, tools):
        self.tools = tools

    def execute(self, request: RunRequest):
        run = self.tools.create_procurement_run(request)
        self.tools.run_full_check(run["id"])
        return self.tools.get_run_summary(run["id"])


class ExceptionResolution:
    def __init__(self, tools):
        self.tools = tools

    def execute(self, exception_id, request):
        # The atomic resolution tool updates evidence and reruns the SKU in one transaction.
        return self.tools.resolve_exception(exception_id, request)


class POPreparation:
    def __init__(self, tools):
        self.tools = tools

    def execute(self, run_id):
        return self.tools.generate_po_drafts(run_id)


class Approval:
    def __init__(self, human_tools):
        self.tools = human_tools

    def execute(self, draft_id, request, approve=True):
        return (self.tools.approve_po if approve else self.tools.reject_po)(draft_id, request)
