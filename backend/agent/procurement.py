"""One bounded Procurement Agent. Stored state drives its next action.

The deterministic review needs no model key. The separate chat module reads its
results through bounded tools; neither workflow can grant human approval.
"""
from backend.skills.workflows import POPreparation, ProcurementCheck


class ProcurementAgent:
    def __init__(self, tools):
        self.tools = tools

    def daily_review(self, request):
        summary = ProcurementCheck(self.tools).execute(request)
        return self.resume(summary["id"])

    def resume(self, run_id):
        summary = self.tools.get_run_summary(run_id)
        if summary["processed_count"] < summary["expected_sku_count"]:
            self.tools.run_full_check(run_id)
        drafts = POPreparation(self.tools).execute(run_id)
        exceptions = self.tools.list_exceptions(run_id)
        summary = self.tools.get_run_summary(run_id)
        active = [d for d in drafts if d["lines"]]
        if summary["blocked_count"]:
            next_action = "RESOLVE_EXCEPTIONS_AND_REVIEW"
        elif any(d["status"] != "APPROVED" for d in active):
            next_action = "HUMAN_REVIEW"
        elif active:
            next_action = "APPROVED_READY_FOR_EXPORT"
        else:
            next_action = "NO_ACTION_REQUIRED"
        return {"run": summary, "drafts": drafts,
                "exceptions": [e for e in exceptions if e["status"] == "OPEN"],
                "next_action": next_action}
