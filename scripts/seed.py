"""Seed a tenant graph with the synthetic company: python -m scripts.seed [--tenant acme] [--seed 7] [--if-missing]"""

import argparse

from oncall_brain.config import get_settings
from oncall_brain.services.seeding import seed
from oncall_brain.wiring import make_store

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default=get_settings().default_tenant)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--if-missing", action="store_true", help="keep an existing graph (and its learned memory)")
    a = p.parse_args()
    store = make_store()
    if a.if_missing and store.exists(a.tenant):
        print(f"tenant_{a.tenant} exists; keeping it")
    else:
        counts = seed(store, a.tenant, a.seed)
        print(f"seeded tenant_{a.tenant} (+ pristine copy):", ", ".join(f"{k}={v}" for k, v in counts.items()))
