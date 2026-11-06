"""Manage sign-in accounts for MIS Lookup.

  .venv/bin/python manage_users.py add <username> ["Display Name"]   # prompts for a password
  .venv/bin/python manage_users.py remove <username>
  .venv/bin/python manage_users.py list

Adding the first user turns sign-in on (creates users.json). Removing users.json turns it off.
Restart is not needed: the file is read on every request.
"""
import getpass
import sys

import auth


def main(argv):
    if len(argv) < 2 or argv[1] not in {"add", "remove", "list"}:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "list":
        users = auth.list_users()
        print("\n".join(users) if users else "No users - sign-in is off.")
        return 0
    if len(argv) < 3:
        print(__doc__)
        return 1
    name = argv[2].strip()
    if cmd == "remove":
        print("Removed." if auth.remove_user(name) else f"No user named {name}.")
        return 0
    pw = getpass.getpass(f"Password for {name} (min 10 chars): ")
    if len(pw) < 10:
        print("Too short: use at least 10 characters.")
        return 1
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords don't match.")
        return 1
    auth.set_user(name, pw, argv[3] if len(argv) > 3 else "")
    print(f"Saved {name}. Sign-in is on; users are stored in {auth.USERS_FILE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
