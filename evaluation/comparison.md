# Evaluation comparison

| Metric | Result |
|---|---:|
| dependency violations | 0 |
| strategy match percent | 83.33 |
| wave exact match percent | 33.33 |
| wave order similarity percent | 71.43 |
| risk coverage percent | 60.0 |
| hallucination count | 0 |
| hallucination assets | [] |
| cycles grouped | True |
| expert asset count | 30 |
| computed asset count | 30 |

## Strategy mismatches

- `INF-04`: expected migrate, got clone
- `APP-13`: expected migrate, got clone
- `APP-14`: expected rebuild, got retain_under_tsa
- `APP-18`: expected migrate, got clone
- `APP-19`: expected rebuild, got retain_under_tsa
