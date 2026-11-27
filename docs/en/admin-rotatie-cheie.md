# Rotating the admin key (ADMIN_TOKEN)

The key lives only in `/etc/tabela.env` (root, chmod 600). Do not put it in the repo, in the CHANGELOG, in logs or in the interface.

## Steps

1. Generate a new key, at least 24 characters long, on your own server:
   `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Edit `/etc/tabela.env` and set `ADMIN_TOKEN=<new key>`.
3. For strict mode, add `ADMIN_TOKEN_STRICT=1` to the same file (off by default).
4. Restart the service: `sudo systemctl restart tabela`.
5. Verify: logging in with the old key must be refused and the new one accepted.

## Effects

- All active sessions are invalidated on rotation (the cookie is signed with the old key). The only effect for you is having to log in again.
- With `ADMIN_TOKEN_STRICT=1` and a key shorter than 24 characters, the service does not start and prints a message that does not include the key. Fix `/etc/tabela.env` and restart.

## Recovery if you forgot the key

Connect over SSH, edit `/etc/tabela.env` (set a new key or remove `ADMIN_TOKEN_STRICT`) and restart the service. There is no other recovery path from the interface.

## Two-step login (2FA, optional)

Off by default. Without `ADMIN_TOTP_SECRET`, login stays key-only.

**Enable**
1. On the server: `python3 scripts/admin_totp_setup.py` (in `/opt/tabela`, with the app's venv). The script prints a base32 secret and an `otpauth://` URI; it writes nothing anywhere.
2. Add the secret to your authenticator app (TOTP, 6 digits, 30 s, SHA1): manual entry, or a QR code generated locally from the URI.
3. Add to `/etc/tabela.env`: `ADMIN_TOTP_SECRET=<the secret>` and restart: `sudo systemctl restart tabela`.
4. Check in a new window, **without closing the SSH session**: `#admin` asks for the key and the 6-digit code.

**Effects**
- Each code is accepted only once (±30 s clock tolerance). If you get "Wrong key or code.", wait for the next code.
- `Authorization: Bearer` is accepted only from the server (`127.0.0.1`), as with the `curl` examples; from outside it is refused.
- An invalid secret (not base32 or shorter than 16 characters) disables the administration (503) until you fix it.
- All login forms (`#admin`, `#ocr`, `#ocr2`, `#infofer`) show the code field.

**Disable / recovery** (lost phone, clock out of sync): over SSH, delete the `ADMIN_TOTP_SECRET` line from `/etc/tabela.env` and `sudo systemctl restart tabela`. For a new phone, generate a new secret with the script.

## Settings on the Settings page

The capture retention (1–30 days, default 7) and the free-space threshold (MB) are changed from the Settings page. The values from the environment (`CAPTURE_RETENTION_DAYS`, `CAPTURE_MIN_FREE_MB`) remain the defaults until a value is saved from the interface.
