# Evaluation analysis

- Dependency violations: 0 (target: 0).
- Strategy match: 73.33%.
- Exact expert wave match: 33.33%.
- Pairwise wave order similarity: 71.43%.
- Expert risk coverage: 60.0%.
- Unknown asset references: 0.

Wave exact match compares wave numbers asset by asset. A low score can reflect different grouping or capacity assumptions even when dependency violations are zero. Review strategy mismatches and wave differences against the expert assumptions before changing rules.

## Strategy mismatches

- `INF-01`: expected `retain_under_tsa`, computed `retain_under_tsa`.
- `INF-02`: expected `retain_under_tsa`, computed `retain_under_tsa`.
- `INF-04`: expected `migrate`, computed `clone`.
- `DB-05`: expected `retain_under_tsa`, computed `retain_under_tsa`.
- `APP-01`: expected `retain_under_tsa`, computed `retain_under_tsa`.
- `APP-10`: expected `retain_under_tsa`, computed `retain_under_tsa`.
- `APP-13`: expected `migrate`, computed `clone`.
- `APP-18`: expected `migrate`, computed `clone`.
