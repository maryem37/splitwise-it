# Demo slides: dependency-graph separation planner

## Slide 1 — Plan a safe IT separation

**Nordia Retail carve-out planner**

- 30 assets across applications, data and infrastructure.
- Deterministic strategies and waves with explainable reasons.
- Documents follow computed data; they do not invent decisions.

*Presenter note:* Frame this as a planning prototype for a fictional retail division, not an executable production cutover plan.

---

## Slide 2 — Why sequencing matters

- Applications rely on data stores, identity, networks and shared platforms.
- Shared services continue under TSA while buyer replacements are built.
- Licence expiry, service cost, cutover capacity and business readiness constrain the order.

**Relationship convention:** `source -> target` means source depends on target.

*Presenter note:* Moving a prerequisite too late can block many applications; leaving shared services too long can breach TSA dates and raise costs.

---

## Slide 3 — Portfolio edge cases

- Shared ERP and financial database with non-transferable licences.
- Shared Active Directory/SSO used across the portfolio.
- APP-06 Inventory and APP-07 WMS form a dependency cycle.
- Payment licence LIC-04 expires before the planned completion.
- Sensitive customer and financial data, duplicate CRMs, and unused legacy systems.

*Presenter note:* Point to `data/portfolio_v1.yaml` and the edge-case guide in `data/README.md`.

---

## Slide 4 — Architecture and controls

```text
YAML -> validation -> dependency graph -> ordered strategy rules
                                      -> SCC-aware wave sequencing
                                      -> conflict and metric calculations
                                      -> plan, runbooks, TSA schedule, risk register
                                      -> evaluation against expert reference
```

- Python, Pydantic, NetworkX, YAML rules and templates.
- LLM narrative is optional; it cannot change strategies, waves, dates or tables.
- Generated asset references are checked against the portfolio.

---

## Slide 5 — Computed strategy and waves

- 83.33% strategy match with the independent expert plan.
- 7 waves for 30 assets; capacity limit is 8 per wave.
- One strongly connected component; APP-06 and APP-07 stay together.
- 0 dependency-order violations.

**Critical finding:** latest estimated completion is 18 Dec 2028; target TSA exit is 31 Dec 2027.

*Presenter note:* The schedule is intentionally allowed to show infeasible dates; conflicts are evidence for programme decisions.

---

## Slide 6 — TSA and licence exposure

| Finding | Computed result |
|---|---|
| Estimated TSA exposure | $3.415 million |
| TSA-01 | 24 months / $2.04 million; APP-01 and APP-14 finish after the non-extendable end date |
| TSA-02 | APP-09 requires extension coverage |
| TSA-04 | DB-05, INF-02 and APP-19 require extension or contingency |
| LIC-04 | APP-08 completes after the licence expires |

*Presenter note:* These are scenario estimates from fictional inputs, not approved budgets or vendor quotes.

---

## Slide 7 — Evaluation and limits

- Dependency violations: **0**; cycles grouped: **yes**.
- Exact wave-number match: **23.33%**; pairwise order similarity: **70.33%**.
- Expert risk coverage: **80.00%**; unknown structured asset IDs: **0**.
- Four-asset robustness portfolio: all assets scheduled, 0 dependency violations.

**Limits:** fictional effort estimates, no staff/resource calendar, portfolio-specific rules, optional AI not run against a live provider.

---

## Slide 8 — Demo and decisions

1. Run `carveout run-all`.
2. Open `output/graph.html`, `output/separation_plan.md`, and a wave runbook.
3. Review `output/waves.json`, `output/tsa_exit_schedule.csv`, and `evaluation/analysis.md`.
4. Decide how to resolve the ERP/TSA-01 overrun, payment licence expiry and five strategy mismatches.

**Next:** validate estimates with owners, agree TSA contingency, refine expert/rule definitions, then exercise optional AI and build a polished UI.
