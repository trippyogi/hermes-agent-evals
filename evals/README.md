# evals/

Fixture YAML, isolated runners, scorers, and JSON schemas.

```
python -m hermes_eval fetch-sut
python -m hermes_eval freeze
python -m hermes_eval run --fixture <id> --ref <full-sha>
python -m hermes_eval compare --historical --suite core-failures
python -m hermes_eval canary
python -m hermes_eval live --ref <full-sha> --reps 10
python -m hermes_eval analyze
python -m hermes_eval probe-prefix --ref <full-sha>
python -m hermes_eval scan-waste evals/fixtures/_waste_samples --out results/wasted-turn-scan.json --label-sheet
python -m hermes_eval manifest
```

See the repo README for policy and the compare UX.
