| Tier | CPU the tier may use | CPU in use at 14,800 requests per second | CPU utilization: in use, as a share of what the tier may use | CPU utilization of the busiest node, measured the same way | Request rate at which this tier would be at 80% CPU utilization |
|---|---|---:|---:|---:|---:|
| Web tier | 16 vCPUs: 2 web nodes of 8 vCPUs | 12.7 vCPUs | **79.3%** | 79.6% | 14,926 requests per second |
| API tier | 5.25 vCPUs: the CPU limits of 3 API pods, 1.75 vCPUs each | 2.8 vCPUs | **53.2%** | 60.2% | 22,256 requests per second |
| Database writer | 16 vCPUs: one `db.r9g.4xlarge` instance | 12.2 vCPUs | **76.4%** | one instance | 15,490 requests per second |
