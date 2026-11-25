# Research notes

Collected 22 Nov 2026, before any benchmark was run. Quotes are verbatim from the linked page. "Account check" means the fact was read from the AWS account with the AWS CLI rather than from documentation.

## 1. What AWS claims for each Graviton generation

| Step | Claim (verbatim) | Source | Date |
|---|---|---|---|
| Graviton2 vs x86 | "Amazon EC2 M6g instances deliver up to 40% better price performance over the current generation x86-based Amazon EC2 M5 instances" | [What's New](https://aws.amazon.com/about-aws/whats-new/2020/05/amazon-ec2-m6g-instances-powered-by-aws-graviton2-processors-generally-available/) | 11 May 2020 |
| Graviton3 vs Graviton2 | "Graviton3 processors, deliver up to 25 percent higher performance, up to 2x higher floating-point performance, and 50 percent faster memory access based on leading-edge DDR5 memory technology compared with Graviton2 processors." | [AWS News Blog](https://aws.amazon.com/blogs/aws/new-amazon-ec2-c7g-instances-powered-by-aws-graviton3-processors/) | 23 May 2022 |
| Graviton4 vs Graviton3 | "AWS Graviton4 processors are up to 30% faster for web applications, 40% faster for databases, and 45% faster for large Java applications than AWS Graviton3 processors." | [AWS News Blog](https://aws.amazon.com/blogs/aws/aws-graviton4-based-amazon-ec2-r8g-instances-best-price-performance-in-amazon-ec2/) | 9 Jul 2024 |
| Graviton5 vs Graviton4 | "Graviton5 offers up to 25% better compute performance compared to Graviton4-based instances, with up to 35% faster performance for web applications, up to 35% for machine learning inference, and up to 30% for databases." | [AWS News Blog](https://aws.amazon.com/blogs/aws/now-available-amazon-ec2-m9g-and-m9gd-instances-powered-by-new-aws-graviton5-processors/) | 10 Jun 2026 |
| C9g vs C8g | "C9g instances are compute-optimized and deliver up to 25% higher performance per vCPU compared to previous-generation C8g instances." | [AWS News Blog](https://aws.amazon.com/blogs/aws/amazon-ec2-c9g-and-c9gd-instances-powered-by-aws-graviton5-processors-are-now-available/) | 30 Jun 2026 |
| R9g vs R8g | "R9g and R9gd instances deliver up to 25% better compute performance compared to AWS Graviton4-based R8g and R8gd instances. They are up to 30% faster for databases, up to 35% faster for web applications, and up to 35% faster for machine learning." | [What's New](https://aws.amazon.com/about-aws/whats-new/2026/08/amazon-ec2-r9g-and-r9gd-memory-optimized-instances-are-now-available/) | 31 Aug 2026 |

Aurora:

| Step | Claim (verbatim) | Source | Date |
|---|---|---|---|
| R6g vs R5 | "Graviton2 instances provide up to 20% performance improvement and up to 35% price/performance improvement for Aurora depending on database size." | [What's New](https://aws.amazon.com/about-aws/whats-new/2021/03/achieve-up-to-35-percent-better-price-performance-with-amazon-aurora-using-new-graviton2-instances/) | 12 Mar 2021 |
| R7g vs R6g | "Graviton3 instances provide up to 30% performance improvement and up to 20% price-performance improvement over Graviton2 instances for Aurora depending on database engine, version, and workload." | [What's New](https://aws.amazon.com/about-aws/whats-new/2023/05/amazon-aurora-mysql-postgresql-graviton3-based-r7g-instance-family/) | 11 May 2023 |
| R8g vs R7g | "Graviton4-based instances provide up to a 40% performance improvement and up to 29% price/performance improvement for on-demand pricing over Graviton3-based instances of equivalent sizes on Amazon Aurora databases, depending on database engine, version, and workload." | [What's New](https://aws.amazon.com/about-aws/whats-new/2024/11/amazon-aurora-graviton4-based-r8g-database-instances/) | 26 Nov 2024 |
| R9g vs R8g | "Graviton5-based R9g instances provide up to a 30% performance improvement and up to a 22% price-performance improvement for on-demand pricing over Graviton4-based instances of equivalent sizes on Amazon Aurora, depending on database engine, version, and workload." | [What's New](https://aws.amazon.com/about-aws/whats-new/2026/11/amazon-aurora-rds-postgresql-mysql-mariadb-r9g-instances/) | 12 Nov 2026 |

Reading these claims:

- Every figure is an "up to" figure against the generation immediately before it. AWS publishes no Graviton5-versus-Graviton2 figure.
- Multiplying the three compute claims gives 1.25 x 1.30 x 1.25 = 2.03. This is an upper bound built from best cases, not a prediction. The study measures the real ratio for this workload. *Added on 24 Nov 2026:* "upper bound" says too much. The products of the claims range from 2.03 to 2.45 for Amazon EC2, depending on which claims are combined, and the three Aurora claims multiply to 2.37. The study measured something else, CPU time per request: ratios of 2.22 (web tier), 2.80 (API tier) and 2.79 (database writer).
- No announcement states a price reduction for Graviton5. The claims are performance and price-performance.

## 2. Hardware by generation

From the [AWS Graviton Technical Guide](https://github.com/aws/aws-graviton-getting-started/blob/main/README.md) processor table unless noted.

| | Graviton2 | Graviton3 | Graviton4 | Graviton5 |
|---|---|---|---|---|
| Core | Neoverse-N1 | Neoverse-V1 | Neoverse-V2 | Neoverse-V3 |
| Architecture | ARMv8.2-a | ARMv8.4-a | Armv9.0-a | Armv9.2-a |
| Frequency | 2500 MHz | 2600 MHz | 2800 MHz | 3300 MHz |
| Cores per chip | 64 | 64 | 96 | 192 |
| L2 per core | 1 MB | 1 MB | 2 MB | 2 MB |
| Shared last-level cache | 32 MB | 32 MB | 36 MB | 48 MB per NUMA node up to 16xlarge |
| Memory | DDR4 | DDR5 | DDR5-5600 | DDR5-8800 |
| First GA | May 2020 | May 2022 | Jul 2024 | Jun 2026 |

Other Graviton5 facts:

- "Graviton5 doubles the number of cores from Graviton4, from 96 to 192, and it supports DDR5-8800 memory and the latest PCIe gen6 interconnects." ([Amazon Science](https://www.amazon.science/blog/graviton5s-improved-design-increases-speed-and-energy-efficiency-beyond-moores-law), 10 Jun 2026)
- "the 192 cores in Graviton5 are split across four chiplets, with each chiplet containing DRAM controllers, PCIe controllers, and 48 cores", which reduces "memory latency for VMs that are 48 cores or smaller" (same source). Every size used in this study is 32 vCPU or smaller.
- "Every vCPU on a Graviton processor maps to a physical core, and there is no Simultaneous Multi-Threading (SMT)." ([transition guide](https://github.com/aws/aws-graviton-getting-started/blob/main/transition-guide.md))

## 3. Guidance that shaped the method

From the AWS Graviton Technical Guide:

- "we recommend fully loading both instance types to determine the maximum sustainable load before the latency or error rate exceeds acceptable bounds" (transition-guide.md). This is why each configuration gets a capacity run and not only a steady-state run.
- "Testing at low levels of load can lead to misleading results. The most realistic test results are usually achieved when testing close to breaking latency." (java.md)
- "Breaking latency is the point when the machine can no longer serve more throughput and maintain acceptable response times to the load-generator and incrementally more throughput induces an exponential rise in latency." (perfrunbook/defining_your_benchmark.md)
- Java: "AWS recommends at least JDK11, but ideally JDK17 or newer." (java.md). The API uses Corretto 21 with default JVM flags in all configurations.
- Node.js: "Node.JS is fundamentally single threaded and so on an instance with more than one vCPU (which is most of them!), the node process will leave the CPU underutilized." (nodejs.md). The web tier therefore runs one single-vCPU pod per core.
- Generations: "Graviton5 does not support Amazon Linux 2 kernel 4.14.x" (os.md). Nodes use Amazon Linux 2023.

From AWS on same-architecture upgrades: "no code changes are required for most applications. Select the equivalent R9g instance size and your application runs with better performance." ([R9g blog](https://aws.amazon.com/blogs/aws/amazon-ec2-r9g-and-r9gd-instances-powered-by-aws-graviton5-processors-are-now-generally-available/), 31 Aug 2026)

## 4. Independent measurements

| Who | Step | Result (verbatim) | Source |
|---|---|---|---|
| Honeycomb | Graviton4 to 5 | "Over 60 days running both generations side by side, every measured service used 11-26% less CPU on Graviton5 for identical work. Ingest P99 latency dropped 28%" | [Honeycomb](https://www.honeycomb.io/blog/graviton5-honeycomb-per-service-results-m8g-m9g-migration), 10 Jun 2026 |
| Phoronix | Graviton4 to 5 | "there was 30% geo mean uplift from Graviton4 to Graviton5 across all of these independent benchmarks carried out using m8g.4xlarge to m9g.4xlarge" | [Phoronix](https://www.phoronix.com/review/aws-graviton5/8), 9 Jul 2026 |
| Phoronix | Graviton3 to 4 | "Going from Graviton3 to Graviton4 clocked in at 30% for the geo mean improvement" | [Phoronix](https://www.phoronix.com/review/aws-graviton4-benchmarks/7), 12 Jul 2024 |
| Honeycomb | Graviton2 to 3 | "were able to operate at similar latency and throughput with 10% higher CPU target utilization set on the ASG (leading to 30% fewer instances being provisioned)" | [Honeycomb](https://www.honeycomb.io/blog/present-future-arm-aws-graviton-honeycomb), 23 May 2022 |

No published measurement was found that compares Graviton5 directly with Graviton2 for a Java, Node.js, or MySQL workload. That gap is what this study fills.

## 5. Availability (account check, us-west-2)

- EC2: `c9g`, `m9g`, `r9g`, `t9g` and their `d` variants are offered in us-west-2, us-east-1, and us-east-2. eu-west-1 has no `r9g`.
- Every instance type considered is offered in all four us-west-2 Availability Zones.
- Aurora MySQL: `db.r9g` is orderable for 3.08.0 through 3.14.0 and 8.4.7 through 8.4.10. `db.r6g` is orderable for all of those. Chosen engine version: 3.10.x (long-term support), the same for every configuration.
- Amazon EKS: Kubernetes 1.37 is the default version.

## 6. Prices (account check, AWS Price List API, us-west-2, On-Demand, Linux)

EC2, USD per hour:

| Size | Graviton2 | Graviton3 | Graviton4 | Graviton5 | Graviton5 vs Graviton2 |
|---|---|---|---|---|---|
| c*.4xlarge | 0.5440 | 0.5800 | 0.6381 | 0.6955 | +27.9% |
| m*.8xlarge | 1.2320 | 1.3056 | 1.4362 | 1.5654 | +27.1% |
| m*.large | 0.0770 | n/a | n/a | 0.0978 | +27.1% |

Aurora MySQL, Standard storage configuration, USD per hour:

| Class | Graviton2 | Graviton3 | Graviton4 | Graviton5 | Graviton5 vs Graviton2 |
|---|---|---|---|---|---|
| db.r*.8xlarge | 4.1530 | 4.4220 | 4.4160 | 4.4384 | +6.9% |
| db.r*.4xlarge | 2.0760 | n/a | n/a | 2.2192 | +6.9% |

What this means before any test is run:

- A like-for-like upgrade raises the compute bill: about 27% on EC2 and about 7% on Aurora.
- Halving the size after upgrading lowers it: `m9g.4xlarge` is 36.5% cheaper than `m6g.8xlarge`, `c9g.2xlarge` is 36.1% cheaper than `c6g.4xlarge`, and `db.r9g.4xlarge` is 46.6% cheaper than `db.r6g.8xlarge`.
- So the cost outcome depends entirely on whether the smaller Graviton5 configuration holds the baseline's performance. Break-even is a per-vCPU capacity gain of 1.27x on EC2 and 1.07x on Aurora.

The full price snapshot used in the report is regenerated by `analysis/pricing.py` and stored under `results/pricing/`.

Added on 24 Nov 2026:

- Aurora storage configurations: "Aurora I/O-Optimized can reduce your costs when your I/O spending is 25% or more of your total Aurora database spending." ([Amazon Aurora User Guide, storage](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Overview.StorageReliability.html), read 24 Nov 2026).
- vCPUs: "Every vCPU on a Graviton processor maps to a physical core, and there is no Simultaneous Multi-Threading (SMT)." (AWS Graviton Technical Guide, [transition-guide.md](https://github.com/aws/aws-graviton-getting-started/blob/main/transition-guide.md), read 24 Nov 2026).

## 7. Load generator: Distributed Load Testing on AWS v4.3.4

Read from the deployed stack and from the solution source at tag v4.3.4.

- API: Amazon API Gateway with IAM authorization. `POST /scenarios` creates and starts a run. Scripts are uploaded first to `public/test-scenarios/k6/<testId>.js` in the scenarios bucket.
- Standard mode runs k6 through Taurus, which passes `--stage` or `--vus` and therefore overrides any arrival-rate scenario in the script. It also averages per-task percentiles without weighting.
- Native mode (`nativeRunMode`) runs `k6 run` with the script's own options and merges per-task latency histograms (0.5% relative bucket error). Each task runs an independent copy of the script, so the total arrival rate is the per-task rate times the task count.
- Each task writes `result.json` with summary, per-label statistics, and the full histogram. The analysis in this repository merges those histograms itself.
- Load generator tasks are AWS Fargate, 2 vCPU and 4 GiB each, x86-64.
- This study uses native mode only.

## 8. Tooling assessment

| Tool | Finding | Decision |
|---|---|---|
| Agent Toolkit for AWS | Installable with `aws agent-toolkit add-skill`; 130 skills | Installed the EKS, Aurora MySQL, CloudFormation, deployment, compute, cost, and observability skills |
| AWS Graviton skills | Four skills: three x86-to-Graviton migrations and a savings assessment | Installed the Java migration and savings assessment skills for reference. Neither covers generation-to-generation right-sizing |
| AWS CodeDeploy | Compute platforms are EC2/on-premises, Lambda, and ECS | Replaced by the CodePipeline Amazon EKS deploy action |
| CodePipeline EKS action | Category Deploy, provider EKS, V2 pipelines, Helm or kubectl | Used for application deployment |

## 9. Competitor context

Stated neutrally, vendor claims only:

- Azure Cobalt 200: "deliver up to 50% performance improvement over Cobalt 100" ([Microsoft](https://techcommunity.microsoft.com/blog/azureinfrastructureblog/announcing-cobalt-200-azure%E2%80%99s-next-cloud-native-cpu/4469807), 18 Nov 2025).
- Google Axion N4A: "up to 2x better price-performance and 80% better performance-per-watt than comparable current-generation x86-based VMs" ([Google Cloud](https://cloud.google.com/blog/products/compute/axion-based-n4a-vms-now-in-preview), 27 Jan 2026).

These are not benchmarked here. The study compares AWS with AWS, which is the decision a team on Graviton2 faces first.
