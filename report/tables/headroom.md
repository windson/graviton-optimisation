|  | **A: Graviton2 baseline** | **B: Graviton5, same size** | **C: Graviton5, right-sized** |
|---|---:|---:|---:|
| Ceiling run, 590 seconds | 11,800 requests per second: API tier at 79.4% CPU utilization, p99 response time 31.7 ms, 0.00% of requests failed | 28,400 requests per second: web tier at 80.0% CPU utilization, p99 response time 19.6 ms, 0.00% of requests failed | 14,800 requests per second: web tier at 79.3% CPU utilization, p99 response time 23.2 ms, 0.00% of requests failed |
| **Rated load:** the rate of that run, scaled to 80% CPU utilization of the busiest tier | **about 11,900 requests per second** | **about 28,400 requests per second** | **about 14,900 requests per second** |
| Rated load against the baseline's |  | 2.39 times (+139%) | 1.25 times (+25%) |
| Rated load above the comparison load of 11,800 requests per second | +100 requests per second (+1%) | +16,600 requests per second (+141%) | +3,100 requests per second (+26%) |
| For comparison: the rating that the runs at 11,800 requests per second point to, their rate scaled to 80% CPU utilization | about 11,900 requests per second, scaled from 79% CPU utilization in 3 runs | not given: one step, at 12,000 requests per second and 33% CPU utilization | about 14,400 requests per second, scaled from 66% CPU utilization in 3 runs |
| Highest passing step of the staircase, 110 seconds per step | 14,400 requests per second | at least 32,000 requests per second | 16,800 requests per second |
| First failing step | 15,200 requests per second: 26% of requests failed | none: it passed every step | 17,600 requests per second: p99 response time 179 ms |
| From the rated load to the highest passing step | +21% | at least +13% | +13% |

The ratios and differences in this table are those of the reported rated loads, which are rounded to 100 requests per second, so that they can be recomputed from the table.
