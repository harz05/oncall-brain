"""Seed a tenant graph with the synthetic company: python -m scripts.seed [--tenant acme] [--seed 7] [--if-missing]
python -m scripts.seed --reset restores the tenant's pristine copy instead: run it from cron on a public deployment, so
whatever visitors wrote (incidents, docs, sessions) neither piles up nor stays on show."""

import argparse

from oncall_brain.config import get_settings
from oncall_brain.services.seeding import reset, seed
from oncall_brain.wiring import make_store

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default=get_settings().default_tenant)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--if-missing", action="store_true", help="keep an existing graph (and its learned memory)")
    p.add_argument("--reset", action="store_true", help="restore the pristine copy (what the UI's reset does)")
    a = p.parse_args()
    store = make_store()
    if a.reset:
        print(f"tenant_{a.tenant}: {reset(store, a.tenant)}")
    elif a.if_missing and store.exists(a.tenant):
        print(f"tenant_{a.tenant} exists; keeping it")
    else:
        counts = seed(store, a.tenant, a.seed)
        print(f"seeded tenant_{a.tenant} (+ pristine copy):", ", ".join(f"{k}={v}" for k, v in counts.items()))
