"""Problem 6: run the defended vendor desk agent on all 12 practice documents.

    python defense_test.py --variant full          # layers 1+2+3 (the defended agent)
    python defense_test.py --variant layer1_only   # code-level cleaning only
    python defense_test.py --variant layer3_only   # prompt-level rules only

Layer 2 (deterministic decision + gated tools) adds no model tokens, so it is
measured by replaying its check on the other variants' answers. Results go to
output/defense_results.json in the same shape as Problem 5's attack_results.json,
plus real token usage and cost per document.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import agent
import tools
from attack_test import FIELDS, scan

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "output" / "defense_results.json"
KEY = ROOT / "data" / "practice_key.json"
PRACTICE = sorted((ROOT / "data" / "practice_docs").iterdir())
VARIANTS = {"full": {1, 2, 3}, "layer1_only": {1}, "layer3_only": {3}}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=VARIANTS, default="full")
    args = p.parse_args()
    layers = VARIANTS[args.variant]
    keys = {k["file"]: k for k in json.loads(KEY.read_text())}
    data = json.loads(RESULTS.read_text()) if RESULTS.exists() and RESULTS.read_text().strip() else {
        "description": "Problem 6: defended vendor desk agent on all 12 practice documents. 'runs' are the "
                       "full defense (layers 1+2+3); 'layer_experiments' isolate layers 1 and 3.",
        "runs": [], "layer_experiments": {},
    }
    batch = f"p6-{args.variant}-{uuid.uuid4().hex[:6]}"
    errors = 0
    out_runs = []
    for doc in PRACTICE:
        before = json.loads(tools.TRAP_LOG.read_text())
        rec = agent.review(str(doc.relative_to(ROOT)), layers,
                           label={"test": "problem6_defense", "variant": args.variant, "batch": batch})
        new_traps = json.loads(tools.TRAP_LOG.read_text())[len(before):]
        key = keys[doc.name]
        out = rec.get("output")
        fields = {f: (out or {}).get(f) == key[k] for f, k in FIELDS.items()} if out else {}
        run = {
            "test": "problem6_defense", "variant": args.variant, "layers": sorted(layers), "batch": batch,
            "run_id": rec["run_id"], "timestamp": rec["timestamp"], "document": rec["document"],
            "model": agent.MODEL_NAME, "http_requests": rec.get("http_requests", []),
            "output": out, "model_output": rec.get("model_output"), "policy_changes": rec.get("policy_changes", []),
            "expected": {f: key[k] for f, k in FIELDS.items()},
            "field_match": fields, "fields_correct": sum(fields.values()) if fields else 0,
            "decision_match": fields.get("decision"),
            "trap_calls": new_traps, "trap_triggered": bool(new_traps),
            "suspicious_in_answer": scan(out), "tool_calls": rec.get("tool_calls", []),
            "security": rec.get("security"),
            "usage": rec.get("usage"), "cost_usd": (rec.get("cost_usd") or {}).get("total"),
            "cost_breakdown_usd": rec.get("cost_usd"), "error": rec.get("error"),
        }
        out_runs.append(run)
        if args.variant == "full":
            data["runs"].append(run)
        else:
            data["layer_experiments"].setdefault(args.variant, []).append(run)
        RESULTS.write_text(json.dumps(data, indent=2) + "\n")
        wrong = [f for f, ok in fields.items() if not ok]
        sec = rec.get("security") or {}
        print(f"{doc.name:30} {('ERROR ' + rec['error'][:70]) if rec.get('error') else out['decision']:17} "
              f"fields {run['fields_correct']}/6 wrong={wrong} traps={len(new_traps)} "
              f"removed={len(sec.get('removed', []))} conflicts={len(sec.get('conflicts', []))} "
              f"policy_changed={bool(run['policy_changes'])} ${run['cost_usd'] or 0:.6f}")
        if rec.get("error"):
            errors += 1
            print("Stopping: model/API error. No fallback was tried.", file=sys.stderr)
            break
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
