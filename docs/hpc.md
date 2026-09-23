# HPC / workflow engines

On an HPC login node, the right shape is a short-lived process per check: poll once, branch
on the exit code, and never hold an open connection. `atb status <molid>` is built for this —
Nextflow, Snakemake or a cron loop can call it directly.

```bash
# submit once (a re-run adopts the existing entry: exit 0, "duplicate": true)
molid=$(atb submit lig.pdb --charge 0 --ref LIG-042 \
  | python -c 'import json,sys; print(json.load(sys.stdin)["molid"])')

# each time the workflow re-evaluates the rule:
atb status "$molid"
case $? in
  0) atb download "$molid" itp_aa pdb_aa_opt -o "lig_$molid/" ;;
  4) echo "still running; check again later" ;;
  5) echo "failed or rejected"; exit 1 ;;
  3) echo "rate-limited; back off" ;;
  *) echo "error"; exit 1 ;;
esac
```

`atb status` costs no quota. `atb submit --wait` blocks in the process instead — useful
interactively, but not this idiom.

## Exit codes

| code | meaning |
|---|---|
| 0 | done — for `status`, the molecule is `finished` or `capped` |
| 1 | error (anything not listed below) |
| 2 | usage — bad arguments, or no API key configured |
| 3 | rate-limited — see `retry_after` in the error body |
| 4 | still running — `status` not terminal, or a `--wait`/download timeout |
| 5 | failed or rejected — the molecule, its job, or its chemistry |

Output is JSON on stdout by default (`--table` for humans); errors are JSON on stderr.
