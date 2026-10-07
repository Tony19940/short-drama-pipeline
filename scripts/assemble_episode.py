#!/usr/bin/env python3
"""Local EDL export with revision and narrative gates; never submits cloud jobs."""
import argparse
import json
from pathlib import Path
from director.context import ProductionContext, using_context
from director.jobs import assemble_episode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", required=True)
    parser.add_argument("--episode", default="1")
    parser.add_argument("--revision", default="")
    parser.add_argument("--candidate", action="store_true", help="isolated local preview; cannot approve or replace the official EDL")
    args = parser.parse_args()
    ctx = ProductionContext.resolve(Path(args.prod).expanduser().resolve(), args.episode, args.revision)
    with using_context(ctx):
        result = assemble_episode(ctx.prod, ctx.episode_token, candidate=args.candidate)
    # ffmpeg's captured log stays in the worker; keep the handoff readable.
    result.pop("stdout", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (PermissionError, ValueError, OSError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
