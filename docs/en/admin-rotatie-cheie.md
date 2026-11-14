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

## Settings on the Settings page

The capture retention (1–30 days, default 7) and the free-space threshold (MB) are changed from the Settings page. The values from the environment (`CAPTURE_RETENTION_DAYS`, `CAPTURE_MIN_FREE_MB`) remain the defaults until a value is saved from the interface.
