# Architecture and build status

```text
Portfolio YAML -> Pydantic models -> integrity validation
                                      |
                                      +-> dependency graph and queries
                                      +-> ordered strategy rules
                                      +-> TSA-aware SCC condensation and waves
                                               |
                                               +-> TSA and licence conflicts
                                               +-> metrics
                                               +-> Markdown and CSV deliverables
                                               +-> expert evaluation and v2 robustness
```

A relationship `source -> target` means the source depends on the target. The
sequencer reverses that direction for topological ordering. Strongly connected
components stay together. Assets retained under a TSA remain available while
their consumers move, then exit later. Rules and waves run without an LLM;
current documents use templates and calculated data.

## Implementation order

1. Data model, loader, portfolio and independent expert ground truth.
2. Graph construction, queries and graph exports.
3. Explainable strategy rules.
4. SCC-aware sequencing, TSA/licence/capacity constraints and metrics.
5. Template document generation and asset-reference guardrails.
6. Evaluation against the expert plan and a modified portfolio.
7. Optional LLM narratives, final report and demo materials.

The expert plan is hand-authored before sequencing and remains an independent
evaluation input.
