"""Example experiment entrypoint honoring the renv runner contract.

Reads RENV_RUN_DIR + RENV_PARAMS from the environment; writes metrics.json
(a flat {name: value} map) and any artifact files into RENV_RUN_DIR.
Run with:  renv exp run {{slug}} 001-baseline --entrypoint src/run.py --param k=8

On a cluster: run this there with RENV_RUN_DIR set to a scratch dir, then
`renv exp ingest {{slug}} <exp> --dir <copied-dir>` (or --metrics + --remote
if nothing comes home). Optionally write provenance.json (git_sha, params,
seed) next to metrics.json to earn the remote-verified grade.
"""
import json, os

run_dir = os.environ["RENV_RUN_DIR"]
params = json.loads(os.environ["RENV_PARAMS"])

_tb = None
def track(step, **values):
    """TELESCOPE, not ledger: per-step curves -> TensorBoard events, if the
    writer is importable (ships with torch). Fail-open: never breaks the run;
    the only citable numbers are the ones in metrics.json."""
    global _tb
    if _tb is False:
        return
    try:
        if _tb is None:
            from torch.utils.tensorboard import SummaryWriter
            _tb = SummaryWriter(os.path.join(run_dir, "tb"))
        for name, value in values.items():
            _tb.add_scalar(name, value, step)
    except Exception:
        _tb = False

# ... your experiment here ...
# for epoch in range(epochs):
#     loss = train_step(...)
#     track(epoch, loss=loss)
metrics = {"example_metric": params.get("k", 0) / 10}

with open(os.path.join(run_dir, "metrics.json"), "w") as f:
    json.dump(metrics, f)
