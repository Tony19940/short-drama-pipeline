#!/usr/bin/env python3
"""Inspect/register explicit production revisions without moving any media."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from director.revisions import RevisionError, activate_revision, register_revision, resolve_binding


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prod", required=True)
    p.add_argument("--episode", default="1")
    p.add_argument("--revision", default="")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    reg = sub.add_parser("register")
    reg.add_argument("--artifact", action="append", default=[], metavar="BASE=PATH")
    reg.add_argument("--artifact-token", default="")
    reg.add_argument("--frames-dir", required=True)
    reg.add_argument("--shots-dir", required=True)
    reg.add_argument("--cut-file", default="")
    reg.add_argument("--activate", action="store_true")
    sub.add_parser("activate")
    args = p.parse_args()
    prod = Path(args.prod).expanduser().resolve()
    if not prod.is_dir():
        p.error("production directory does not exist")
    if args.command == "show":
        result = resolve_binding(prod, args.episode, args.revision).source_report()
    elif args.command == "activate":
        if not args.revision:
            p.error("activate needs --revision")
        result = activate_revision(prod, args.episode, args.revision)
    else:
        if not args.revision:
            p.error("register needs --revision")
        artifacts = {}
        for item in args.artifact:
            if "=" not in item:
                p.error("--artifact must be BASE=PATH")
            base, path = item.split("=", 1)
            if base in artifacts:
                p.error(f"duplicate artifact mapping: {base}")
            artifacts[base] = path
        result = register_revision(prod, {"episode_id": args.episode, "revision_id": args.revision,
                                         "artifact_token": args.artifact_token,
                                         "artifacts": artifacts, "frames_dir": args.frames_dir,
                                         "shots_dir": args.shots_dir, "cut_file": args.cut_file}, activate=args.activate)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except RevisionError as exc:
        raise SystemExit(str(exc)) from None
