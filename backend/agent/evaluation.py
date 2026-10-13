"""Deterministic regression scorer for versioned Procurement Agent evaluation cases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def score_case(case: dict) -> dict:
    observed = case["observed"]
    calls = observed.get("tool_calls", [])
    called = [c.get("name") for c in calls]
    expected = case.get("expected_tools", [])
    allowed = set(case.get("allowed_tools", expected))
    correct_tools = all(name in called for name in expected) and all(name in allowed for name in called)
    args_ok = all(all(c.get("arguments", {}).get(k) == v for k, v in expected_args.items())
                  for c, expected_args in zip(calls, case.get("expected_arguments", [])))
    answer = observed.get("final_answer", "").lower()
    correctness = all(term.lower() in answer for term in case.get("required_answer_terms", []))
    fabricated = any(term.lower() in answer for term in case.get("forbidden_claims", []))
    policy = len(observed.get("policy_violations", [])) == 0
    unnecessary = max(0, len(calls) - int(case.get("max_tool_calls", len(calls))))
    return {
        "id": case["id"], "category": case["category"],
        "final_answer_correctness": correctness,
        "tool_selection_correctness": correct_tools,
        "tool_argument_correctness": args_ok,
        "unsupported_or_fabricated_claims": fabricated,
        "task_completion": bool(observed.get("task_completed")) and correctness,
        "unnecessary_tool_calls": unnecessary,
        "policy_violations": len(observed.get("policy_violations", [])),
        "passed": correctness and correct_tools and args_ok and not fabricated and policy and unnecessary == 0,
    }


def evaluate(dataset: Path) -> dict:
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    scores = [score_case(case) for case in cases]
    count = len(scores) or 1
    boolean_metrics = ["final_answer_correctness", "tool_selection_correctness", "tool_argument_correctness",
                       "task_completion", "passed"]
    summary = {metric: round(sum(bool(s[metric]) for s in scores) / count, 4) for metric in boolean_metrics}
    summary.update({
        "unsupported_or_fabricated_claim_rate": round(sum(s["unsupported_or_fabricated_claims"] for s in scores) / count, 4),
        "average_unnecessary_tool_calls": round(sum(s["unnecessary_tool_calls"] for s in scores) / count, 4),
        "policy_violation_rate": round(sum(s["policy_violations"] > 0 for s in scores) / count, 4),
    })
    return {"dataset": dataset.name, "dataset_version": cases[0].get("dataset_version") if cases else None,
            "case_count": len(cases), "summary": summary, "cases": scores}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/procurement_agent_v1.jsonl")
    parser.add_argument("--output", default="evals/report-v1.json")
    args = parser.parse_args()
    report = evaluate(Path(args.dataset))
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
