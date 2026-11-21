"""Choose the policy on the tuning speakers only, then freeze it to data/policy.json.

Rule, fixed in advance: among configurations whose accepted actions on the tuning split reject
"risk > alpha" at level delta (binomial test), take the one that accepts the most actions; ties go to
the stricter configuration. The choice is in-sample, so it certifies nothing by itself: the certificate
is the single Clopper-Pearson bound that run_eval.py reports on the test speakers.
"""

from __future__ import annotations

import itertools
import json
import subprocess

from pramaan.gate import binom_cdf
from pramaan.types import Policy

from .common import ALPHA, DELTA, POLICY, ROOT, guard, tuning_rows

GRID = {
    # Never one: acting on a single recogniser family is what the guard exists to prevent, and on English
    # turns (no acoustic check) it would mean acting on one vendor alone.
    "min_families": (3, 2),
    "witness_llr_min": (0.0, 3.0, 8.0, 20.0),
    "accept_threshold": (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3),
    "language_aware": (False, True),
}


def main() -> None:
    tune = tuning_rows()
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    best: tuple[int, Policy, int] | None = None
    print(f"tuning on {len(tune)} actions from {len({r.speaker for r in tune})} speakers")
    for combo in itertools.product(*GRID.values()):  # strict to permissive
        policy = Policy(**dict(zip(GRID, combo, strict=True)))
        outs = [guard(r, policy) for r in tune]
        n = sum(o.executed for o in outs)
        k = sum(o.executed and o.wrong for o in outs)
        p = binom_cdf(k, n, ALPHA) if n else 1.0
        print(f"  {dict(zip(GRID, combo, strict=True))}  accepted {n}  wrong {k}  p={p:.4f}")
        if p <= DELTA and (best is None or n > best[0]):
            best = (n, policy, k)
    if best is None:
        raise SystemExit("no configuration certifies on the tuning split; keeping the previous policy")
    n, policy, k = best
    policy = policy.model_copy(update={"code_commit": commit})
    POLICY.write_text(json.dumps(policy.model_dump(), indent=1, sort_keys=True) + "\n")
    print(f"\nfrozen policy {policy.hash}: accepted {n} of {len(tune)}, wrong {k}\n{POLICY}")


if __name__ == "__main__":
    main()
