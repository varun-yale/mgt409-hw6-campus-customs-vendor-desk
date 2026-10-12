"""Problem 4: run the vendor desk agent with and without prompt caching.

    python cache_test.py --setup cached              # all 12 practice docs
    python cache_test.py --setup nocache             # all 12 practice docs
    python cache_test.py --setup nocache --phase pretest --docs data/practice_docs/p01_bluehen_quote.html

Both setups use the same agent, prompt, handbook, tools, model (gpt-6-luna via
Portkey) and output type. The only difference:

  cached   the instructions are identical on every request (prompt + handbook),
           so the API can reuse the cached prefix.
  nocache  a random "Request ID" line goes at the very top of the instructions,
           regenerated for every model request, so no two prefixes match and
           nothing can be read from cache. The API has no switch to turn
           caching off (prompt_cache_retention only accepts in_memory or 24h).

Every model request is recorded in output/cache_test.json with the API's own
token counts (read from the raw HTTP response) and the billed cost from
data/prices.json. Runs are also appended, labeled, to output/usage_log.json and
output/audit_trail.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

import agent
import tools

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "output" / "cache_test.json"
KEY = ROOT / "data" / "practice_key.json"
PRACTICE = sorted((ROOT / "data" / "practice_docs").iterdir())


def _load() -> dict:
    if RESULTS.exists() and RESULTS.read_text().strip():
        return json.loads(RESULTS.read_text())
    return {
        "description": "Problem 4 cache test. Every model request from both setups, with the API's "
                       "own token counts and the billed cost from data/prices.json. Only "
                       "phase='comparison' entries go into the totals.",
        "runs": [],
        "requests": [],
    }


def _save(data: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(data, indent=2) + "\n")


def make_instructions(setup: str):
    static = agent.build_instructions(agent.BASELINE)   # original Problem 3 prompt
    if setup == "cached":
        return static

    def per_request() -> str:
        # Called by PydanticAI for every model request, so every prefix is new.
        return f"Request ID: {uuid.uuid4().hex}\n\n{static}"

    return per_request


def compare_with_key(output: dict | None, key: dict | None) -> dict | None:
    if output is None or key is None:
        return None
    pairs = {
        "vendor_name": key["vendor"], "sku": key["sku"], "unit_price": key["unit_price"],
        "lead_time_days": key["lead_time_days"], "min_order_units": key["min_order"],
        "decision": key["decision"],
    }
    fields = {f: output.get(f) == want for f, want in pairs.items()}
    return {"fields": fields, "all_match": all(fields.values())}


def run_doc(setup: str, phase: str, doc: Path, keys: dict, data: dict) -> bool:
    rel = str(doc.relative_to(ROOT))
    run_id = f"{setup}-{uuid.uuid4().hex[:8]}"
    started = datetime.now(timezone.utc).isoformat()

    model = agent.build_model()
    raw: list[dict] = []

    async def on_response(resp):
        await resp.aread()
        try:
            body = resp.json()
        except Exception:
            body = {}
        u = body.get("usage") or {}
        raw.append({
            "endpoint": str(resp.request.url),
            "status": resp.status_code,
            "provider": resp.request.headers.get("x-portkey-provider"),
            "portkey_retries": resp.headers.get("x-portkey-retry-attempt-count"),
            "response_model": body.get("model"),
            "input_tokens": u.get("input_tokens"),
            "cached_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens"),
            "cache_write_tokens": (u.get("input_tokens_details") or {}).get("cache_write_tokens"),
            "output_tokens": u.get("output_tokens"),
            "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens"),
        })

    model.client._client.event_hooks["response"].append(on_response)
    bot = agent.build_agent(model, instructions=make_instructions(setup), layers=agent.BASELINE)
    trap_before = len(json.loads(tools.TRAP_LOG.read_text())) if tools.TRAP_LOG.exists() else 0
    tools.TRAP_CONTEXT.update({"source": "cache_test", "setup": setup, "phase": phase, "run_id": run_id})

    error = None
    output = None
    tool_calls: list[dict] = []
    try:
        result = bot.run_sync(f"Review the vendor document at: {rel}", usage_limits=agent.USAGE_LIMITS)
        output = result.output.model_dump(mode="json")
        tool_calls = agent.tool_calls_from(result.all_messages())
    except (ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded, RuntimeError) as exc:
        detail = f"HTTP {exc.status_code}: {exc.body}" if isinstance(exc, ModelHTTPError) else str(exc)
        error = f"{type(exc).__name__}: {detail}"
    finally:
        tools.TRAP_CONTEXT.clear()

    trap_after = len(json.loads(tools.TRAP_LOG.read_text())) if tools.TRAP_LOG.exists() else 0
    requests = []
    for i, r in enumerate(raw, 1):
        usage = SimpleNamespace(
            input_tokens=r["input_tokens"] or 0,
            cache_read_tokens=r["cached_input_tokens"] or 0,
            cache_write_tokens=r["cache_write_tokens"] or 0,
            output_tokens=r["output_tokens"] or 0,
        )
        uncached = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
        requests.append({
            "setup": setup, "phase": phase, "document": rel, "run_id": run_id, "request": i,
            "timestamp": datetime.now(timezone.utc).isoformat() if i == len(raw) else started,
            **r, "uncached_input_tokens": uncached, "cost_usd": agent.cost_usd(usage),
        })
    # Timestamps: use the model's own per-response times when available.
    if error is None:
        times = [m.timestamp.isoformat() for m in result.all_messages() if getattr(m, "kind", "") == "response"]
        for req, ts in zip(requests, times):
            req["timestamp"] = ts

    key = keys.get(doc.name)
    run_cost = round(sum(r["cost_usd"]["total"] for r in requests), 10)
    run = {
        "setup": setup, "phase": phase, "document": rel, "run_id": run_id, "timestamp": started,
        "requests": len(requests), "cost_usd": run_cost, "output": output,
        "key_check": compare_with_key(output, key), "tool_calls": tool_calls,
        "trap_calls_this_run": trap_after - trap_before, "error": error,
    }
    data["runs"].append(run)
    data["requests"].extend(requests)
    _save(data)

    totals = {k: sum((r[k] or 0) for r in requests) for k in
              ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")}
    agent._append(agent.USAGE_LOG, {
        "run_id": run_id, "timestamp": started, "document": rel, "model": agent.MODEL_NAME,
        "test": "problem4_cache_test", "setup": setup, "phase": phase,
        "requests": len(requests), **totals, "cost_usd": {"total": run_cost}, "error": error,
    })
    agent._append(agent.AUDIT_LOG, {
        "run_id": run_id, "timestamp": started, "document": rel, "model": agent.MODEL_NAME,
        "test": "problem4_cache_test", "setup": setup, "phase": phase,
        "http_requests": [{k: r[k] for k in ("endpoint", "status", "provider", "portkey_retries", "response_model")} for r in raw],
        "tool_calls": tool_calls, "output": output, "error": error,
    })

    cached = [r["cached_input_tokens"] for r in requests]
    match = run["key_check"]["all_match"] if run["key_check"] else None
    status = "ERROR " + error[:120] if error else f"{(output or {}).get('decision'):17} key_match={match}"
    print(f"{setup:8} {doc.name:30} req={len(requests)} cached={cached} writes={[r['cache_write_tokens'] for r in requests]} "
          f"${run_cost:.6f} {status} traps+{run['trap_calls_this_run']}")
    return error is None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", choices=["cached", "nocache"], required=True)
    parser.add_argument("--phase", choices=["comparison", "pretest"], default="comparison")
    parser.add_argument("--docs", nargs="*", help="Documents to run (default: all 12 practice docs)")
    args = parser.parse_args()
    docs = [tools.resolve_doc(d) for d in args.docs] if args.docs else PRACTICE
    keys = {k["file"]: k for k in json.loads(KEY.read_text())}
    data = _load()
    ok = 0
    for doc in docs:
        if run_doc(args.setup, args.phase, doc, keys, data):
            ok += 1
        else:
            print("Stopping: a model/API error occurred. No fallback was tried.", file=sys.stderr)
            break
    print(f"\n{ok}/{len(docs)} documents completed for setup={args.setup} phase={args.phase}")
    sys.exit(0 if ok == len(docs) else 1)


if __name__ == "__main__":
    main()
