| Request rate of the step, requests per second | A: Graviton2 baseline: p99 response time | B: Graviton5, same size: p99 response time | C: Graviton5, right-sized: p99 response time |
|---:|---:|---:|---:|
| 8,000 | 27 ms | 11 ms | 12 ms |
| 9,600 | 28 ms |  | 13 ms |
| 11,200 | 31 ms |  | 15 ms |
| 12,000 | 33 ms | 11 ms | 17 ms |
| 12,800 | 38 ms |  | 18 ms |
| 13,600 | 45 ms |  | 20 ms |
| 14,400 | 58 ms |  | 22 ms |
| 15,200 | fails: 26% of requests failed |  | 27 ms |
| 16,000 | fails: 31% of requests failed | 12 ms | 33 ms |
| 16,800 | fails: 31% of requests failed |  | 49 ms |
| 17,600 | fails: 31% of requests failed |  | fails: 179 ms |
| 20,000 |  | 12 ms |  |
| 24,000 |  | 14 ms |  |
| 25,600 |  | 15 ms |  |
| 27,200 |  | 17 ms |  |
| 28,800 |  | 21 ms |  |
| 30,400 |  | 25 ms |  |
| 32,000 |  | 33 ms |  |
