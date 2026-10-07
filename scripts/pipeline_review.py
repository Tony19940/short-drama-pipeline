#!/usr/bin/env python3
"""Check narrative evidence or record an explicit local reviewer action."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from director.context import ProductionContext, using_context
from director.narrative import digest, inspect_narrative, contract_errors
from director.shot_table import design_review_digest
from director.review_actions import record_design, record_observation, record_sequence


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prod", required=True)
    p.add_argument("--episode", default="1")
    p.add_argument("--revision", default="")
    sub = p.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--report", default="")
    sub.add_parser("show")
    for command in ("design", "observe", "sequence"):
        sub.add_parser(command).add_argument("--input", required=True, help="reviewer-authored JSON; never inferred from a prompt")
    args = p.parse_args()
    ctx = ProductionContext.resolve(Path(args.prod).expanduser().resolve(), args.episode, args.revision)
    with using_context(ctx):
        if args.command == "check":
            report = inspect_narrative(ctx.prod, ctx.episode_token)
            table = ctx.read_artifact("shot_list.json", required=True)
            issues = contract_errors(ctx.read_artifact("events.json"), [r.get("shot_id") or r.get("id") for r in table.get("shots") or []])
            if issues:
                report["errors"].extend(issues)
                report["status"] = "fail"
            result = {"source": ctx.source_report(), **report}
            if args.report:
                path = Path(args.report).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        elif args.command == "show":
            result = {"source": ctx.source_report(), "design_input_sha256": design_review_digest(ctx.read_artifact("shot_list.json")),
                      "contract_sha256": digest(ctx.read_artifact("events.json")), "cut_file": ctx.cut_rel(),
                      "events": ctx.read_artifact("events.json"), "reviews": ctx.read_artifact("sequence_reviews.json")}
        else:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("review input must be a JSON object")
            result = {"design": record_design, "observe": record_observation, "sequence": record_sequence}[args.command](ctx, payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "check" and result.get("status") != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (PermissionError, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from None
