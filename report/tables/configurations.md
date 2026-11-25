|  | **A: Graviton2 baseline** | **B: Graviton5, same size** | **C: Graviton5, right-sized** |
|---|---:|---:|---:|
| Web nodes | 2 x `c6g.4xlarge`, 32 vCPUs in all | 2 x `c9g.4xlarge`, 32 vCPUs in all | 2 x `c9g.2xlarge`, 16 vCPUs in all |
| Web pods (0.95 vCPU requested each) | 32 pods | 32 pods | 16 pods |
| API nodes | 3 x `m6g.xlarge`, 12 vCPUs in all | 3 x `m9g.xlarge`, 12 vCPUs in all | 3 x `m9g.large`, 6 vCPUs in all |
| API pods (CPU limit 1.75 vCPUs each) | 6 pods, 10.5 vCPUs of CPU limits | 6 pods, 10.5 vCPUs of CPU limits | 3 pods, 5.25 vCPUs of CPU limits |
| Aurora MySQL writer and reader | 2 x `db.r6g.8xlarge`, 32 vCPUs and 256 GiB each | 2 x `db.r9g.8xlarge`, 32 vCPUs and 256 GiB each | 2 x `db.r9g.4xlarge`, 16 vCPUs and 128 GiB each |
| System nodes | 2 x `m6g.large`, 4 vCPUs in all | 2 x `m9g.large`, 4 vCPUs in all | 2 x `m9g.large`, 4 vCPUs in all |
| vCPUs of the web, API and database tiers, counting the reader | 108 vCPUs | 108 vCPUs | 54 vCPUs |
