| Measure at 8,000 requests per second, one run of 590 seconds each | Both web nodes in service (`c2-r1`) | One web node out of service (`c2n-r1`) |
|---|---:|---:|
| Web pods running | 16 of 16 pods | 8 of 16 pods |
| Achieved request rate, as a share of the target rate | 100.00% | 100.00% |
| Failed requests, as a share of the requests sent | 0.000% | 0.000% |
| p50 response time | 3.5 ms | 3.6 ms |
| p95 response time | 9.1 ms | 23.7 ms |
| p99 response time | 11.8 ms | 38.7 ms |
| CPU utilization of the web nodes in service, as a share of their vCPUs | 44.8% of two nodes | 88.9% of one node |
| Within the limits of the staircase | yes | yes |
