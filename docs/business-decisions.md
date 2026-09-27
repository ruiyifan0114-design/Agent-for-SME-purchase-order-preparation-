# Business specification implementation map

Authority: the user's backend prompt plus the existing `biz module` CSVs, all 14 sheets of `Biz_Module_Master.xlsx`, and `Biz_Module_Design_Spec.docx`. The source artifacts were read without changes. Vendor links in the business package are conceptual references, not extra MVP requirements.

| Rule/control | Implemented behavior | Automated evidence |
| --- | --- | --- |
| BR-01/02, AC-01 | Exactly one default mapping; supplier and SKU relation approved; no auto-selection | supplier approval, missing mapping, human supplier correction tests |
| BR-03/04, EX-C01/02/03 | Missing mapping/approval/price blocks only the affected SKU | bad commercial data and partial-progress tests |
| BR-05/06, AC-03/04/05 | Explicit MOQ/pack; integer ceil(max(raw,MOQ)/pack)*pack | UAT 36→50 and 63→70; edited quantity rejection |
| BR-07 | Lead-time evidence and feasibility warnings; missing lead time blocks | deterministic engine, demo expected dates |
| BR-08, AC-12 | One run+supplier draft, one current line per result, row lock | grouping/idempotency and PostgreSQL concurrent generation |
| BR-09, AC-09/10 | Separate human credential, explicit confirmation, identity/time captured | machine cannot approve, HTTP end-to-end |
| BR-10, AC-11 | Quantity/price/source/default-supplier changes invalidate approval | critical-edit, rerun, supplier correction tests |
| BR-11, AC-06/07 | Decimal pricing; HALF_UP line rounding, sum of line amounts; no tax | decimal calculation, corrupted line/total rejection |
| BR-12 | Batch → run → SKU context/result/revision → PO line → approval snapshot | frozen-run and resolution history tests |
| AC-08 | Recheck domain data and open blocking exceptions at approval/export | approval gate and resolved-exception workflow |

## Explicit engineering choices for open questions

| Business question | Handling |
| --- | --- |
| Q-01 Currency | Required run input; supplier/mapping must match. XTS only in synthetic fixtures. No actual currency assumed. |
| Q-02/03 SKU/supplier identities | Reuse the ten template examples and SUP-A/B/C; synthetic labels retained in docs/output. |
| Q-04/05/06 Prices, MOQ, pack, lead time | Explicit synthetic fixture values; placeholders normalized to missing. Missing modifiers block; use MOQ=0/pack=1 to explicitly state no restriction. |
| Q-07 Staleness | Both thresholds required in run request. Demo 1/30 days is a synthetic test choice, not confirmed business policy. Applies to inventory and commercial update dates; future dates also block. |
| Q-08 Reviewer | Server-configured generic reviewer, separate credential, no assumed business role. |
| Q-09 Approval amount threshold | None added. Every final PO requires human approval. |
| Q-10 Tax | Excluded; PO/export explicitly PRE_TAX. Two-decimal money is the MVP currency precision policy. |
| Q-11 Payment/shipping terms | Out of scope; one explicit warehouse destination. |
| Q-12 Numbering | Unique `PO-<UUID>`, no external numbering convention assumed. |
| Q-13 Overrides | User prompt explicitly requests line edits. Human quantity/price edits supported with reason and invalidation; supplier changes through human source/default-mapping correction only. |
| Q-14 Partial progress | User prompt explicitly authorizes unaffected SKUs to continue. BLOCKED SKUs remain visible and do not enter PO drafts. |

The safety/target rule, strict-below-safety trigger, dated minimum stock checkpoint, mandatory explicit modifiers, and warning severity for feasible-but-late new orders are documented implementation policies. They should be reviewed by the team's Physics/Biz owners before freezing a competition dataset. The engine is deterministic and isolated so that policy can be replaced without giving calculations to an LLM.

## Exception mapping

`MISSING_SUPPLIER_MAPPING` ↔ EX-C01; `SUPPLIER_NOT_APPROVED` ↔ EX-C02; `MISSING_PRICE` ↔ EX-C03; `INVALID_MOQ` ↔ EX-C04; `INVALID_PACK_MULTIPLE` ↔ EX-C05; commercial `STALE_DATA` ↔ EX-C06; `PO_AMOUNT_MISMATCH` ↔ EX-C07; approval-history `INVALIDATED` ↔ EX-C08.

Inventory-related codes include MISSING_INVENTORY, DUPLICATE_INVENTORY, CONFLICTING_INVENTORY, STALE_DATA. Invalid/ambiguous demand, open PO or stock policy blocks rather than assuming zero. Past-due OPEN POs produce OVERDUE_OPEN_PO because arrival is not confirmed; future late POs remain visible as LATE_OPEN_PO warnings and cannot cover earlier demand.

PO_AMOUNT_MISMATCH is an approval/export guard error and a FAILED tool log, not a replenishment input exception. It cannot be waived through the exception endpoint. Human edit/recalculation repairs amounts and requires fresh approval.

## Deliberate MVP limits

One deterministic workflow Agent; no chat model, real ERP, vendor messages, multi-supplier optimization, tax engine, scheduling daemon or multi-user identity provider. Daily reviews are explicit API/CLI calls. Raw imports are immutable; human corrections are run-local evidence. Independent daily runs must receive refreshed inputs, including newly placed open POs, to avoid reordering across separate reviews. A technical database outage fails visibly; it does not get converted into a fabricated SKU result.
