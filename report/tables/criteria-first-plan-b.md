| Criterion of the first plan | A: Graviton2 baseline | Configuration B | Difference | Threshold | Result |
|---|---:|---:|---:|---|---|
| Achieved request rate (requests sent, failed ones included) | 100.00% of the target rate | 100.00% of the target rate |  | at least 99.5% of target | **Met** |
| Error rate | 0.000% of requests | 0.000% of requests |  | at most 0.1% and at most baseline + 0.05 percentage points | **Met** |
| p50 response time | 6.1 ms | 3.1 ms | -48.3% | at most +5% vs baseline | **Met** |
| p95 response time | 16.9 ms | 7.8 ms | -53.7% | at most +5% vs baseline | **Met** |
| p99 response time | 26.4 ms | 10.8 ms | -59.3% | at most +10% vs baseline | **Met** |
| Highest passing step of the capacity run | 14,400 requests per second | at least 32,000 requests per second | at least +122% | at least 95% of baseline | **Met** |

The first five rows are medians of three 590-second runs at 8,000 requests per second. The last row compares the two staircases, with 110 seconds measured per step.
