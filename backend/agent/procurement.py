"""One bounded Procurement Agent. Stored state drives its next action.

This MVP deliberately needs no LLM/key: the planning policy is explicit, repeatable,
and has no path to human approval tools. A future language UI may invoke these skills.
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
