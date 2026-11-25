| Configuration | Modelled On-Demand bill of the whole stack | Bill per million requests, at an average of 4,000 requests per second | EC2 and Aurora instances, On-Demand | Rated load at 80% CPU utilization | Monthly instance cost per 1,000 requests per second of rated load |
|---|---:|---:|---:|---:|---:|
| **A: Graviton2 baseline** | $12,354 per month | $1.18 per million requests | $7,307 per month | about 11,900 requests per second | $614 per month |
| **B: Graviton5, same size** | $13,145 per month | $1.25 per million requests | $8,067 per month | about 28,400 requests per second | $284 per month |
| **C: Graviton5, right-sized** | $9,206 per month | $0.88 per million requests | $4,105 per month | about 14,900 requests per second | $275 per month |
