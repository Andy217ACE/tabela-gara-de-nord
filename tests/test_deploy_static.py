# © 2026 Andy217Ace
"""Static checks for the deploy files: install.sh, tabela.service, .env.example, README.

They read the files as text (no systemd, no apt, no server): the values that must agree
between the code, the env example, the installer and the unit."""
import re
from pathlib import Path

from app.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
PROD_VAPID_SUBJECT = "https://tabelacfr.ddns.net"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _unit_section(text: str, name: str) -> list[str]:
    """Lines of one [Section] of a systemd unit (comments and blanks dropped)."""
    out, inside = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            inside = s == f"[{name}]"
            continue
        if inside and s and not s.startswith("#"):
            out.append(s)
    return out


# -- watchdog sudoers (defect 1) -------------------------------------------------------------

def test_install_sh_installs_watchdog_sudoers_like_update_sh():
    text = _read(DEPLOY / "install.sh")
    assert "deploy/tabela-watchdog.sudoers" in text
    assert "/etc/sudoers.d/tabela-watchdog" in text
    # the same approach as update.sh: validate with visudo first, then install mode 440
    assert "visudo -cf" in text and "install -m 440" in text
    assert text.index("visudo -cf") < text.index("install -m 440") < text.index(
        "enable --now tabela-watchdog.timer")


def test_install_sh_and_update_sh_use_the_same_sudoers_destination():
    install = _read(DEPLOY / "install.sh")
    update = _read(DEPLOY / "update.sh")
    dst = "/etc/sudoers.d/tabela-watchdog"
    assert dst in install and dst in update


# -- VAPID_SUBJECT agrees everywhere (defect 3) ----------------------------------------------

def test_vapid_subject_default_is_the_site_url(monkeypatch):
    monkeypatch.delenv("VAPID_SUBJECT", raising=False)
    assert get_settings().vapid_subject == PROD_VAPID_SUBJECT


def test_vapid_subject_agrees_in_env_example_and_install_sh():
    env_example = re.search(r"^VAPID_SUBJECT=(\S+)\s*$", _read(ROOT / ".env.example"), re.M)
    install = re.search(r"^VAPID_SUBJECT=(\S+)\s*$", _read(DEPLOY / "install.sh"), re.M)
    assert env_example and install
    assert env_example.group(1) == PROD_VAPID_SUBJECT
    assert install.group(1) == PROD_VAPID_SUBJECT


# -- Telegram state file under the unit's ReadWritePaths (defect 4) --------------------------

def test_unit_sets_telegram_state_path_under_read_write_paths():
    service = _unit_section(_read(DEPLOY / "tabela.service"), "Service")
    prefix = "Environment=TELEGRAM_STATE_PATH="
    env = [l[len(prefix):] for l in service if l.startswith(prefix)]
    assert len(env) == 1
    state = env[0]
    rw = [p for l in service if l.startswith("ReadWritePaths=")
          for p in l.split("=", 1)[1].split()]
    assert rw, "the unit must declare ReadWritePaths"
    assert any(state.startswith(p.rstrip("/") + "/") for p in rw), (state, rw)
    assert state == "/var/lib/tabela/telegram_sent.json"


def test_code_default_for_telegram_state_path_is_unchanged():
    # dev and tests rely on the relative default; only the unit points to the state dir
    text = _read(ROOT / "app" / "telegram.py")
    assert '"data/telegram_sent.json"' in text


# -- Telegram variables in .env.example (defect 5) -------------------------------------------

def test_env_example_lists_telegram_variables_as_empty_placeholders():
    text = _read(ROOT / ".env.example")
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        assert re.search(rf"^#\s*{key}=\s*$", text, re.M), key
    assert re.search(r"^#\s*TELEGRAM_STATE_PATH=/var/lib/tabela/telegram_sent\.json\s*$",
                     text, re.M)
    # no real values: the token and the chat id are never written, not even as examples
    assert not re.search(r"^\s*TELEGRAM_(BOT_TOKEN|CHAT_ID)=", text, re.M)


# -- README lists the real apt packages (defect 5) -------------------------------------------

def test_readme_lists_every_apt_package_install_sh_installs():
    install = _read(DEPLOY / "install.sh")
    m = re.search(r"apt-get install -y -q (.+)$", install, re.M)
    assert m
    packages = m.group(1).split()
    readme = _read(ROOT / "README.md")
    start = readme.index("Scriptul instalează")
    paragraph = readme[start:readme.index("creează", start)]
    for pkg in packages:
        assert f"`{pkg}`" in paragraph, pkg
