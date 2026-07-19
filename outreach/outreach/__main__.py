"""`python -m outreach ...` — operational entrypoint (phase H).

  python -m outreach run --stage all --dry-run   # advance every lead one step (safe)
  python -m outreach run --stage enrich          # any single stage, autonomy gate or not
  python -m outreach run --stage all --live       # live still gated behind G-SEND
  python -m outreach auth-google                   # one-off: OAuth consent -> GOOGLE_REFRESH_TOKEN
  python -m outreach hash-password                 # mint CONSOLE_PASSWORD_HASH for the console login
  python -m outreach export-leads --state enriched # dump the ready-pool lead list to CSV
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
    x = sub.add_parser("export-leads", help="dump the lead list to CSV")
    x.add_argument("--state", default=None, help="filter by lead state (e.g. enriched); omit = all")
    x.add_argument("--out", default=None, help="output path; omit = stdout")
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
    elif args.cmd == "export-leads":
        from . import export
        if args.out:
            n = export.write_csv(args.out, state=args.state)
            print(f"wrote {n} leads -> {args.out}")
        else:
            print(export.leads_csv(state=args.state), end="")


if __name__ == "__main__":
    main(sys.argv[1:])
