"""`python -m outreach ...` — operational entrypoint (phase H).

  python -m outreach run --stage all --dry-run   # advance every lead one step (safe)
  python -m outreach run --stage enrich          # any single stage, autonomy gate or not
  python -m outreach run --stage all --live       # live still gated behind G-SEND
  python -m outreach auth-google                   # one-off: OAuth consent -> GOOGLE_REFRESH_TOKEN
  python -m outreach hash-password                 # mint CONSOLE_PASSWORD_HASH for the console login
"""
from __future__ import annotations
import argparse
import sys

from . import run as run_mod

STAGES = ["all", "inbound", "classify", "monitor", "discover", "enrich", "draft",
          "followup", "auto_approve", "send", "digest"]


def main(argv=None):
    p = argparse.ArgumentParser(prog="outreach")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="advance leads one step per tick")
    r.add_argument("--stage", default="all", choices=STAGES)
    r.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    r.add_argument("--live", dest="dry_run", action="store_false",
                   help="attempt live send (still refused unless G-SEND is cleared)")
    sub.add_parser("auth-google", help="one-off: OAuth consent -> print GOOGLE_REFRESH_TOKEN")
    sub.add_parser("hash-password", help="mint an argon2id hash for CONSOLE_PASSWORD_HASH")
    args = p.parse_args(argv)

    if args.cmd == "run":
        print(run_mod.run(stage=args.stage, dry_run=args.dry_run))
    elif args.cmd == "auth-google":
        from . import auth_google
        auth_google.run()
    elif args.cmd == "hash-password":
        import getpass

        from . import webauth
        pw = getpass.getpass("Console password: ")
        if pw != getpass.getpass("Repeat: "):
            raise SystemExit("passwords do not match")
        print("\nAdd to the environment / Secret Manager (never commit):\n")
        print(f"CONSOLE_PASSWORD_HASH={webauth.hash_password(pw)}")


if __name__ == "__main__":
    main(sys.argv[1:])
