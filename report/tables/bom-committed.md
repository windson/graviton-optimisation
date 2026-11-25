| Line item, in US dollars per month | A: Graviton2 baseline | B: Graviton5, same size | C: Graviton5, right-sized | Quantity and unit price |
|---|---:|---:|---:|---|
| **Compute and database** |  |  |  |  |
| Web tier nodes | 2 x c6g.4xlarge<br>$500 | 2 x c9g.4xlarge<br>$669 | 2 x c9g.2xlarge<br>$335 | 730 hours; EC2 Instance Savings Plan, 1 year, no upfront |
| API tier nodes | 3 x m6g.xlarge<br>$212 | 3 x m9g.xlarge<br>$283 | 3 x m9g.large<br>$142 | 730 hours; EC2 Instance Savings Plan, 1 year, no upfront |
| System nodes | 2 x m6g.large<br>$71 | 2 x m9g.large<br>$94 | 2 x m9g.large<br>$94 | 730 hours; EC2 Instance Savings Plan, 1 year, no upfront |
| Aurora MySQL writer and reader | 2 x db.r6g.8xlarge<br>$3,973<br>Reserved Instance | 2 x db.r9g.8xlarge<br>$6,480<br>On-Demand: no one-year rate was returned | 2 x db.r9g.4xlarge<br>$3,240<br>On-Demand: no one-year rate was returned | 730 hours; one year, no upfront, where AWS offered it |
| *Subtotal: compute and database* | *$4,755* | *$7,527* | *$3,811* |  |
| Rest of the stack: the same lines and amounts as in the On-Demand bill | $5,046 | $5,078 | $5,101 | Not covered by a commitment |
| **Total per month** | **$9,801** | **$12,605** | **$8,912** |  |
| Difference from A |  | +28.6% | -9.1% |  |
