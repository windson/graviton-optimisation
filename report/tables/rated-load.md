| Measure | **A: Graviton2 baseline** | **B: Graviton5, same size** | **C: Graviton5, right-sized** |
|---|---:|---:|---:|
| Request rate | 11,800 requests per second | 12,000 requests per second | 11,800 requests per second |
| Runs | 3 runs of 590 seconds | 1 step of 110 seconds | 3 runs of 590 seconds |
| Achieved request rate, as a share of the target rate | 100.00% (100.00 to 100.00%) | 99.99% | 100.00% (100.00 to 100.00%) |
| Failed requests, as a share of the requests sent | 0.000% (0.000 to 0.000%) | 0.000% | 0.000% (0.000 to 0.000%) |
| p50 response time | 7.1 ms (7.0 to 7.1 ms) | 3.3 ms | 3.8 ms (3.8 to 3.8 ms) |
| p95 response time | 22.1 ms (21.2 to 22.1 ms) | 8.2 ms | 11.1 ms (11.0 to 11.1 ms) |
| p99 response time | 33.3 ms (31.7 to 33.3 ms) | 11.1 ms | 15.6 ms (15.6 to 15.7 ms) |
| Web tier: CPU utilization, as a share of the web nodes' vCPUs | 73.2% (71.6 to 73.5%) | 33.1% | 65.6% (65.5 to 65.7%) |
| API tier: CPU utilization, as a share of the API pods' CPU limits | 78.7% (78.4 to 79.4%) | 29.0% | 39.6% (39.6 to 40.1%) |
| Database writer: CPU utilization, as a share of its vCPUs | 79.3% (78.8 to 79.4%) | 30.7% | 61.6% (61.6 to 61.6%) |
| CPU utilization of the busiest tier: the highest of the three figures above | **79.3%**, database writer | **33.1%**, web tier | **65.6%**, web tier |
| CPU utilization of the busiest single node in any run, measured the same way | 87.8%, an API node | 33.5%, a web node | 66.0%, a web node |
| API containers: share of their scheduling periods in which the CPU limit stopped them, counted over each run as a whole | 0.8% (0.5 to 1.0%) | 1.1% over its whole staircase | 0.0% (0.0 to 0.0%) |
| Web tier: CPU time per request | 1.985 ms (1.942 to 1.992 ms) | 0.883 ms | 0.889 ms (0.889 to 0.890 ms) |
| API tier: CPU time per request | 0.700 ms (0.697 to 0.706 ms) | 0.253 ms | 0.176 ms (0.176 to 0.179 ms) |
| Database writer: CPU time per request | 2.151 ms (2.138 to 2.153 ms) | 0.818 ms | 0.835 ms (0.835 to 0.836 ms) |

Figures of several runs are the median, with the lowest and highest run in brackets. Configuration B was not run at 11,800 requests per second: its column is one 110-second step of its capacity run at 12,000 requests per second, from the first session, shown for reference.
