| Step | Web tier | API tier | Database writer |
|---|---:|---:|---:|
| 1. CPU time per request on Graviton5, measured on configuration B at 8,000 requests per second | 0.891 ms | 0.241 ms | 0.814 ms |
| 2. CPU in use at the baseline's rated load of 11,900 requests per second: row 1 times the request rate, divided by 1,000 | 10.6 vCPUs | 2.9 vCPUs | 9.7 vCPUs |
| 3. Capacity that keeps row 2 at 80% CPU utilization: row 2 divided by 0.8 | **13.2 vCPUs** | **3.6 vCPUs of pod CPU limits** | **12.1 vCPUs** |
| 4. Capacity of the Graviton2 baseline | 32 vCPUs | 10.5 vCPUs of pod CPU limits | 32 vCPUs |
| 5. One instance size down: half the baseline, as deployed in configuration C | **16 vCPUs**: 2 x `c9g.2xlarge` | **5.25 vCPUs of pod CPU limits**: pods on 3 x `m9g.large` | **16 vCPUs**: `db.r9g.4xlarge` |
| 6. Two instance sizes down: a quarter of the baseline. Not deployed, and for the API tier not deployable with pods of 1.75 vCPUs | 8 vCPUs: less than row 3 | 2.6 vCPUs of pod CPU limits: less than row 3 | 8 vCPUs: less than row 3 |
| 7. Calculated CPU utilization at the rated load: row 2 divided by row 5 | 66.2% | 54.6% | 60.5% |
| 8. The same calculation for the comparison load of 11,800 requests per second | 65.7% | 54.2% | 60.0% |
| 9. Measured CPU utilization of configuration C at 11,800 requests per second: median of three 590-second runs | **65.6%** | **39.6%** | **61.6%** |

The rows are computed from unrounded figures; the rated load is 11,890.5 requests per second before it is rounded to 11,900.
