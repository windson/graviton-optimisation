| Tier | CPU the tier may use | CPU in use at 11,800 requests per second | CPU utilization: in use, as a share of what the tier may use | CPU utilization of the busiest node, measured the same way | Request rate at which this tier would be at 80% CPU utilization |
|---|---|---:|---:|---:|---:|
| Web tier | 32 vCPUs: 2 web nodes of 16 vCPUs | 22.9 vCPUs | **71.6%** | 71.6% | 13,180 requests per second |
| API tier | 10.5 vCPUs: the CPU limits of 6 API pods, 1.75 vCPUs each | 8.3 vCPUs | **79.4%** | 87.8% | 11,890 requests per second |
| Database writer | 32 vCPUs: one `db.r6g.8xlarge` instance | 25.2 vCPUs | **78.8%** | one instance | 11,975 requests per second |
