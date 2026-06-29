"""`python -m outreach ...` — operational entrypoint (phase H).

  python -m outreach run --stage all --dry-run   # advance every lead one step (safe)
  python -m outreach run --stage classify
  python -m outreach run --stage send --dry-run
  python -m outreach run --stage all --live       # live still gated behind G-SEND
"""
from __future__ import annotations
import argparse
import sys

from . import run as run_mod


def main(argv=None):
    p = argparse.ArgumentParser(prog="outreach")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="advance leads one step per tick")
    r.add_argument("--stage", default="all", choices=["all", "classify", "send"])
    r.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    r.add_argument("--live", dest="dry_run", action="store_false",
                   help="attempt live send (still refused unless G-SEND is cleared)")
    args = p.parse_args(argv)

    if args.cmd == "run":
        print(run_mod.run(stage=args.stage, dry_run=args.dry_run))


if __name__ == "__main__":
    main(sys.argv[1:])
