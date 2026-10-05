"""Measure the Monitor's "experts cached" figure against what the expert cache actually holds.

Runs a conversation workload against the server and reads `expert_slots` (the arena's capacity) and
`expert_slots_resident` (what the engine reports after this change) from GET /metrics after each turn:

  --workload topic    a multi-turn conversation that stays on one theme (a realistic chat; MoE routing
                      stays concentrated, so the cache fills far short of its arena)
  --workload diverse  the same number of turns, each on a different subject (routing spreads, the
                      resident count climbs) - the control that shows the figure SHOULD move
  --workload repeat   one short prompt, repeated (the extreme narrow-routing case)

A pre-change engine sends no `expert_slots_resident`, and its Monitor showed the same capacity under
every workload - run the topic workload before and after the change, and both workloads after, for the
full picture.  Example:

    python3 tools/measure_expert_residency.py --workload topic

AGENTS.md: numbers go in the PR with their environment - this prints one (GPU, driver, OS, engine
version); add the model, quantization and context flags from how you started the server.
"""
import argparse
from datetime import datetime, timezone
import json
import platform
import subprocess
import sys
import urllib.error
import urllib.request

# One theme throughout (a trip to Paris), each turn phrased differently: the way a real chat goes.
TOPIC = [
    "I'm planning a weekend in Paris. Suggest a two-day itinerary.",
    "Which neighborhood would you stay in, and why?",
    "What are some good bistros in Le Marais?",
    "How do I get from Charles de Gaulle airport to the city center?",
    "Is the Louvre doable in half a day? What should I prioritize?",
    "What's the best time of day to visit the Eiffel Tower?",
    "Can I get by with English, or should I learn a few French phrases?",
    "What day trips are worth it - Versailles or Giverny?",
    "How does the metro work? Which pass should I buy?",
    "What's a good area for an evening walk along the Seine?",
    "Any museums beyond the obvious ones that you'd recommend?",
    "Summarize all of this into a packing and planning checklist.",
]

# The same number of turns, each a different subject: routing spreads across the expert space.
DIVERSE = [
    "Prove that the square root of 2 is irrational.",
    "Write a Python function that merges two sorted lists.",
    "Compose a short poem about autumn rain.",
    "What caused the fall of the Roman Empire?",
    "Explain photosynthesis to a ten-year-old.",
    "Draft a polite email asking a landlord to fix a leaking tap.",
    "What are the health benefits of regular walking?",
    "Describe the plot of a mystery novel set on a train.",
    "How do interest rates affect housing prices?",
    "Give me a recipe for vegetarian chili.",
    "Explain how a neural network learns, without math.",
    "What should I see on a first visit to Tokyo?",
]

REPEAT = ["What is the capital of France?"] * 12


def get(url, api_key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def chat(url, model, messages, max_tokens, api_key):
    body = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens, "stream": False}).encode()
    req = urllib.request.Request(f"{url}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def gpu_line():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--workload", choices=["topic", "diverse", "repeat"], default="topic")
    ap.add_argument("--turns", type=int, default=0, help="cap the workload at this many turns")
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--model", default=None, help="defaults to the server's first model")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--out", default=None, help="also write the table to this JSON file")
    args = ap.parse_args()

    turns = {"topic": TOPIC, "diverse": DIVERSE, "repeat": REPEAT}[args.workload]
    if args.turns:
        turns = turns[:args.turns]

    try:
        model = args.model or get(f"{args.url}/v1/models", args.api_key)["data"][0]["id"]
        first = get(f"{args.url}/metrics", args.api_key)["engine"]
    except urllib.error.URLError as e:
        print(f"error: cannot reach the server at {args.url} ({e.reason}).\n"
              "start it first, e.g.:  .venv/bin/python -m serve.server --engine strata "
              "--config strata-<model>.json --port 8080", file=sys.stderr)
        return 2

    print("# environment")
    print(f"date_utc: {datetime.now(timezone.utc):%Y-%m-%d %H:%M}")
    print(f"platform: {platform.platform()}")
    print(f"gpu: {gpu_line() or 'nvidia-smi not available'}")
    print(f"engine: {first.get('version') or 'unknown'}")
    print(f"model: {model}")
    print(f"workload: {args.workload} ({len(turns)} turns, one growing conversation), max_tokens={args.max_tokens}")
    print()
    print("# after each turn: expert-cache slots (capacity) vs resident (holding an expert)")
    print(f"{'turn':>4}  {'expert_slots':>12}  {'resident':>8}  last user turn")
    rows, messages = [], []
    for i, text in enumerate(turns, 1):
        messages.append({"role": "user", "content": text})
        reply = chat(args.url, model, messages, args.max_tokens, args.api_key)
        messages.append({"role": "assistant",
                         "content": reply["choices"][0]["message"]["content"]})
        eng = get(f"{args.url}/metrics", args.api_key)["engine"]
        slots, resident = eng.get("expert_slots"), eng.get("expert_slots_resident")
        rows.append({"turn": i, "user": text, "expert_slots": slots, "expert_slots_resident": resident})
        shown = text if len(text) <= 52 else text[:49] + "..."
        print(f"{i:>4}  {slots if slots is not None else '–':>12}  "
              f"{resident if resident is not None else 'n/a':>8}  {shown}")

    last = rows[-1]
    print()
    if last["expert_slots_resident"] is None:
        print("summary: this engine reports no residency figure (pre-change): the Monitor shows the "
              f"capacity, {last['expert_slots']} experts, under every workload.")
    else:
        gap = (last["expert_slots"] or 0) - last["expert_slots_resident"]
        print(f"summary: capacity {last['expert_slots']}, resident {last['expert_slots_resident']} "
              f"after {len(rows)} {args.workload} turns ({gap} slots empty) - the Monitor's old figure "
              f"would have read {last['expert_slots']} regardless of the workload.")
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"url": args.url, "model": model, "workload": args.workload, "rows": rows}, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
