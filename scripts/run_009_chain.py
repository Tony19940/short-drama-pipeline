#!/usr/bin/env python3
"""Compatibility shim. Implementation: scripts/legacy/run_009_chain.py"""
from legacy.run_009_chain import main

if __name__ == "__main__":
    raise SystemExit(main())
