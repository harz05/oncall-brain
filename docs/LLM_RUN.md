# A real LLM choosing the tools

`make demo` and `python -m scripts.llm_run` use whatever planner `.env` selects. With `LLM_PROVIDER=anthropic` (or any
other provider) the model reads the incident board from the graph before every decision and picks the next tool
itself; the deterministic planner only steps in when a reply is unusable, and the trace says so ("LLM fallback: ...").

`scripts/llm_run.py` plays the whole story (act 1, the human's confirm, act 2 with memory, act 2 on a reset graph
without it, act 3) with the model, then with the deterministic planner, and writes every decision (role, tool, args,
who decided, reason, latency) to `docs/llm_runs/<model>.json`.

## Results (2026-10-16)

| planner | decisions | chosen by the model | fell back | right cause | ms per decision: mean / p50 / p95 |
|---|---|---|---|---|---|
| Claude Opus 5.5 (`claude-opus-5-5`) | 60 | 60 | 0 | 4 / 4 | 2699 / 2317 / 4988 |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | 60 | 60 | 0 | 4 / 4 | 1859 / 1722 / 2530 |
| qwen2.5:3b on local Ollama, first prompt | 53 | 19 | 34 | 3 / 4 | 776 / 674 / 1505 |

Both Claude models took the same path as the deterministic planner: in act 1 they checked all five suspects and ruled
out four decoys; in act 2 memory solved it in 3 investigator calls and 1 check; in act 3 triage correlated the alert
storm and `conclude` kept the postgres-orders change that explains all three alerts. They differed from the planner
only in the order they checked suspects (act 2 without memory and act 3 found the culprit one check later).

A small local model is not enough: qwen2.5:3b replied without a usable tool call in most turns, so the planner made
64% of its decisions.

## What the first Claude run taught us

The first Opus run, with the original prompt, got act 3 wrong. The prompt said "recall first" and never mentioned
`correlate_alerts`, so Claude skipped the storm and blamed the subscriptions deploy, exactly like the "without
correlation" ablation in `make demo`. It also stopped checking after the first supported suspect (the prompt said
"until one is supported"), so act 1's decoys were never ruled out. The role playbook in the prompt
(`adapters/llm/openai_compat.py`, `SYSTEM`) now states the same rules the deterministic planner follows; the model
still makes every choice from the board. That run is not kept; rerun the script to reproduce the current numbers.

## Reproduce

```bash
cp .env.example .env    # set LLM_PROVIDER=anthropic and LLM_API_KEY (or ANTHROPIC_API_KEY in the environment)
make db
python -m scripts.llm_run                                  # model from .env (default claude-sonnet-5-5)
LLM_MODEL=claude-opus-5-5 python -m scripts.llm_run        # override the model
make demo                                                  # the scripted demo, now with the model deciding
```
