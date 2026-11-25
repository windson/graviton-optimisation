|  | **A: Graviton2 baseline** | **B: Graviton5, same size** | **C: Graviton5, right-sized** |
|---|---:|---:|---:|
| Web nodes<br>API nodes<br>Aurora MySQL instances | 2 x `c6g.4xlarge`<br>3 x `m6g.xlarge`<br>2 x `db.r6g.8xlarge` | 2 x `c9g.4xlarge`<br>3 x `m9g.xlarge`<br>2 x `db.r9g.8xlarge` | 2 x `c9g.2xlarge`<br>3 x `m9g.large`<br>2 x `db.r9g.4xlarge` |
| CPU utilization of the busiest tier at the comparison load of 11,800 requests per second; the API tier's is a share of its pods' CPU limits | 79%, database writer (API tier: 79%) | 33%, web tier, at 12,000 requests per second ¹ | 66%, web tier |
| p99 response time at the comparison load of 11,800 requests per second | 33.3 ms | 11.1 ms, at 12,000 requests per second ¹ | 15.6 ms |
| Rated load: the request rate at 80% CPU utilization, from each configuration's ceiling run | about 11,900 requests per second | about 28,400 requests per second | about 14,900 requests per second |
| EC2 and Aurora instances, On-Demand | $7,307 per month | $8,067 per month (+10% against A) | $4,105 per month (-44% against A) |
| Modelled bill of the stack, On-Demand, at an average of 4,000 requests per second: the items listed in `report/tables/bom-on-demand.md` | $12,354 per month | $13,145 per month (+6% against A) | $9,206 per month (-25% against A) |

¹ Configuration B was not run at 11,800 requests per second. Its figures are from one 110-second step of its capacity run, at 12,000 requests per second, and are shown for reference.
