"""Does an outside model pick the right tool from the MCP tool list alone?

Gives the configured model (LLM_PROVIDER=anthropic + a key in .env) exactly what an MCP client sees, the tool names,
descriptions and schemas from the catalogue, plus the server instructions, and asks it to handle plain requests with
one tool call each. No playbook, no hints. Prints a table and rewrites docs/MCP_PICK.md.

    python -m scripts.mcp_pick
"""

import sys
import time
from pathlib import Path

import httpx

from oncall_brain.config import get_settings
from oncall_brain.mcp_server import INSTRUCTIONS, catalogue

DOC = Path(__file__).parents[1] / "docs" / "MCP_PICK.md"
URL = "https://api.anthropic.com/v1/messages"

# (what a person would type, the tools that count as right)
REQUESTS = [
    ("checkout is slow and alert:checkout-latency just fired. Find out why.", {"respond_to_alert"}),
    ("who owns kafka?", {"ask", "who_knows"}),
    ("why was legacy-billing retired from the checkout path?", {"ask"}),
    ("how do I roll back a bad deploy on cart?", {"ask"}),
    ("which services would be hurt if payments-gw went down?", {"blast_radius"}),
    ("does checkout depend on kafka, directly or through something else?", {"dependency_path"}),
    ("who knows payments-gw best? I need someone to review a change there.", {"who_knows"}),
    ("where did chg:pgw-pool-1 come from, which ticket and who made it?", {"change_story"}),
    ("we just deployed cart v3.2.0 (new checkout button), record that.", {"record_change"}),
    ("inc:checkout-latency is confirmed: chg:pgw-pool-1 caused it and reverting it fixed things.",
     {"resolve_incident"}),
    ("show me every service and which team owns it.", {"service_map"}),
    ("monitoring says payments p99 latency is 4s since 10:05, note that down.", {"record_anomaly"}),
    ("a new alert: refunds returns 5xx above 1%, on refunds. Register it.", {"raise_alert"}),
    ("what did the agents do on inc:checkout-latency so far?", {"incident_board"}),
    ("I'm person:hana-costa. What did I ask you about payments-gw earlier?", {"my_questions", "ask"}),
]


def pick(model: str, key: str, tools: list[dict], request: str) -> tuple[str | None, str]:
    body = {"model": model, "max_tokens": 600, "system": INSTRUCTIONS + "\nThe company (tenant) is 'acme'. Answer the "
            "request by calling exactly one tool.", "tools": tools,
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
            "messages": [{"role": "user", "content": request}]}
    r = httpx.post(URL, json=body, headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=60)
    r.raise_for_status()
    msg = r.json()
    use = next((b for b in msg["content"] if b["type"] == "tool_use"), None)
    text = " ".join(b["text"] for b in msg["content"] if b["type"] == "text").strip()
    return (use["name"] if use else None), (str(use["input"]) if use else text)[:120]


def main() -> int:
    s = get_settings()
    key = s.api_key()
    if s.llm_provider != "anthropic" or not key:
        print("needs LLM_PROVIDER=anthropic and a key in .env", file=sys.stderr)
        return 2
    model = s.llm_model or "claude-sonnet-5-5"
    tools = [{"name": t.name, "description": t.description,
              "input_schema": getattr(t, "input_schema", None) or t.inputSchema}
             for t, _ in catalogue().values()]
    rows, right = [], 0
    for request, ok in REQUESTS:
        picked, args = pick(model, key, tools, request)
        hit = picked in ok
        right += hit
        rows.append((request, picked or "(no tool)", "yes" if hit else f"no (wanted {' or '.join(sorted(ok))})", args))
        print(f"{'ok ' if hit else 'MISS'} {picked or '(no tool)':<20} <- {request}")
    lines = [f"# Tool pick test: {right}/{len(REQUESTS)} on {model}", "",
             f"Run {time.strftime('%Y-%m-%d %H:%M')} by `python -m scripts.mcp_pick`. The model sees only what an MCP "
             "client sees: the server instructions and the tool list (names, descriptions, schemas) from "
             "`oncall_brain.mcp_server.catalogue()`. No playbook, no examples. One request, one tool call.", "",
             "| request | picked | right? | arguments |", "|---|---|---|---|"]
    lines += [f"| {r} | `{p}` | {ok} | `{a.replace('|', '/')}` |" for r, p, ok, a in rows]
    DOC.write_text("\n".join(lines) + "\n")
    print(f"\n{right}/{len(REQUESTS)} right; wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
