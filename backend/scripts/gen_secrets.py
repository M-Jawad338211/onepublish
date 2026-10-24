"""Generate the secrets the app needs.

uv run python scripts/gen_secrets.py            # prints TOKEN_ENC_KEY and SESSION_SECRET
uv run python scripts/gen_secrets.py --password # prompts, prints ADMIN_PASSWORD_HASH
"""

import base64
import getpass
import os
import secrets
import sys

from argon2 import PasswordHasher

if "--password" in sys.argv:
    pw = getpass.getpass("Admin password: ")
    if pw != getpass.getpass("Again: "):
        sys.exit("Passwords differ")
    if len(pw) < 12:
        sys.exit("Use at least 12 characters")
    print(f"ADMIN_PASSWORD_HASH={PasswordHasher().hash(pw)}")
else:
    print(f"TOKEN_ENC_KEY={base64.b64encode(os.urandom(32)).decode()}")
    print(f"SESSION_SECRET={secrets.token_urlsafe(48)}")
