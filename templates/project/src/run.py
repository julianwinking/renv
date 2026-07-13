"""Example experiment entrypoint honoring the reref runner contract.

Reads REREF_RUN_DIR + REREF_PARAMS from the environment; writes metrics.json
(a flat {name: value} map) and any artifact files into REREF_RUN_DIR.
Run with:  reref exp run {{slug}} 001-baseline --entrypoint src/run.py --param k=8
"""
import json, os

run_dir = os.environ["REREF_RUN_DIR"]
params = json.loads(os.environ["REREF_PARAMS"])

# ... your experiment here ...
metrics = {"example_metric": params.get("k", 0) / 10}

with open(os.path.join(run_dir, "metrics.json"), "w") as f:
    json.dump(metrics, f)
