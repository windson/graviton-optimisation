#!/usr/bin/env bash
# Records the analysis commands and their output, run on the result files in this
# repository. Anyone with the repository can run the same commands and compare.
#
#   scripts/capture-analysis-evidence.sh
#
# Output: results/evidence/analysis/*.txt, one file per command: the command line, then
# its unedited output. A listing is replaced only if its command succeeded; if one fails,
# its output is printed and the script ends with an error. Nothing here talks to AWS.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/results/evidence/analysis"
mkdir -p "$OUT"
cd "$ROOT"

FAILED=0
record() {
  local file="$OUT/$1.txt" command="$2" status
  echo "\$ $command" > "$file.new"
  bash -o pipefail -c "$command" >> "$file.new" 2>&1
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "failed with status $status, ${file#"$ROOT"/} is left as it was:" >&2
    cat "$file.new" >&2
    rm -f "$file.new"
    FAILED=1
    return 0
  fi
  mv "$file.new" "$file" || { FAILED=1; return 0; }
  echo "wrote ${file#"$ROOT"/} ($(wc -l < "$file") lines)"
}

# Per-operation lines are indented by six spaces; the listings keep the per-window lines.
WINDOWS="grep -vE '^( {6}|$)'"
# For several runs in one listing: the two header lines once (column names, then units),
# then one line per run.
ROWS="awk '/^  (window|unit) / { if (!shown[\$1]++) print; next } /^  steady /'"
# The same with each run's name in front of its line.
NAMED="awk '/^[a-z0-9-]+ \/ / { run = \$3 } /^  window / { if (!shown[\$1]++) printf \"  %-12s%s\n\", \"run\", substr(\$0, 3); next } /^  unit / { if (!shown[\$1]++) printf \"  %-12s%s\n\", \"\", substr(\$0, 3); next } /^  steady / { printf \"  %-12s%s\n\", run, substr(\$0, 3) }'"


# ---- How the load was chosen: the calibration staircase on the Graviton2 baseline ----------
[ -d results/calibration/cal3-cap ] && record calibration "uv run -q analysis/summarize.py results/calibration/cal3-cap | $WINDOWS"

# ---- Each configuration: capacity run, steady runs, ceiling run ------------------------------
for stage in results/[a-c]-*/; do
  stage="${stage%/}"
  letter="$(basename "$stage" | cut -c1)"
  # <letter>2: the configuration deployed a second time; <letter>2p: that deployment with the
  # database writer in the other Availability Zone; <letter>2n: with one web node out of service.
  for prefix in "$letter" "${letter}2" "${letter}2p" "${letter}2n"; do
    [ -d "$stage/$prefix-cap" ] && record "$prefix-capacity" "uv run -q analysis/summarize.py $stage/$prefix-cap | $WINDOWS"
    runs="$(ls -d "$stage/$prefix"-r[1-3] 2>/dev/null | tr '\n' ' ')"
    [ -n "$runs" ] && record "$prefix-steady" "uv run -q analysis/summarize.py $runs| $ROWS"
    ceilings="$(ls -d "$stage/$prefix"-ceiling* 2>/dev/null | tr '\n' ' ')"
    [ -n "$ceilings" ] && record "$prefix-ceiling" "uv run -q analysis/summarize.py $ceilings| $ROWS"
    [ -d "$stage/$prefix-cap" ] && record "$prefix-ceiling-estimate" "uv run -q analysis/ceiling.py estimate $prefix"
  done
done

# ---- The comparison at the baseline's rated load: the runs of each configuration at that rate --
A=results/a-graviton2-baseline
C=results/c-graviton5-right-sized
# The baseline's runs at that rate are the ceiling run that rates it (results/ceiling.json)
# and the runs of the second session.
if [ -d $A/a3-rated-1 ]; then
  rating_run="$(jq -er '.stages["a-graviton2-baseline"].ceiling_run.run' results/ceiling.json)" || rating_run=""
  if [ -n "$rating_run" ] && [ -f "$A/$rating_run/summary.json" ]; then
    runs="$(ls -d $A/$rating_run $A/a3-rated-[1-3] | tr '\n' ' ')"
    record a-rated-load "uv run -q analysis/summarize.py $runs| $NAMED"
  else
    echo "the run that rates the baseline is not named in results/ceiling.json, or its summary is missing:" \
      "results/evidence/analysis/a-rated-load.txt is left as it was" >&2
    FAILED=1
  fi
fi
runs="$(ls -d $C/c2-rated-[1-3] 2>/dev/null | tr '\n' ' ')"
[ -n "$runs" ] && record c-rated-load "uv run -q analysis/summarize.py $runs| $NAMED"

# ---- What was running: processor and runtime as the pods saw them ----------------------------
# Columns: configuration, time of the snapshot, CPU part number, the JVM's SVE setting and
# its number of parallel GC threads (which follows the processors it sees), the Java
# runtime, the Node.js version. Sorted by the time of the snapshot.
record processors \
  "jq -r '[.stage, .at, (.api.cpu | capture(\"CPU part\\\\s*: (?<p>0x[0-9a-f]+)\").p), (.api.jvm_flags | capture(\"(?<f>UseSVE=[0-9])\").f), (.api.jvm_flags | capture(\"(?<f>ParallelGCThreads=[0-9]+)\").f), (.api.java | capture(\"(?<v>Corretto-[0-9.]+)\").v), .web.node] | @tsv' results/*/environment*.json | sort -k2 | column -t"

record baseline-nodes \
  "jq -r '.nodes[] | [.tier, .type, .zone, .kernel, .kubelet] | @tsv' results/a-graviton2-baseline/environment.json | column -t"

# ---- The changes as clients saw them ----------------------------------------------------------
[ -f results/a-graviton2-baseline/ab-events.json ] && \
  record change-upgrade "uv run -q analysis/change_summary.py a-graviton2-baseline ab"
[ -f results/b-graviton5-same-size/bc-events.json ] && \
  record change-right-sizing "uv run -q analysis/change_summary.py b-graviton5-same-size bc"

# Why API pods were reported not ready at a failover: the kubelet's probe failures, from the
# Kubernetes events saved when the pipeline finished (they are kept for an hour).
[ -f results/b-graviton5-same-size/bc-kubernetes-events.json ] && \
  record probe-failures "jq -r '.[] | select(.type == \"Warning\" and .reason == \"Unhealthy\" and (.object | contains(\"storefront-api\")) and (.message | contains(\"deadline\"))) | [.at[11:19], (.object | split(\"-\") | last), (.count | tostring) + \"x\", (.message | sub(\"Get .http://[^ ]+ \"; \"\"))] | @tsv' results/b-graviton5-same-size/bc-kubernetes-events.json"

# ---- Comparison, ceiling and bill ---------------------------------------------------------------
record bill "uv run -q analysis/bom.py"
record comparison "uv run -q analysis/compare.py"
record ceiling "uv run -q analysis/ceiling.py"
record rated-load "uv run -q analysis/rated.py"

exit "$FAILED"
