"""Seed a tenant graph with the synthetic company: python -m scripts.seed --tenant acme [--seed 7]"""

import argparse

from oncall_brain.services.seeding import seed
from oncall_brain.wiring import make_store

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default="acme")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    counts = seed(make_store(), a.tenant, a.seed)
    print(f"seeded tenant_{a.tenant} (+ pristine copy):", ", ".join(f"{k}={v}" for k, v in counts.items()))
