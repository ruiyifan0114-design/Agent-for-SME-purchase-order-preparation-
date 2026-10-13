# Procurement Agent operations

The Agent is a single orchestration layer. Inventory, sourcing, pricing, landed cost,
matching, PO changes and approvals remain deterministic backend services. PostgreSQL is
the source of truth; each turn re-reads the selected run rather than trusting chat memory.

## Persistent conversations

Each signed-in user can maintain multiple chats inside a workspace. Conversation titles,
messages and the last selected procurement run are stored in PostgreSQL. On every turn the
backend loads the latest 12 saved messages for linguistic context; client-supplied history is
ignored when a conversation ID is present. The full history remains inspectable in the UI,
while the bounded model context controls token use. Chat ownership is enforced in the backend,
and ordinary members can inspect or replay only their own Agent interactions. Workspace owners
and administrators retain workspace-wide audit access.

Conversation context may resolve references such as “that supplier” or “the previous option”,
but it is not business truth. The Agent must still call authorized tools for current SKU, PO,
supplier, price, approval and inventory facts.

## Security and evidence

Every tool call is authorized by the backend role. Viewers receive operational status but
commercial fields are redacted and cannot call spend, PO or scenario tools. Imported text
is untrusted and never becomes an instruction. Business facts include field-level evidence
with source file/system, record ID, field, timestamp and rule/revision version.

List tools return `total`, `next_cursor` and `complete`. The Agent must follow continuation
cursors before claiming all rows were inspected. Results that exceed the bounded payload are
rejected explicitly rather than silently truncated.

## Sensitive changes

Sensitive actions use `POST /agent/proposals`, followed by separate authenticated calls to
`/{id}/confirm` and `/{id}/execute`. Execution rechecks the target version and delegates to
the existing PO or approval domain service. A stale target fails without changing state.

## Resilience and audit

Safe model inference may retry on timeouts, rate limits and server failures. A circuit breaker,
deadline, tool limit, token budget and estimated cost budget bound each turn. Tool writes are
never retried. `/agent/interactions` records provider/model, versioned prompt/config/tools,
validated arguments, hashed result references, outcome, usage and timestamps. Replay is
read-only and re-reads current authoritative state, so it does not claim bit-for-bit historical
results when source data has changed.

## Evaluation

Run:

```bash
python -m backend.agent.evaluation --dataset evals/procurement_agent_v1.jsonl --output evals/report-v1.json
```

The versioned regression set covers normal, missing/conflicting data, delayed POs, supplier
comparison, approvals, malicious instructions and tool failures. It scores answer correctness,
tool selection/arguments, fabrication, completion, unnecessary calls and policy violations.
The checked-in report is a deterministic baseline, not a claim about live-provider quality;
replace each case's `observed` trace with a captured candidate trace for release evaluation.
