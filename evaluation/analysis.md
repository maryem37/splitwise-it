# Evaluation analysis

- Dependency violations: 0 (target: 0).
- Strategy match: 83.33%.
- Exact expert wave match: 23.33%.
- Pairwise wave order similarity: 70.33%.
- Expert risk coverage: 80.0%.
- Unknown asset references: 0.

Wave exact match compares wave numbers asset by asset. A low score can reflect different grouping or capacity assumptions even when dependency violations are zero. Review strategy mismatches and wave differences against the expert assumptions before changing rules.

## Strategy mismatches

- `INF-04`: expected `migrate`, computed `clone`.
- `APP-13`: expected `migrate`, computed `clone`.
- `APP-14`: expected `rebuild`, computed `retain_under_tsa`.
- `APP-18`: expected `migrate`, computed `clone`.
- `APP-19`: expected `rebuild`, computed `retain_under_tsa`.
