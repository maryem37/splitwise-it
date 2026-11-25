# Fictional portfolio v1: Nordia Retail

Retail division of Atlas Group sold to a private equity buyer.
30 assets, 61 relationships, 7 licences, 4 TSA services.
Convention: `source -> target` means the source DEPENDS ON the target.

## Edge cases and what the engine should do

| # | Edge case | Where | Expected behaviour |
|---|---|---|---|
| 1 | Shared ERP | APP-01, DB-01 (TSA-01) | Strategy: retain under TSA, then rebuild. Many assets depend on it. |
| 2 | Cycle | APP-06 <-> APP-07 | Detected as one strongly connected component and moved in the same wave. |
| 3 | Non-transferable licence | LIC-01, LIC-02, LIC-05 | No plain clone or migrate. Retain under TSA or rebuild. |
| 4 | Licence expiring during the programme | LIC-04 (ends 2027-04-30) on APP-08 | APP-08 depends on the ERP, so it cuts over after the licence ends. Flag it. |
| 5 | Legacy app with no users | APP-12, DB-06, INF-05 | Strategy: retire. |
| 6 | Shared identity (AD/SSO) | INF-03 | Hub: 7+ assets authenticate via it. Must separate early. |
| 7 | Sensitive data | DB-01, DB-02, DB-04 | Higher risk, extra checks in the runbook. |
| 8 | TSA too short for a heavy dependency | TSA-01 ends 2027-09-30, not extendable | APP-01 exits TSA in Wave 5 (~Nov 2027), after TSA-01 ends. Flag it. |
| 9 | Duplicate function | APP-04 vs APP-05 (CRM) | APP-05: retire and consolidate into APP-04. |
| 10 | Wave capacity | max 8 assets per wave | Naive level grouping gives a wave with 9 assets, so the splitter is exercised. |
| 11 | Extendable TSA used as buffer | TSA-02, TSA-03, TSA-04 | Cost and extension should appear in the TSA exit schedule. |

## Sanity checks already run
- Loads and validates with 0 errors and 0 warnings.
- Exactly one cycle: APP-06 / APP-07.
- Naive level grouping gives 5 levels (before capacity and constraints).
- Rough schedule check (`build_effort_weeks` in parallel from `day1` `2027-01-04`, plus `effort_weeks` per wave from `cutover_start` `2027-03-01`):
  `APP-08` finishes after `LIC-04` (`2027-04-30`), and `APP-01` exits `TSA-01` after `2027-09-30`, so both conflicts must be raised.
  `retain_under_tsa` assets exit in the same or a later wave than all their dependents (`wave(src) <= wave(tgt)`).

These are rough numbers from a quick check, not the final engine output.
Write `expert_plan_v1.yaml` by hand, before building the engine, to avoid tuning it to the code.
