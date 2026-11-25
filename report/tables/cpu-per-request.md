| Tier | Request rate and runs | A, Graviton2: CPU time per request | B, Graviton5: CPU time per request | A divided by B | Less CPU time per request on Graviton5 |
|---|---|---:|---:|---:|---:|
| Web tier: React pages rendered on Node.js 24 | 8,000 requests per second: three 590-second runs of each | 1.974 ms | 0.891 ms | 2.22 | 55% |
|  | A at 11,800 requests per second (3 runs of 590 seconds), B at 12,000 requests per second (1 step of 110 seconds) | 1.985 ms | 0.883 ms | 2.25 | 56% |
| API tier: Java 21, Spring Boot | 8,000 requests per second: three 590-second runs of each | 0.676 ms | 0.241 ms | 2.80 | 64% |
|  | A at 11,800 requests per second (3 runs of 590 seconds), B at 12,000 requests per second (1 step of 110 seconds) | 0.700 ms | 0.253 ms | 2.76 | 64% |
| Database: Aurora MySQL 3.10 writer | 8,000 requests per second: three 590-second runs of each | 2.269 ms | 0.814 ms | 2.79 | 64% |
|  | A at 11,800 requests per second (3 runs of 590 seconds), B at 12,000 requests per second (1 step of 110 seconds) | 2.151 ms | 0.818 ms | 2.63 | 62% |
