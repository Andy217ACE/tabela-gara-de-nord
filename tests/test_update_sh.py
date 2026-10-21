# © 2026 Andy217Ace
"""deploy/update.sh, simulated: a temp git "origin" + clone as APP_DIR, fake pip /
systemctl / health commands (injected through env overrides), a real SQLite file.

Covers: happy path, rollback when the new commit never gets healthy, abort before the
restart when pip fails, detached HEAD, /etc/tabela.env migration (no glued lines) and
the pre-migration SQLite backup (last N kept)."""
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "update.sh"


def _bash():
    if os.name == "nt":
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
            if Path(p).exists():
                return p
        return None
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("git") is None,
                                reason="needs bash (Git Bash on Windows) and git")


def posix(p) -> str:
    """Path as Git Bash / POSIX bash sees it."""
    s = str(p)
    if os.name == "nt" and len(s) > 1 and s[1] == ":":
        s = "/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def commit(repo, schema: int, health: str, msg: str):
    (repo / "app").mkdir(exist_ok=True)
    (repo / "app" / "store.py").write_text(f"SCHEMA_VERSION = {schema}\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (repo / "HEALTH").write_text(health, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def script(path: Path, body: str):
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return posix(path)


@pytest.fixture
def server(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    app = tmp_path / "app"
    data = tmp_path / "data"
    data.mkdir()
    # plain `git init` + checkout -b: `init -b` needs git >= 2.28
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    git(work, "checkout", "-q", "-b", "main")
    git(work, "remote", "add", "origin", str(origin))
    prev = commit(work, 2, '{"ok":true}', "v2 healthy")
    git(work, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", "-b", "main", str(origin), str(app)], check=True)

    log = tmp_path / "calls.log"
    fake = tmp_path / "bin"
    fake.mkdir()
    pip = script(fake / "pip", f'echo "pip $*" >> "{posix(log)}"\n'
                               f'[ ! -f "{posix(tmp_path / "PIP_FAILS")}" ]\n')
    script(fake / "systemctl", f'echo "systemctl $*" >> "{posix(log)}"\n')
    script(fake / "health", f'cat "{posix(app / "HEALTH")}"\n')

    db = data / "tabela.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE services(id INTEGER PRIMARY KEY)")
    c.execute("PRAGMA user_version = 2")
    c.commit()
    c.close()
    env_file = tmp_path / "tabela.env"
    env_file.write_bytes(b"DB_PATH=" + posix(db).encode() + b"\nPOLLER_ENABLED=1")  # no final \n

    env = {**os.environ, "APP_DIR": posix(app), "ENV_FILE": posix(env_file),
           "DATA_DIR": posix(data), "BACKUP_DIR": posix(data / "backups"), "BACKUP_KEEP": "2",
           # SYSTEMCTL / HEALTH_CMD are word-split by the script (like "curl -fs URL"),
           # so the fakes are called by name through PATH (temp paths contain spaces)
           "PATH": str(fake) + os.pathsep + os.environ.get("PATH", ""),
           "PIP": pip, "PYTHON": posix(sys.executable), "SYSTEMCTL": "systemctl",
           "HEALTH_CMD": "health", "HEALTH_TRIES": "2", "HEALTH_SLEEP": "0",
           "UNIT_DST": posix(tmp_path / "tabela.service"), "REQUIRE_ROOT": "0"}

    class S:
        pass
    s = S()
    s.__dict__.update(tmp=tmp_path, work=work, app=app, data=data, env=env, log=log,
                      env_file=env_file, db=db, prev=prev)

    def run(*args):
        return subprocess.run([BASH, posix(SCRIPT), *args], env=env, capture_output=True,
                              text=True, timeout=60)
    s.run = run
    s.head = lambda: subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"], check=True,
                                    capture_output=True, text=True).stdout.strip()
    return s


def test_happy_path_migrates_env_and_backs_up_db(server):
    new = commit(server.work, 3, '{"ok":true}', "v3 healthy")
    git(server.work, "push", "-q", "origin", "main")
    r = server.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert server.head() == new
    assert "OK:" in r.stdout
    env = server.env_file.read_text(encoding="utf-8").splitlines()
    assert env[1] == "POLLER_ENABLED=1" and env[2].startswith("LAST_IMAGE_PATH=")
    backups = list((server.data / "backups").glob("tabela-*-v2.db"))
    assert len(backups) == 1
    c = sqlite3.connect(backups[0])
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    c.close()
    calls = server.log.read_text().splitlines()
    assert calls.count("systemctl restart tabela") == 1
    # the restarted app would have migrated the DB; then a second run needs no backup
    c = sqlite3.connect(server.db)
    c.execute("PRAGMA user_version = 3")
    c.commit()
    c.close()
    r = server.run()
    assert r.returncode == 0 and "backup" not in r.stdout
    assert server.env_file.read_text().count("LAST_IMAGE_PATH=") == 1


def test_rolls_back_when_new_commit_is_unhealthy(server):
    commit(server.work, 2, "boom", "broken")
    git(server.work, "push", "-q", "origin", "main")
    r = server.run("main")
    assert r.returncode == 1
    assert server.head() == server.prev
    assert "rolling back" in r.stderr and "ROLLED BACK" in r.stderr
    calls = server.log.read_text().splitlines()
    assert calls.count("systemctl restart tabela") == 2
    assert sum(c.startswith("pip install") for c in calls) == 2


def test_pip_failure_aborts_before_restart(server):
    commit(server.work, 3, '{"ok":true}', "v3")
    git(server.work, "push", "-q", "origin", "main")
    (server.tmp / "PIP_FAILS").write_text("1")
    r = server.run()
    assert r.returncode == 1
    assert "pip install failed" in r.stderr and "NOT restarted" in r.stderr
    assert server.head() == server.prev
    assert "systemctl restart tabela" not in server.log.read_text()
    assert not (server.data / "backups").exists()


def test_detached_head_fails_clearly(server):
    git(server.app, "checkout", "-q", "--detach")
    r = server.run()
    assert r.returncode == 1 and "detached HEAD" in r.stderr
    assert not server.log.exists()


def test_keeps_only_last_backups(server):
    bk = server.data / "backups"
    bk.mkdir()
    for i in range(4):
        (bk / f"tabela-2026010{i}-000000-v2.db").write_bytes(b"x")
    commit(server.work, 3, '{"ok":true}', "v3")
    git(server.work, "push", "-q", "origin", "main")
    assert server.run().returncode == 0
    names = sorted(p.name for p in bk.glob("tabela-*.db"))
    assert len(names) == 2 and names[0] == "tabela-20260103-000000-v2.db"
