| Measure at 8,000 requests per second: median of three 590-second runs (lowest to highest) | **A: Graviton2 baseline** | **B: Graviton5, same size** | **C: Graviton5, right-sized** |
|---|---:|---:|---:|
| Failed requests, counted over the three runs together | 0 of 14,160,132 | 0 of 14,160,132 | 0 of 14,160,133 |
| p50 response time | 6.1 ms (6.1 to 6.1 ms) | 3.1 ms (3.1 to 3.2 ms) | 3.7 ms (3.7 to 3.7 ms) |
| p95 response time | 16.9 ms (16.9 to 17.0 ms) | 7.8 ms (7.8 to 7.9 ms) | 8.8 ms (8.7 to 8.8 ms) |
| p99 response time | 26.4 ms (26.4 to 26.7 ms) | 10.8 ms (10.8 to 10.8 ms) | 11.8 ms (11.6 to 11.8 ms) |
| Web tier: CPU utilization, as a share of the web nodes' vCPUs | 49.4% (49.2 to 49.8%) | 22.3% (22.2 to 22.3%) | 43.4% (42.7 to 43.4%) |
| API tier: CPU utilization, as a share of the API pods' CPU limits | 51.5% (51.0 to 52.3%) | 18.4% (18.3 to 18.4%) | 28.0% (27.9 to 28.1%) |
| Database writer: CPU utilization, as a share of its vCPUs | 56.7% (56.7 to 56.7%) | 20.3% (20.3 to 20.4%) | 42.5% (42.5 to 42.7%) |
