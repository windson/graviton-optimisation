The billed write I/O of the study's Aurora cluster as CloudWatch reported it, saved at intervals to see
whether a datapoint is revised after it is published (docs/02-experiment-protocol.md, deviations 15 and 17).

Each file is the output of

  aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name VolumeWriteIOPs \
      --dimensions Name=DBClusterIdentifier,Value=graviton-uplift \
      --start-time 2026-11-23T12:00:00Z --end-time 2026-11-24T06:00:00Z --period 300 --statistics Sum \
      --query 'sort_by(Datapoints,&Timestamp)[].[Timestamp,Sum]' --output text

taken at the UTC time in its name (billed-2256.txt at 22:56 on 23 Nov, billed-0352.txt at 03:52 on 24 Nov).
The value is the count per five minutes; divide by 300 for a rate per second. Runs of equal values are
the blocks that analysis/usage.py works with.
