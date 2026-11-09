# © 2026 Andy217Ace
"""Exportatorul de securitate (scripts/security_snapshot.py): rulează ca root din timer și
scrie snapshot.json pentru #admin. În teste totul vine din fișiere temporare (DB fail2ban cu
schema reală, log-uri nginx/fail2ban), nimic din sistem."""
import gzip
import importlib.util
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILTER = ROOT / "deploy" / "fail2ban" / "nginx-tabela-probes.local"


def _load():
    spec = importlib.util.spec_from_file_location(
        "security_snapshot", ROOT / "scripts" / "security_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = _load()
UTC = timezone.utc
# 2026-11-09 18:00:00 UTC
NOW = datetime(2026, 11, 9, 18, 0, 0, tzinfo=UTC).timestamp()

# schema reală (fail2ban 1.1.0 de pe server, `sqlite3 .schema`)
F2B_SCHEMA = """
CREATE TABLE fail2banDb(version INTEGER);
CREATE TABLE jails(name TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1);
CREATE INDEX jails_name ON jails(name);
CREATE TABLE logs(jail TEXT NOT NULL, path TEXT, firstlinemd5 TEXT, lastfilepos INTEGER DEFAULT 0, FOREIGN KEY(jail) REFERENCES jails(name) ON DELETE CASCADE, UNIQUE(jail, path),UNIQUE(jail, path, firstlinemd5));
CREATE INDEX logs_path ON logs(path);
CREATE INDEX logs_jail_path ON logs(jail, path);
CREATE TABLE bans(jail TEXT NOT NULL, ip TEXT, timeofban INTEGER NOT NULL, bantime INTEGER NOT NULL, bancount INTEGER NOT NULL default 1, data JSON, FOREIGN KEY(jail) REFERENCES jails(name) );
CREATE INDEX bans_jail_timeofban_ip ON bans(jail, timeofban);
CREATE INDEX bans_jail_ip ON bans(jail, ip);
CREATE INDEX bans_ip ON bans(ip);
CREATE TABLE bips(ip TEXT NOT NULL, jail TEXT NOT NULL, timeofban INTEGER NOT NULL, bantime INTEGER NOT NULL, bancount INTEGER NOT NULL default 1, data JSON, PRIMARY KEY(ip, jail), FOREIGN KEY(jail) REFERENCES jails(name) );
CREATE INDEX bips_timeofban ON bips(timeofban);
CREATE INDEX bips_ip ON bips(ip);
"""

J = "nginx-tabela-probes"


def ts(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp())


def make_db(path, bips=(), bans=(), jails=((J, 1), ("sshd", 1))):
    c = sqlite3.connect(path)
    c.executescript(F2B_SCHEMA)
    c.execute("INSERT INTO fail2banDb VALUES (4)")
    c.executemany("INSERT INTO jails VALUES (?,?)", jails)
    c.executemany("INSERT INTO bips(ip,jail,timeofban,bantime,bancount,data) VALUES (?,?,?,?,?,'{}')",
                  bips)
    c.executemany("INSERT INTO bans(jail,ip,timeofban,bantime,bancount,data) VALUES (?,?,?,?,?,'{}')",
                  bans)
    c.commit()
    c.close()
    return path


def nginx(ip, when, target, status=404, method="GET"):
    d = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    stamp = d.strftime("%d/%b/%Y:%H:%M:%S") + " +0000"
    return f'{ip} - - [{stamp}] "{method} {target} HTTP/1.1" {status} 22 "-" "curl/8"\n'


def f2b(when, event, ip, jail=J):
    return (f"{when},063 fail2ban.actions        [668168]: NOTICE  [{jail}] {event} {ip}\n")


# -- clasificarea probelor (aceleași reguli ca filtrul fail2ban) ---------------------------

PROBES = ["/.env", "/.env.local", "/.git/config", "/.gitignore", "/.aws/credentials",
          "/.svn/wc.db", "/wp-login.php", "/wp-admin/setup.php", "/blog/wp-includes/x.js",
          "/phpinfo.php", "/phpinfo", "/x/y/index.php", "/index.php?s=1", "/shell.php7",
          "/config.json", "/docker-compose.yml", "/storage/logs/laravel.log",
          "/SDK/webLanguage", "/a/.DS_Store", "http://evil.example/.env",
          "/.vscode/sftp.json", "/.ssh/id_rsa"]
LEGIT = ["/", "/api/board", "/api/admin/session", "/sw.js", "/app.js", "/style.css",
         "/.well-known/acme-challenge/x", "/.well-known/security.txt",
         "/icons/logo-96.png", "/manifest.webmanifest", "/?q=.env", "/favicon.ico",
         "/fonts/fira-code.woff2", "/offline.html", "/config.jsonx", "/phpx"]


@pytest.mark.parametrize("target", PROBES)
def test_probe_paths_are_counted_with_4xx(target):
    assert ss.is_probe(f"GET {target} HTTP/1.1", 404)
    assert ss.is_probe(f"GET {target} HTTP/1.1", 400)


@pytest.mark.parametrize("target", LEGIT)
def test_legit_paths_are_not_probes(target):
    assert not ss.is_probe(f"GET {target} HTTP/1.1", 404)


@pytest.mark.parametrize("status", [200, 301, 304, 500, 502])
def test_probe_needs_a_4xx_answer(status):
    assert not ss.is_probe("GET /.env HTTP/1.1", status)


def test_builtin_rule_equals_the_reference_filter():
    probe, source = ss.load_probe(FILTER)
    assert source == "filter"
    assert probe == ss.BUILTIN_PROBE


def test_missing_or_broken_filter_falls_back_to_builtin(tmp_path):
    assert ss.load_probe(tmp_path / "nope.local") == (ss.BUILTIN_PROBE, "builtin")
    bad = tmp_path / "bad.local"
    bad.write_text("[Definition]\n_probe = (unclosed\n", encoding="utf-8")
    assert ss.load_probe(bad) == (ss.BUILTIN_PROBE, "builtin")


# -- parsere -------------------------------------------------------------------------------

def test_parse_access_line():
    r = ss.parse_access_line(nginx("1.2.3.4", "2026-11-09 17:10:14", "/.env?x=1"))
    assert r == {"ip": "1.2.3.4", "ts": ts("2026-11-09 17:10:14"),
                 "request": "GET /.env?x=1 HTTP/1.1", "path": "/.env", "status": 404}


def test_parse_access_line_with_offset_and_ipv6():
    line = '2001:db8::1 - - [09/Nov/2026:19:10:14 +0200] "GET / HTTP/2.0" 200 5 "-" "-"\n'
    r = ss.parse_access_line(line)
    assert r["ip"] == "2001:db8::1" and r["ts"] == ts("2026-11-09 17:10:14")


@pytest.mark.parametrize("line", ["", "garbage\n", "\x00\x01\x02",
                                  '1.2.3.4 - - [99/Foo/2026:00:00:00 +0000] "GET / HTTP/1.1" 200 1 "-" "-"',
                                  '1.2.3.4 - - [09/Nov/2026:00:00:00 +0000] "\\x16\\x03\\x01" 400 1 "-" "-"'])
def test_parse_access_line_rejects_garbage(line):
    r = ss.parse_access_line(line)
    assert r is None or r["path"] is None  # TLS pe HTTP: cerere fără cale


def test_parse_f2b_log_line():
    assert ss.parse_f2b_line(f2b("2026-11-09 17:10:15", "Ban", "195.178.110.159"), UTC) == {
        "ts": ts("2026-11-09 17:10:15"), "event": "ban", "jail": J, "ip": "195.178.110.159"}
    assert ss.parse_f2b_line(f2b("2026-11-09 17:10:15", "Unban", "1.1.1.1"), UTC)["event"] == "unban"
    assert ss.parse_f2b_line(f2b("2026-11-09 17:10:15", "Restore Ban", "1.1.1.1"), UTC)["event"] == "restore"
    found = "2026-11-09 17:10:14,207 fail2ban.filter [1]: INFO    [x] Found 1.1.1.1 - 2026-11-09\n"
    assert ss.parse_f2b_line(found, UTC) is None
    assert ss.parse_f2b_line("garbage", UTC) is None


# -- baza fail2ban -------------------------------------------------------------------------

def test_read_f2b_db_current_bans(tmp_path):
    db = make_db(tmp_path / "f.sqlite3", bips=[
        ("9.9.9.1", J, int(NOW) - 3600, 86400, 2),       # activ
        ("9.9.9.2", J, int(NOW) - 90000, 86400, 1),      # expirat
        ("9.9.9.3", "sshd", int(NOW) - 10, -1, 5),       # permanent
    ], bans=[(J, "9.9.9.1", int(NOW) - 3600, 86400, 2)])
    out = ss.read_f2b_db(db, NOW)
    assert out["jails"] == ["nginx-tabela-probes", "sshd"]
    banned = {b["ip"]: b for b in out["banned"]}
    assert set(banned) == {"9.9.9.1", "9.9.9.3"}
    assert banned["9.9.9.1"] == {"ip": "9.9.9.1", "jail": J, "banned_ts": int(NOW) - 3600,
                                 "expires_ts": int(NOW) - 3600 + 86400, "bancount": 2}
    assert banned["9.9.9.3"]["expires_ts"] is None
    assert out["bans"] == [{"ts": int(NOW) - 3600, "event": "ban", "jail": J, "ip": "9.9.9.1"}]


def test_read_f2b_db_is_read_only(tmp_path):
    db = make_db(tmp_path / "f.sqlite3")
    before = db.read_bytes()
    ss.read_f2b_db(db, NOW)
    assert db.read_bytes() == before
    assert not (tmp_path / "f.sqlite3-journal").exists()


# -- snapshot complet ----------------------------------------------------------------------

@pytest.fixture
def env(tmp_path):
    db = make_db(tmp_path / "fail2ban.sqlite3", bips=[
        ("195.178.110.159", J, ts("2026-11-09 17:10:14"), 86400, 1),
        ("10.0.0.9", J, ts("2026-11-09 16:00:00"), 86400, 3),        # deban manual (log)
    ])
    f2blog = tmp_path / "fail2ban.log"
    f2blog.write_text(
        f2b("2026-11-01 10:00:00", "Ban", "7.7.7.7")             # > 7 zile: doar în istoric
        + f2b("2026-11-05 10:00:00", "Ban", "8.8.8.8")
        + f2b("2026-11-06 10:00:00", "Unban", "8.8.8.8")
        + f2b("2026-11-09 16:00:01", "Ban", "10.0.0.9")
        + f2b("2026-11-09 16:30:00", "Unban", "10.0.0.9")
        + f2b("2026-11-09 17:00:00", "Restore Ban", "8.8.8.8")
        + f2b("2026-11-09 17:10:15", "Ban", "195.178.110.159")
        + "2026-11-09 17:10:14,207 fail2ban.filter [1]: INFO [x] Found 1.1.1.1\n",
        encoding="utf-8")
    acc = tmp_path / "access.log"
    acc.write_text(
        nginx("195.178.110.159", "2026-11-09 17:10:14", "/.env")
        + nginx("195.178.110.159", "2026-11-09 17:10:14", "/.git/config")
        + nginx("195.178.110.159", "2026-11-09 17:10:14", "/.env")
        + nginx("195.178.110.159", "2026-11-09 17:10:13", "/", 200)
        + nginx("5.5.5.5", "2026-11-09 12:00:00", "/api/board", 200)
        + nginx("6.6.6.6", "2026-11-09 11:00:00", "/wp-login.php")
        + 'not a log line\n',
        encoding="utf-8")
    acc1 = tmp_path / "access.log.1"
    acc1.write_text(nginx("6.6.6.6", "2026-11-05 11:00:00", "/phpinfo.php")
                    + nginx("195.178.110.159", "2026-11-06 09:00:00", "/x.php"),
                    encoding="utf-8")
    with gzip.open(tmp_path / "access.log.2.gz", "wt", encoding="utf-8") as g:
        g.write(nginx("6.6.6.6", "2026-11-04 11:00:00", "/.env")
                + nginx("6.6.6.6", "2026-10-20 11:00:00", "/.env"))   # > 7 zile: ignorat
    return {"db": db, "f2b_logs": [f2blog], "access_logs": [acc, acc1, tmp_path / "access.log.2.gz"],
            "filter_path": FILTER, "tz": UTC}


def test_snapshot_banned_now_and_totals(env):
    s = ss.build_snapshot(NOW, **env)
    assert s["schema"] == ss.SCHEMA and s["generated_ts"] == NOW
    assert s["fail2ban"]["available"] is True
    assert [(b["ip"], b["jail"]) for b in s["banned"]] == [("195.178.110.159", J)]  # 10.0.0.9 debanat
    b = s["banned"][0]
    assert b["banned_at"] == "2026-11-09T17:10:14+00:00"
    assert b["expires_at"] == "2026-11-10T17:10:14+00:00"
    assert b["bancount"] == 1
    assert s["fail2ban"]["jails"] == [{"name": J, "banned_now": 1}, {"name": "sshd", "banned_now": 0}]
    t = s["totals"]
    assert t["banned_now"] == 1
    assert t["bans_24h"] == 2          # 10.0.0.9 + 195.178.110.159 (Restore nu se numără)
    assert t["bans_7d"] == 3           # + 8.8.8.8
    assert t["probes_24h"] == 4        # 3 de la .159 + wp-login de la 6.6.6.6
    assert t["probe_ips_24h"] == 2
    assert t["requests_24h"] == 6
    assert t["probes_7d"] == 7 and t["requests_7d"] == 9
    assert s["probe_rule"] == "filter"


def test_snapshot_per_ip_windows(env):
    s = ss.build_snapshot(NOW, **env)
    w = s["ips"]["195.178.110.159"]
    assert w["24h"]["requests"] == 4 and w["24h"]["probes"] == 3
    assert w["24h"]["paths"] == [{"path": "/.env", "count": 2}, {"path": "/.git/config", "count": 1}]
    assert w["24h"]["first_seen"] == "2026-11-09T17:10:13+00:00"
    assert w["24h"]["last_seen"] == "2026-11-09T17:10:14+00:00"
    assert w["7d"]["requests"] == 5 and w["7d"]["probes"] == 4
    assert w["7d"]["first_seen"] == "2026-11-06T09:00:00+00:00"
    six = s["ips"]["6.6.6.6"]
    assert six["24h"]["probes"] == 1 and six["7d"]["probes"] == 3   # oct.: în afara ferestrei
    assert "5.5.5.5" not in s["ips"]          # nici banat, nici probe
    assert s["top"][0]["ip"] == "195.178.110.159" and s["top"][0]["banned"] is True
    assert [x["ip"] for x in s["top"]] == ["195.178.110.159", "6.6.6.6"]
    assert s["top"][1] == {"ip": "6.6.6.6", "probes_24h": 1, "probes_7d": 3, "requests_7d": 3,
                           "last_seen": "2026-11-09T11:00:00+00:00", "banned": False}
    assert s["access_log"]["parse_errors"] == 1 and s["access_log"]["available"] is True


def test_snapshot_history_newest_first(env):
    h = ss.build_snapshot(NOW, **env)["history"]
    assert h[0] == {"at": "2026-11-09T17:10:15+00:00", "event": "ban", "jail": J,
                    "ip": "195.178.110.159"}
    assert [x["event"] for x in h] == ["ban", "restore", "unban", "ban", "unban", "ban", "ban"]


def test_top_paths_limited_and_truncated(tmp_path, env):
    acc = tmp_path / "big.log"
    lines = [nginx("4.4.4.4", "2026-11-09 17:00:00", f"/p{i}.php") for i in range(9)]
    lines.append(nginx("4.4.4.4", "2026-11-09 17:00:00", "/" + "a" * 600 + ".php"))
    acc.write_text("".join(lines), encoding="utf-8")
    env["access_logs"] = [acc]
    w = ss.build_snapshot(NOW, **env)["ips"]["4.4.4.4"]["24h"]
    assert len(w["paths"]) == ss.TOP_PATHS == 5
    assert all(len(p["path"]) <= ss.MAX_PATH_LEN for p in w["paths"])


def test_ips_limited_banned_first(env, monkeypatch):
    monkeypatch.setattr(ss, "MAX_IPS", 1)
    s = ss.build_snapshot(NOW, **env)
    assert list(s["ips"]) == ["195.178.110.159"]
    assert s["ips_truncated"] is True


def test_history_limited(env, monkeypatch):
    monkeypatch.setattr(ss, "MAX_HISTORY", 2)
    assert len(ss.build_snapshot(NOW, **env)["history"]) == 2


def test_without_fail2ban(tmp_path, env):
    env["db"] = tmp_path / "missing.sqlite3"
    env["f2b_logs"] = [tmp_path / "missing.log"]
    s = ss.build_snapshot(NOW, **env)
    assert s["fail2ban"]["available"] is False
    assert s["banned"] == [] and s["history"] == []
    assert s["totals"]["banned_now"] is None and s["totals"]["bans_24h"] is None
    assert s["totals"]["probes_24h"] == 4          # log-ul nginx tot se citește
    assert s["errors"]


def test_without_access_log(tmp_path, env):
    env["access_logs"] = [tmp_path / "missing.log"]
    s = ss.build_snapshot(NOW, **env)
    assert s["access_log"]["available"] is False
    assert s["totals"]["probes_24h"] is None and s["totals"]["requests_24h"] is None
    assert s["ips"] == {}           # valori necunoscute, nu 0
    assert s["banned"][0]["ip"] == "195.178.110.159"


def test_bans_fall_back_to_db_when_log_missing(tmp_path, env):
    env["db"] = make_db(tmp_path / "f2.sqlite3", bans=[
        (J, "1.1.1.1", int(NOW) - 100, 86400, 1), (J, "1.1.1.2", int(NOW) - 200000, 86400, 1)])
    env["f2b_logs"] = []
    s = ss.build_snapshot(NOW, **env)
    assert s["totals"]["bans_24h"] == 1
    assert s["totals"]["bans_7d"] is None   # baza fail2ban păstrează doar ~1 zi (dbpurgeage)
    assert [x["ip"] for x in s["history"]] == ["1.1.1.1", "1.1.1.2"]


def test_deadline_stops_reading(env, monkeypatch):
    monkeypatch.setattr(ss, "MAX_RUN_S", -1)
    s = ss.build_snapshot(NOW, **env)
    assert s["access_log"]["truncated"] is True


def test_banned_ip_without_requests_has_zero_counts(tmp_path, env):
    env["access_logs"] = [tmp_path / "empty.log"]
    (tmp_path / "empty.log").write_text("", encoding="utf-8")
    s = ss.build_snapshot(NOW, **env)
    w = s["ips"]["195.178.110.159"]["24h"]
    assert w["requests"] == 0 and w["probes"] == 0 and w["first_seen"] is None


def test_old_rotated_files_are_skipped_by_mtime(tmp_path, env):
    old = tmp_path / "access.log.9.gz"
    with gzip.open(old, "wt", encoding="utf-8") as g:
        g.write(nginx("3.3.3.3", "2026-11-09 17:00:00", "/.env"))  # conținut „nou", fișier vechi
    os.utime(old, (NOW - 9 * 86400, NOW - 9 * 86400))
    env["access_logs"] = [old]
    s = ss.build_snapshot(NOW, **env)
    assert "3.3.3.3" not in s["ips"] and s["access_log"]["files"] == 0


# -- scriere atomică și CLI ----------------------------------------------------------------

def test_write_atomic(tmp_path):
    out = tmp_path / "snapshot.json"
    ss.write_atomic(out, {"a": 1})
    assert json.loads(out.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]
    if os.name == "posix":
        assert (out.stat().st_mode & 0o777) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="symlink/owner checks are POSIX-only")
def test_write_atomic_refuses_symlinked_dir(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        ss.write_atomic(link / "snapshot.json", {"a": 1})
    assert not list(real.iterdir())


@pytest.mark.skipif(os.name != "posix", reason="symlink checks are POSIX-only")
def test_write_atomic_replaces_a_planted_symlink_without_following_it(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep", encoding="utf-8")
    d = tmp_path / "out"
    d.mkdir()
    (d / "snapshot.json.tmp").symlink_to(victim)
    ss.write_atomic(d / "snapshot.json", {"a": 1})
    assert victim.read_text(encoding="utf-8") == "keep"


def test_main_writes_snapshot(tmp_path, env):
    out = tmp_path / "out" / "snapshot.json"
    out.parent.mkdir()
    argv = ["--out", str(out), "--db", str(env["db"]), "--filter", str(FILTER),
            "--f2b-log", str(env["f2b_logs"][0]), "--group", ""]  # fără chown în teste
    for a in env["access_logs"]:
        argv += ["--access-log", str(a)]
    assert ss.main(argv) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == ss.SCHEMA and "duration_ms" in data


def test_main_fails_cleanly_when_out_dir_missing(tmp_path, capsys):
    assert ss.main(["--out", str(tmp_path / "nope" / "s.json"), "--db", str(tmp_path / "x")]) == 1
    assert "Traceback" not in capsys.readouterr().err


def test_exporter_uses_only_stdlib():
    text = (ROOT / "scripts" / "security_snapshot.py").read_text(encoding="utf-8")
    imports = {l.split()[1].split(".")[0] for l in text.splitlines()
               if l.startswith(("import ", "from ")) and not l.startswith("from __future__")}
    assert imports <= set(sys.stdlib_module_names), imports - set(sys.stdlib_module_names)
    assert not imports & {"socket", "urllib", "http", "subprocess", "ssl", "ftplib", "smtplib"}
    assert "gethostbyaddr" not in text and "getaddrinfo" not in text
