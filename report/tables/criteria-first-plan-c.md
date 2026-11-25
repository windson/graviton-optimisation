| Criterion of the first plan | A: Graviton2 baseline | Configuration C | Difference | Threshold | Result |
|---|---:|---:|---:|---|---|
| Achieved request rate (requests sent, failed ones included) | 100.00% of the target rate | 100.00% of the target rate |  | at least 99.5% of target | **Met** |
| Error rate | 0.000% of requests | 0.000% of requests |  | at most 0.1% and at most baseline + 0.05 percentage points | **Met** |
| p50 response time | 6.1 ms | 3.7 ms | -40.0% | at most +5% vs baseline | **Met** |
| p95 response time | 16.9 ms | 8.8 ms | -47.8% | at most +5% vs baseline | **Met** |
| p99 response time | 26.4 ms | 11.8 ms | -55.5% | at most +10% vs baseline | **Met** |
| Highest passing step of the capacity run | 14,400 requests per second | 16,800 requests per second | +17% | at least 95% of baseline | **Met** |

The first five rows are medians of three 590-second runs at 8,000 requests per second. The last row compares the two staircases, with 110 seconds measured per step.
