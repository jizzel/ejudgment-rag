"""Manage invited accounts (there is no self sign-up).

python -m ejudgment.worker.users create --email a@b.org --name "A. Mensah" [--role admin]
python -m ejudgment.worker.users list
python -m ejudgment.worker.users disable|enable|revoke-sessions EMAIL
python -m ejudgment.worker.users reset-password EMAIL [--generate]

Passwords are typed (twice, not echoed) or generated with --generate and printed once.
Every change is recorded in auth_events.
"""

import argparse
import getpass
import secrets
import sys
from collections.abc import Sequence

from ejudgment.auth.passwords import WeakPassword
from ejudgment.auth.service import (
    create_user,
    find_user,
    list_users,
    reset_password,
    revoke_sessions,
    set_active,
)
from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.domain.enums import UserRole


def _password(generate: bool) -> tuple[str, bool]:
    if generate:
        return secrets.token_urlsafe(18), True
    first = getpass.getpass("New password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise WeakPassword("The passwords do not match")
    return first, False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ejudgment.worker.users", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Invite a user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", default="")
    create.add_argument("--role", choices=[r.value for r in UserRole], default="researcher")
    create.add_argument("--generate", action="store_true", help="Generate and print a password")
    commands.add_parser("list", help="List users")
    for name in ("disable", "enable", "revoke-sessions"):
        commands.add_parser(name).add_argument("email")
    reset = commands.add_parser("reset-password", help="Set a new password; ends all sessions")
    reset.add_argument("email")
    reset.add_argument("--generate", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = make_engine(settings)
    try:
        with engine.begin() as conn:
            if args.command == "list":
                for row in list_users(conn):
                    state = "active" if row.is_active else "disabled"
                    last = (
                        row.last_login_at.isoformat(timespec="minutes")
                        if row.last_login_at
                        else "never"
                    )
                    sys.stdout.write(f"{row.email}\t{row.role}\t{state}\tlast login {last}\n")
            elif args.command == "create":
                password, generated = _password(args.generate)
                user = create_user(
                    conn,
                    settings,
                    email=args.email,
                    display_name=args.name,
                    password=password,
                    role=UserRole(args.role),
                )
                sys.stdout.write(f"created {user.email} ({user.role})\n")
                if generated:
                    sys.stdout.write(f"password (shown once): {password}\n")
            elif args.command == "reset-password":
                password, generated = _password(args.generate)
                reset_password(conn, settings, args.email, password)
                sys.stdout.write(f"password reset for {args.email}; all sessions ended\n")
                if generated:
                    sys.stdout.write(f"password (shown once): {password}\n")
            elif args.command in ("disable", "enable"):
                set_active(conn, settings, args.email, args.command == "enable")
                sys.stdout.write(f"{args.command}d {args.email}\n")
            else:
                row = find_user(conn, args.email)
                count = revoke_sessions(conn, settings, row.id, reason="admin")
                sys.stdout.write(f"ended {count} session(s) of {args.email}\n")
    except (WeakPassword, LookupError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
