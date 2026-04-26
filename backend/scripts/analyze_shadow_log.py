"""Aggregate one or more shadow-router JSONL files into a readable report.

Usage::

    python scripts/analyze_shadow_log.py logs/shadow_router_2026-04-25.jsonl
    python scripts/analyze_shadow_log.py logs/*.jsonl
    python scripts/analyze_shadow_log.py --since 2026-04-20 logs/

Outputs:
  - summary table to stdout
  - if --report PATH given: a Markdown breakdown of all disagreements

The script is dependency-free (stdlib only) so it can run anywhere.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _iter_records(paths: list[str]):
    files: list[Path] = []
    for p in paths:
        if os.path.isdir(p):
            files.extend(sorted(Path(p).glob("shadow_router_*.jsonl")))
        else:
            files.extend(Path(x) for x in glob.glob(p))
    if not files:
        print(f"no input files found in {paths!r}", file=sys.stderr)
        sys.exit(2)
    for f in files:
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line), f
                except json.JSONDecodeError:
                    continue


def analyze(paths: list[str]) -> dict:
    total = 0
    thin = 0  # turns where engine had no opinion (no rules fired)
    fired_counter: Counter = Counter()
    rule_pair_counter: Counter = Counter()  # (rule, agree?) → n
    agree_overall = 0
    disagree_breakdown: Counter = Counter()  # field → n
    disagreements: list = []
    durations: list[float] = []

    for rec, _file in _iter_records(paths):
        total += 1
        if rec.get("thin"):
            thin += 1
        durations.append(rec.get("duration_ms", 0.0))
        ag = rec.get("agreement", {}) or {}
        if ag.get("overall"):
            agree_overall += 1
        else:
            for k in ("intent_match", "state_match", "pattern_match", "action_match"):
                if not ag.get(k, True):
                    disagree_breakdown[k] += 1
            disagreements.append(rec)

        for fired in (rec.get("shadow", {}) or {}).get("fired_rules", []) or []:
            rid = fired.get("rule_id") if isinstance(fired, dict) else None
            if rid:
                fired_counter[rid] += 1
                rule_pair_counter[(rid, bool(ag.get("overall")))] += 1

    avg_dur = sum(durations) / len(durations) if durations else 0.0
    p95_dur = sorted(durations)[int(len(durations) * 0.95)] if durations else 0.0

    return {
        "total": total,
        "thin": thin,
        "active": total - thin,
        "agreement_count": agree_overall,
        "agreement_pct": (agree_overall / total * 100) if total else 0.0,
        "disagree_breakdown": dict(disagree_breakdown),
        "fired_counter": dict(fired_counter),
        "rule_pair_counter": {f"{k[0]}/{'agree' if k[1] else 'disagree'}": v
                              for k, v in rule_pair_counter.items()},
        "disagreements": disagreements,
        "avg_duration_ms": round(avg_dur, 3),
        "p95_duration_ms": round(p95_dur, 3),
    }


def print_summary(summary: dict) -> None:
    t = summary["total"]
    print()
    print("=" * 60)
    print("SHADOW ROUTER AGREEMENT REPORT")
    print("=" * 60)
    print(f"Total turns analyzed:   {t}")
    print(f"  Thin (no rule fired): {summary['thin']}")
    print(f"  Active (>=1 fired):   {summary['active']}")
    print()
    print(f"Agreement:              {summary['agreement_count']}/{t} "
          f"({summary['agreement_pct']:.2f}%)")
    print()
    if summary["disagree_breakdown"]:
        print("Disagreement breakdown:")
        for k, v in sorted(summary["disagree_breakdown"].items()):
            print(f"  {k:20s} {v}")
        print()
    print("Rule fire counts:")
    for rid, n in sorted(summary["fired_counter"].items(), key=lambda x: -x[1]):
        agree = summary["rule_pair_counter"].get(f"{rid}/agree", 0)
        disagree = summary["rule_pair_counter"].get(f"{rid}/disagree", 0)
        print(f"  {rid:35s} fired={n:4d}  agree={agree:4d}  disagree={disagree:4d}")
    print()
    print(f"Engine performance:     avg={summary['avg_duration_ms']}ms  "
          f"p95={summary['p95_duration_ms']}ms")
    print("=" * 60)


def write_report(summary: dict, path: Path) -> None:
    lines = ["# Shadow Router Disagreement Report", ""]
    lines.append(f"- total: {summary['total']}")
    lines.append(f"- agreement: {summary['agreement_pct']:.2f}%")
    lines.append("")
    lines.append("## Disagreements")
    for d in summary["disagreements"]:
        ag = d.get("agreement", {})
        inp = d.get("input", {})
        actual = d.get("actual", {})
        shadow = d.get("shadow", {})
        fired = [f.get("rule_id") for f in (shadow.get("fired_rules") or [])]
        lines.append("")
        lines.append(f"### Turn {d.get('session')}-{d.get('turn')}")
        lines.append(f"- message: `{inp.get('message')!r}`")
        lines.append(f"- intent={inp.get('intent')} state={inp.get('state')} "
                     f"persona={inp.get('persona')} entities={inp.get('entities')}")
        lines.append(f"- actual: pattern={actual.get('pattern_id')} "
                     f"intent_final={actual.get('intent_final')} "
                     f"state_final={actual.get('state_final')} "
                     f"action={actual.get('direct_action')}")
        lines.append(f"- shadow: pattern={shadow.get('enforced_pattern_id')} "
                     f"intent_override={shadow.get('intent_override')} "
                     f"state_override={shadow.get('state_override')} "
                     f"action={shadow.get('direct_action')} "
                     f"fired={fired}")
        lines.append(f"- agreement flags: {ag}")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written → {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="JSONL file(s) or directory")
    ap.add_argument("--report", type=Path, help="Write Markdown report to PATH")
    args = ap.parse_args(argv)
    summary = analyze(args.paths)
    print_summary(summary)
    if args.report:
        write_report(summary, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
