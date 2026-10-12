"""Campus Customs vendor desk agent.

    python agent.py --doc data/practice_docs/p01_bluehen_quote.html            # defended (Problem 6)
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --baseline # original Problem 3 agent

Reads one vendor document through the read_document tool, extracts the key
facts, and decides recommend / do_not_recommend under the shop handbook's
purchasing rules. The full handbook goes with every model call.

The model is gpt-6-luna through Portkey (Responses API) and nothing else. If
the call fails, the run stops and says why; there is no fallback model.

Every run appends to:
  output/usage_log.json   real token counts from the API and the dollar cost
  output/audit_trail.json tool calls, arguments, short results, final answer
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, Tool
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

import policy
import tools
from models import VendorDecision
from tools import (approve_payment, approve_payment_guarded, read_document, read_document_safe,
                   resolve_doc, send_email, send_email_guarded)

ROOT = Path(__file__).resolve().parent
PROMPT = ROOT / "prompts" / "prompt.md"                    # defended prompt (layer 3)
PROMPT_BASELINE = ROOT / "prompts" / "prompt_baseline.md"  # original Problem 3 prompt, unchanged
HANDBOOK = ROOT / "data" / "shop_handbook.md"
PRICES = ROOT / "data" / "prices.json"
USAGE_LOG = ROOT / "output" / "usage_log.json"
AUDIT_LOG = ROOT / "output" / "audit_trail.json"

MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
USAGE_LIMITS = UsageLimits(request_limit=6, tool_calls_limit=6)

# Defense layers (Problem 6): 1 = code-level document cleaning, 2 = design-level
# (deterministic decision + gated dangerous tools), 3 = prompt-level rules.
BASELINE: frozenset = frozenset()
DEFENDED: frozenset = frozenset({1, 2, 3})

# HW6/.env holds the Portkey settings and wins over anything exported in the shell.
load_dotenv(ROOT / ".env", override=True)


def build_model() -> OpenAIResponsesModel:
    """gpt-6-luna through Portkey's Responses API. No fallback."""
    api_key = os.getenv("PORTKEY_API_KEY")
    provider = os.getenv("PORTKEY_PROVIDER")
    if not api_key or not provider:
        raise RuntimeError("PORTKEY_API_KEY and PORTKEY_PROVIDER must be set in HW6/.env (see .env.example).")
    client = AsyncOpenAI(
        base_url=PORTKEY_BASE_URL,
        api_key="portkey-managed",  # the Portkey key goes in its own header, never to OpenAI
        default_headers={"x-portkey-api-key": api_key, "x-portkey-provider": provider},
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def build_instructions(layers=DEFENDED) -> str:
    """The agent prompt plus the full handbook, sent with every model request.
    Layer 3 uses the defended prompt; otherwise the original Problem 3 prompt."""
    prompt = PROMPT if 3 in layers else PROMPT_BASELINE
    return (
        prompt.read_text(encoding="utf-8")
        + "\n\n---\n\n# Campus Customs Shop Handbook (full text)\n\n"
        + HANDBOOK.read_text(encoding="utf-8")
    )


def build_agent(model: OpenAIResponsesModel, instructions=None, layers=DEFENDED) -> Agent[None, VendorDecision]:
    """The vendor desk agent. `layers` picks the defenses (BASELINE = the original
    Problem 3 agent). `instructions` overrides the prompt (the Problem 4 cache test
    passes a function that adds a per-request ID in front). Tool names stay the same
    in every mode, so runs are comparable."""
    reader = read_document_safe if 1 in layers else read_document
    mailer, payer = (send_email_guarded, approve_payment_guarded) if 2 in layers else (send_email, approve_payment)
    return Agent(
        model,
        instructions=instructions if instructions is not None else build_instructions(layers),
        output_type=VendorDecision,
        tools=[
            Tool(reader, takes_ctx=False, name="read_document"),
            Tool(mailer, takes_ctx=False, name="send_email"),
            Tool(payer, takes_ctx=False, name="approve_payment"),
        ],
        retries=2,
        name="vendor_desk",
    )


# --- logging ------------------------------------------------------------------------

def _append(path: Path, entry: dict) -> None:
    """Append-only JSON list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    items = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else []
    items.append(entry)
    path.write_text(json.dumps(items, indent=2) + "\n")


def cost_usd(usage: Any) -> dict:
    """Dollar cost from the API's own token counts and data/prices.json.

    input_tokens already includes cached tokens, so cached reads are billed at the
    cached price and only the rest at the full input price.
    """
    p = json.loads(PRICES.read_text())[MODEL_NAME]
    per = lambda key: Decimal(str(p[key])) / Decimal(1_000_000)  # noqa: E731
    cached = usage.cache_read_tokens or 0
    written = usage.cache_write_tokens or 0
    uncached = (usage.input_tokens or 0) - cached - written
    parts = {
        "uncached_input": uncached * per("input_per_1m"),
        "cached_input": cached * per("cached_input_per_1m"),
        "cache_write": written * per("cache_write_per_1m"),
        "output": (usage.output_tokens or 0) * per("output_per_1m"),
    }
    return {k: float(v) for k, v in parts.items()} | {"total": float(sum(parts.values()))}


def _short(value: Any, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def tool_calls_from(messages: list) -> list[dict]:
    results = {}
    for m in messages:
        for part in getattr(m, "parts", []):
            if isinstance(part, ToolReturnPart):
                results[part.tool_call_id] = part.content
    calls = []
    for m in messages:
        for part in getattr(m, "parts", []):
            if isinstance(part, ToolCallPart) and part.tool_name != "final_result":
                calls.append({
                    "tool": part.tool_name,
                    "arguments": part.args_as_dict(),
                    "result": _short(results.get(part.tool_call_id, "")),
                })
    return calls


# --- run ------------------------------------------------------------------------------

def review(doc_arg: str, layers=DEFENDED, label: dict | None = None) -> dict:
    """Run the agent on one document with the chosen defense layers and log it.

    Returns a record with the final answer (after layer 2's deterministic check when
    enabled), the model's own answer, what layer 1 removed, real token usage and cost.
    """
    layers = frozenset(layers)
    doc = resolve_doc(doc_arg)
    rel = str(doc.relative_to(ROOT))
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    started = datetime.now(timezone.utc).isoformat()
    tag = {"mode": "defended" if layers else "baseline", "layers": sorted(layers), **(label or {})}

    model = build_model()
    http_log: list[dict] = []

    async def on_response(resp):
        http_log.append({
            "url": str(resp.request.url),
            "status": resp.status_code,
            "provider": resp.request.headers.get("x-portkey-provider"),
            "portkey_retries": resp.headers.get("x-portkey-retry-attempt-count"),
        })

    model.client._client.event_hooks["response"].append(on_response)
    agent = build_agent(model, layers=layers)
    tools.LAST_READ.clear()
    tools.TRAP_CONTEXT.update({"run_id": run_id, "document": rel, **tag})
    record = {"run_id": run_id, "timestamp": started, "document": rel, "model": MODEL_NAME, **tag}

    try:
        result = agent.run_sync(f"Review the vendor document at: {rel}", usage_limits=USAGE_LIMITS)
    except (ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded, RuntimeError) as exc:
        detail = f"HTTP {exc.status_code}: {exc.body}" if isinstance(exc, ModelHTTPError) else str(exc)
        error = f"{type(exc).__name__}: {detail}"
        record.update(http_requests=http_log, tool_calls=[], output=None, error=error)
        _append(AUDIT_LOG, record)
        _append(USAGE_LOG, {k: record[k] for k in ("run_id", "timestamp", "document", "model", *tag)}
                | {"error": error, "note": "No usage recorded: the run failed before completing."})
        return record
    finally:
        tools.TRAP_CONTEXT.clear()

    usage = result.usage() if callable(result.usage) else result.usage
    model_output: VendorDecision = result.output
    final, changes = policy.decide(model_output) if 2 in layers else (model_output, [])
    tokens = {
        "requests": usage.requests,
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": (usage.details or {}).get("reasoning_tokens"),
    }
    cost = cost_usd(usage)
    record.update(
        response_model=getattr(result.response, "model_name", None),
        http_requests=http_log,
        tool_calls=tool_calls_from(result.all_messages()),
        model_output=model_output.model_dump(mode="json"),
        policy_changes=changes,
        security=dict(tools.LAST_READ) if 1 in layers else None,
        output=final.model_dump(mode="json"),
        usage=tokens, cost_usd=cost, error=None,
    )
    _append(USAGE_LOG, {k: record[k] for k in ("run_id", "timestamp", "document", "model", "response_model", *tag)}
            | tokens | {"cost_usd": cost})
    _append(AUDIT_LOG, {k: v for k, v in record.items() if k not in ("usage", "cost_usd")})
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs vendor desk agent")
    parser.add_argument("--doc", required=True, help="Path to one vendor document (HTML, PDF, or .eml)")
    parser.add_argument("--baseline", action="store_true", help="Run the original, undefended Problem 3 agent")
    parser.add_argument("--layers", help="Defense layers to enable, e.g. 1,3 (default: 1,2,3)")
    args = parser.parse_args()
    layers = BASELINE if args.baseline else (
        frozenset(int(x) for x in args.layers.split(",") if x) if args.layers else DEFENDED)
    try:
        rec = review(args.doc, layers)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Can't review that document: {exc}", file=sys.stderr)
        sys.exit(2)
    if rec["error"]:
        print(f"Run failed on {MODEL_NAME} (no fallback was tried).\n{rec['error']}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(rec["output"], indent=2))
    if rec["policy_changes"]:
        print("Layer 2 corrected the model's answer:", *rec["policy_changes"], sep="\n  ")
    u = rec["usage"]
    print(f"\n{rec['run_id']} | {rec['mode']} layers={rec['layers']} | {rec['response_model']} | "
          f"{u['requests']} requests | {u['input_tokens']} in ({u['cached_input_tokens']} cached) / "
          f"{u['output_tokens']} out | ${rec['cost_usd']['total']:.6f}")


if __name__ == "__main__":
    main()
