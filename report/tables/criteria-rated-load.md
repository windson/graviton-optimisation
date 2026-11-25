| Criterion at 11,800 requests per second | A: Graviton2 baseline, median of 3 runs | C: Graviton5, right-sized, median of 3 runs | Difference | Threshold for C | Result |
|---|---:|---:|---:|---|---|
| Achieved request rate | 100.00% of the target rate | 100.00% of the target rate | not used: the threshold is absolute | At least 99.5% | **Met** |
| Error rate | 0.000% of requests | 0.000% of requests | +0.000 percentage points | At most 0.1%, and at most the baseline's plus 0.05 percentage points | **Met** |
| p50 response time | 7.1 ms | 3.8 ms | -46% | At most 5% above the baseline's | **Met** |
| p95 response time | 22.1 ms | 11.1 ms | -50% | At most 5% above the baseline's | **Met** |
| p99 response time | 33.3 ms | 15.6 ms | -53% | At most 10% above the baseline's | **Met** |
| CPU utilization of the busiest tier: the highest of the three tier medians | 79.3%, database writer | 65.6%, web tier | -13.7 percentage points | At most 80% | **Met** |
