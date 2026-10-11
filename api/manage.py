"""Operator commands; never accept a credential or owner via agent HTTP input."""

import argparse
import os
import uuid

import runtime  # noqa: F401
import psycopg
from pydantic import ValidationError
from authority_errors import AuthorityError, DatabaseUnavailable
from db import get_conn, init_db
from principals import bind_agent, ensure_user, leash_user_id


def main():
  parser = argparse.ArgumentParser(description="LEASH database and agent provisioning")
  commands = parser.add_subparsers(dest="command", required=True)
  commands.add_parser("migrate")
  users = commands.add_parser("map-user")
  users.add_argument("--auth-user-id", required=True, type=uuid.UUID)
  commands.add_parser("demo-user")
  agents = commands.add_parser("bind-agent")
  agents.add_argument("--user-id", required=True)
  agents.add_argument("--agent-id", default="agt_shopper")
  agents.add_argument("--token-env", default="AGENT_TOKEN_SHOPPER")
  agents.add_argument("--mode", action="append", choices=["live", "scripted"], required=True)
  args = parser.parse_args()
  try:
    if args.command == "migrate":
      init_db()
      print("Migrations applied")
      return
    with get_conn() as conn:
      if args.command == "map-user":
        user_id = leash_user_id(str(args.auth_user_id))
        if conn.execute("SELECT id FROM users WHERE id = %s", (args.auth_user_id,)).fetchone() is None:
          raise AuthorityError(404, "Auth user does not exist")
        ensure_user(conn, user_id, str(args.auth_user_id))
      elif args.command == "demo-user":
        # Demo identity is enabled only by explicit server environment config.
        if len(os.environ.get("USER_TOKEN", "")) < 32:
          raise AuthorityError(422, "Set a strong demo USER_TOKEN first")
        user_id = os.environ.get("DEMO_USER_ID", "usr_demo")
        ensure_user(conn, user_id)
      else:
        if not args.token_env.startswith("AGENT_TOKEN_"):
          raise AuthorityError(422, "Agent credentials must use an AGENT_TOKEN_* environment variable")
        user_id = args.user_id
        bind_agent(conn, user_id=user_id, agent_id=args.agent_id,
                   token=os.environ.get(args.token_env, ""), modes=tuple(args.mode))
    print(f"{args.command} completed for {user_id}")
  except AuthorityError as exc:
    parser.exit(1, exc.detail + "\n")
  except (DatabaseUnavailable, psycopg.Error, ValidationError):
    parser.exit(1, "Provisioning failed; check database/configuration without logging credentials\n")


if __name__ == "__main__":
  main()
