"""Operator CLI for account bootstrap and maintenance.

Run inside the backend container (interactive terminal, no ``-T``):

    python -m app.cli create-super-admin --email owner@example.com --name "Full Name"
    python -m app.cli create-company-admin --email admin@example.com --name "Full Name"
    python -m app.cli change-email --current-email old@example.com
    python -m app.cli configure-subscription --company-name "Name" \
        --start-date 2026-01-01 --expiry-date 2026-12-31

Passwords are always prompted without echo (or piped on stdin with
``--password-stdin``); they are never accepted as arguments and are never
printed or logged. New email addresses are typed interactively by default so
real addresses never need to appear in source code or scripts.

Exit codes: 0 success / nothing to do, 1 refused, 2 bad input.
"""

import argparse
import getpass
import sys
from collections.abc import Callable
from datetime import date
from typing import TextIO

from sqlalchemy.orm import sessionmaker

from app.core.security import is_valid_email, normalize_email
from app.db.session import get_engine
from app.models import AccessCategory
from app.services.account_admin import AccountChangeError, change_user_email
from app.services.bootstrap import BootstrapError, BootstrapOutcome, create_initial_account
from app.services.subscription_setup import (
    SubscriptionSetupError,
    configure_initial_subscription,
)

Prompt = Callable[[str], str]

_BOOTSTRAP_COMMANDS = {
    "create-super-admin": (AccessCategory.SUPER_ADMIN, "Super Admin"),
    "create-company-admin": (AccessCategory.COMPANY_ADMIN, "Company Admin"),
}

_CATEGORY_LABELS = {
    AccessCategory.SUPER_ADMIN: "Super Admin",
    AccessCategory.COMPANY_ADMIN: "Company Admin",
    AccessCategory.COMPANY_USER: "Company User",
}


def _actor() -> str:
    try:
        return f"cli:{getpass.getuser()}"[:200]
    except Exception:  # noqa: BLE001 - no user database in some containers
        return "cli:unknown"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, label) in _BOOTSTRAP_COMMANDS.items():
        cmd = sub.add_parser(name, help=f"Create the initial {label}")
        cmd.add_argument("--email", required=True)
        cmd.add_argument("--name", required=True, help="Full name")
        cmd.add_argument("--password-stdin", action="store_true", help="Read password from stdin")

    change = sub.add_parser(
        "change-email",
        help="Change an existing account's sign-in email (requires that account's password)",
    )
    change.add_argument("--current-email", required=True)
    change.add_argument(
        "--new-email", help="Skip the interactive prompt (avoid: lands in shell history)"
    )
    change.add_argument(
        "--password-stdin", action="store_true", help="Read the account password from stdin"
    )

    sub_cfg = sub.add_parser(
        "configure-subscription",
        help="Create the company's initial subscription record (only when none exists)",
    )
    sub_cfg.add_argument("--company-name", required=True)
    sub_cfg.add_argument("--start-date", required=True, help="YYYY-MM-DD (first valid day)")
    sub_cfg.add_argument("--expiry-date", required=True, help="YYYY-MM-DD (last valid day)")
    sub_cfg.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    return parser


def _configure_subscription(args: argparse.Namespace, out: TextIO, prompt: Prompt) -> int:
    try:
        start = date.fromisoformat(args.start_date)
        expiry = date.fromisoformat(args.expiry_date)
    except ValueError:
        print("Dates must be in YYYY-MM-DD format. Nothing was changed.", file=out)
        return 2

    total = (expiry - start).days + 1
    print(f"Company:  {args.company_name.strip()}", file=out)
    print(f"Valid:    {start.isoformat()} through {expiry.isoformat()} ({total} days)", file=out)
    if not args.yes and prompt("Create this subscription? [y/N]: ").strip().lower() != "y":
        print("Cancelled. Nothing was changed.", file=out)
        return 1

    db = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        configure_initial_subscription(db, args.company_name, start, expiry, _actor())
    except SubscriptionSetupError as exc:
        print(f"Refused: {exc}", file=out)
        return 1
    finally:
        db.close()
    print("Subscription configured.", file=out)
    return 0


def _bootstrap(args: argparse.Namespace, stdin: TextIO, out: TextIO, secret: Prompt) -> int:
    category, label = _BOOTSTRAP_COMMANDS[args.command]
    if args.password_stdin:
        password = stdin.readline().rstrip("\r\n")
    else:
        password = secret("Password: ")
        if password != secret("Confirm password: "):
            print("Passwords do not match. Nothing was created.", file=out)
            return 2

    db = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        result = create_initial_account(db, category, args.email, args.name, password)
    except BootstrapError as exc:
        print(f"Refused: {exc}", file=out)
        return 1
    finally:
        db.close()

    if result.outcome is BootstrapOutcome.ALREADY_EXISTS:
        print(f"{label} {result.email} already exists. Nothing was changed.", file=out)
    else:
        print(f"Created {label} {result.email}.", file=out)
    return 0


def _change_email(
    args: argparse.Namespace, stdin: TextIO, out: TextIO, prompt: Prompt, secret: Prompt
) -> int:
    new_email = args.new_email
    if new_email is None:
        new_email = prompt("New email address: ").strip()
        if normalize_email(new_email) != normalize_email(prompt("Confirm new email address: ")):
            print("The email addresses do not match. Nothing was changed.", file=out)
            return 2
    if not is_valid_email(new_email):
        print("The new email address is not valid. Nothing was changed.", file=out)
        return 2

    if args.password_stdin:
        password = stdin.readline().rstrip("\r\n")
    else:
        password = secret(f"Current password of {normalize_email(args.current_email)}: ")

    db = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        result = change_user_email(db, args.current_email, new_email, password, _actor())
    except AccountChangeError as exc:
        print(f"Refused: {exc}", file=out)
        return 1
    finally:
        db.close()

    label = _CATEGORY_LABELS[result.access_category]
    print(f"Email changed for {label} account {result.user_id}:", file=out)
    print(f"  {result.old_email} -> {result.new_email}", file=out)
    print(f"  Signed out {result.sessions_revoked} active session(s).", file=out)
    print("  Password, role and account status are unchanged.", file=out)
    print(
        "  Note: the new address is NOT verified (email verification is not implemented yet).",
        file=out,
    )
    return 0


def main(
    argv: list[str] | None = None,
    stdin: TextIO = sys.stdin,
    out: TextIO = sys.stdout,
    prompt: Prompt = input,
    secret: Prompt = getpass.getpass,
) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "change-email":
        return _change_email(args, stdin, out, prompt, secret)
    if args.command == "configure-subscription":
        return _configure_subscription(args, out, prompt)
    return _bootstrap(args, stdin, out, secret)


if __name__ == "__main__":
    raise SystemExit(main())
