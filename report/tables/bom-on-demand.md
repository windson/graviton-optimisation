| Line item, in US dollars per month | A: Graviton2 baseline | B: Graviton5, same size | C: Graviton5, right-sized | Quantity and unit price |
|---|---:|---:|---:|---|
| **Compute and database** |  |  |  |  |
| Web tier nodes | 2 x c6g.4xlarge<br>$794 | 2 x c9g.4xlarge<br>$1,015 | 2 x c9g.2xlarge<br>$508 | 730 hours x the On-Demand rate per instance-hour |
| API tier nodes | 3 x m6g.xlarge<br>$337 | 3 x m9g.xlarge<br>$429 | 3 x m9g.large<br>$214 | 730 hours x the On-Demand rate per instance-hour |
| System nodes | 2 x m6g.large<br>$112 | 2 x m9g.large<br>$143 | 2 x m9g.large<br>$143 | 730 hours x the On-Demand rate per instance-hour |
| Aurora MySQL writer and reader | 2 x db.r6g.8xlarge<br>$6,063 | 2 x db.r9g.8xlarge<br>$6,480 | 2 x db.r9g.4xlarge<br>$3,240 | 730 hours x the On-Demand rate per instance-hour |
| *Subtotal: compute and database* | *$7,307* | *$8,067* | *$4,105* |  |
| **Rest of the stack** |  |  |  |  |
| Amazon EKS control plane | $73 | $73 | $73 | 730 cluster-hours x $0.10 per cluster-hour |
| Node volumes: 7 x 40 GiB gp3 | $22 | $22 | $22 | 280 GB-months x $0.08 per GB-month |
| Application Load Balancer | $16 | $16 | $16 | 730 hours x $0.0225 per hour |
| Load balancer capacity units | $340 | $340 | $340 | 42,509 LCU-hours x $0.008 per LCU-hour; bytes through the load balancer as measured in the baseline's runs at 8,000 requests per second, scaled to the average request rate; one LCU for each GB per hour of throughput |
| NAT gateway | $33 | $33 | $33 | 730 hours x $0.045 per hour |
| Aurora storage | $0.64 | $0.64 | $0.64 | 6.4 GB-months x $0.10 per GB-month |
| Aurora I/O requests | $1,077 | $1,108 | $1,132 | 5,383 to 5,659 million I/Os x $0.20 per million; estimated: the writer's write operations in this configuration at 4,000 requests per second, times the ratio of billed I/Os to write operations |
| Secrets Manager secret | $0.40 | $0.40 | $0.40 | 1 secret x $0.40 per secret per month |
| Data transfer out to the internet | $3,484 | $3,484 | $3,484 | 40,384 GB at the tiered rate ($0.09 per GB for the first 10,240 GB, then $0.085 per GB); the same bytes; 95% of them taken as responses (assumed), all sent to the internet, no CDN |
| *Subtotal: rest of the stack* | *$5,046* | *$5,078* | *$5,101* |  |
| **Total per month** | **$12,354** | **$13,145** | **$9,206** |  |
| Difference from A |  | +6.4% | -25.5% |  |
