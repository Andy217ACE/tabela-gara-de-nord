# © 2026 Andy217Ace
"""Generate a secret for the optional admin 2FA (TOTP) and print how to enable it.

    python scripts/admin_totp_setup.py [--label NAME]

Prints a fresh base32 secret and its otpauth:// URI. Nothing is written anywhere: copy
the secret into /etc/tabela.env yourself (see docs/admin-rotatie-cheie.md). Run it on the
server or in a private terminal; the output is a secret.
"""
from __future__ import annotations

import argparse
import base64
import secrets
from urllib.parse import quote, urlencode


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")  # 160 bits, 32 chars


def otpauth_uri(secret: str, label: str, issuer: str = "Tabela Gara de Nord") -> str:
    query = urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1",
                       "digits": 6, "period": 30}, quote_via=quote)
    return f"otpauth://totp/{quote(issuer)}:{quote(label)}?{query}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", default="admin", help="account name shown in the app")
    label = ap.parse_args().label
    secret = new_secret()
    print("Secret (base32, pentru introducere manuală / for manual entry):")
    print(f"  {' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))}")
    print("\nURI (pentru un generator de cod QR local / for a local QR generator):")
    print(f"  {otpauth_uri(secret, label)}")
    print(f"""
Pași / Steps:
  1. Adaugă secretul în aplicația de autentificare (TOTP, 6 cifre, 30 s, SHA1).
     Add the secret to your authenticator app (TOTP, 6 digits, 30 s, SHA1).
  2. Pe server / on the server:  sudo nano /etc/tabela.env
       ADMIN_TOTP_SECRET={secret}
  3. sudo systemctl restart tabela
  4. Verifică / check: #admin cere cheia + codul din aplicație / asks for key + app code.
Recuperare / recovery: șterge ADMIN_TOTP_SECRET din /etc/tabela.env și repornește.
Nu salva acest output / do not keep this output.""")


if __name__ == "__main__":
    main()
