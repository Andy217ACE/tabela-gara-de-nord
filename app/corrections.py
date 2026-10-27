# © 2026 Andy217Ace
"""Manual corrections from the admin (schema v9): narrow rules that fix a value the OCR
keeps reading wrong (e.g. IR 1584 on the board is really IR 1581).

A *rule* is ``(board, field, wrong_value)`` -> ``correct_value``, optionally narrowed to
one station, one scheduled time and/or an interval of service days. It acts in two ways:

- on NEW frames: ``correct_frame`` rewrites the matching OCR rows before the store ingests
  them; the observation of such a row carries ``+corr:<id>`` in its processing version and
  the per-field raw/normalised OCR text stays untouched in ``fields_json``;
- RETROACTIVELY, reversibly: ``plan`` (dry run, writes nothing) -> ``apply`` (one
  transaction; every row it changes is archived with its before/after values in
  ``correction_archive`` under a batch id) -> ``restore`` (puts the archived values back,
  only where the row still holds the corrected value). Same style as
  ``scripts/merge_number_dups.py``.

Rules are soft-deleted (``status='deleted'``), every state change is written to
``correction_audit``. Nothing here is read by a public endpoint: corrections, notes and
the audit log exist for the admin only (``app.corrections_api``).

A missing value is never 0: a ``wrong_value`` of ``""`` (platform, delay only) means
"the cell was not read" (platform NULL; delay without proof of reading).
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import logging
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone

from app.models import Row
from app.normalize import MAX_DELAY, PLATFORM_MAX, _TYPES
from app.store import TZ, service_date

log = logging.getLogger(__name__)

BOARDS = ("arrival", "departure")
FIELDS = ("type", "no", "station", "operator", "time", "platform", "delay")
NOTE_MIN, NOTE_MAX = 3, 500
MAX_ACTIVE_RULES = 500
MAX_SPAN_DAYS = 3660
SAMPLE = 50  # rows listed per kind in a preview (the counts are always complete)
CORR_TAG = "+corr:"

SCHEMA_V9 = (
    """CREATE TABLE IF NOT EXISTS corrections (
        id INTEGER PRIMARY KEY,
        board TEXT NOT NULL CHECK (board IN ('arrival', 'departure')),
        field TEXT NOT NULL CHECK (field IN
            ('type', 'no', 'station', 'operator', 'time', 'platform', 'delay')),
        wrong_value TEXT NOT NULL,
        correct_value TEXT NOT NULL,
        station TEXT,
        sched_time TEXT,
        date_from TEXT,
        date_to TEXT,
        note TEXT NOT NULL DEFAULT '',
        source_capture_id INTEGER,
        source_row_index INTEGER,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT 'admin',
        deleted_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_corrections_status ON corrections(status, board, field)",
    """CREATE TABLE IF NOT EXISTS correction_batches (
        id TEXT PRIMARY KEY,
        correction_id INTEGER NOT NULL REFERENCES corrections(id),
        applied_at TEXT NOT NULL,
        applied_by TEXT NOT NULL DEFAULT 'admin',
        summary_json TEXT NOT NULL DEFAULT '{}',
        restored_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_correction_batches_rule ON correction_batches(correction_id)",
    """CREATE TABLE IF NOT EXISTS correction_archive (
        id INTEGER PRIMARY KEY,
        batch TEXT NOT NULL,
        table_name TEXT NOT NULL,
        row_id INTEGER NOT NULL,
        data_json TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_correction_archive_batch ON correction_archive(batch)",
    """CREATE TABLE IF NOT EXISTS correction_audit (
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        actor TEXT NOT NULL,
        ip TEXT,
        action TEXT NOT NULL,
        correction_id INTEGER,
        batch TEXT,
        detail_json TEXT NOT NULL DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS ix_correction_audit_ts ON correction_audit(ts)",
)


class CorrectionError(ValueError):
    """Invalid input / state; ``status`` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def migrate_to_9(conn: sqlite3.Connection) -> None:
    """Schema v8 -> v9: the corrections tables (additive), atomically with the version
    bump (a failure leaves v8 in place). Re-runnable."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 9:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stmt in SCHEMA_V9:
            conn.execute(stmt)
        conn.execute("PRAGMA user_version = 9")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def has_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                        " AND name='corrections'").fetchone() is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- validation ----------------------------------------------------------------------------

_NAME_OK = re.compile(r"^[A-Z0-9][A-Z0-9 .,'/()\-]*$")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _name(v: str, what: str, lo: int, hi: int) -> str:
    s = unicodedata.normalize("NFKD", v)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"\s+", " ", s).strip()
    if not lo <= len(s) <= hi or not _NAME_OK.match(s):
        raise CorrectionError(f"{what} invalid(ă): {lo}–{hi} caractere (litere, cifre, spațiu, - . , ' / ( )).")
    return s


def _int_str(v: str, what: str, lo: int, hi: int) -> str:
    if not (v.isascii() and v.isdigit() and len(v) <= 6) or not lo <= int(v) <= hi:
        raise CorrectionError(f"{what} invalid(ă): număr întreg între {lo} și {hi}.")
    return str(int(v))


def norm_value(field: str, value, what: str, *, allow_empty: bool) -> str:
    """Canonical text of a field value (the same form `row_value` returns). ``""`` is the
    „not read" marker, valid only for platform/delay and only as a *wrong* value."""
    if value is None:
        value = ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise CorrectionError(f"{what} invalid(ă).")
    v = str(value).strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise CorrectionError(f"{what} conține caractere de control.")
    if v == "":
        if allow_empty and field in ("platform", "delay"):
            return ""
        raise CorrectionError(f"{what} este obligatoriu(ă)."
                              if not allow_empty else
                              f"{what}: „necitit” se poate corecta doar la linie și întârziere.")
    if field == "type":
        t = v.upper()
        if t not in _TYPES:
            raise CorrectionError(f"{what}: tip necunoscut (permise: {', '.join(sorted(_TYPES))}).")
        return t
    if field == "no":
        return _int_str(v, what, 1, 99999)
    if field == "station":
        return _name(v, what, 2, 60)
    if field == "operator":
        return _name(v, what, 2, 40)
    if field == "time":
        m = _TIME.match(v)
        if not m:
            raise CorrectionError(f"{what} invalidă: format OO:MM (00:00–23:59).")
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    if field == "platform":
        return _int_str(v, what, 1, PLATFORM_MAX)
    if field == "delay":
        return _int_str(v, what, 0, MAX_DELAY)
    raise CorrectionError("Câmp necunoscut.")


def _opt_int(v, what: str) -> int | None:
    if v in (None, ""):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).isascii() \
            or not str(v).isdigit() or len(str(v)) > 12:
        raise CorrectionError(f"{what} invalid.")
    return int(v)


def _opt_date(v, what: str) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not _DATE.match(v.strip()):
        raise CorrectionError(f"{what} invalidă (AAAA-LL-ZZ).")
    try:
        return date.fromisoformat(v.strip()).isoformat()
    except ValueError:
        raise CorrectionError(f"{what} invalidă (AAAA-LL-ZZ).") from None


def validate_rule(data) -> dict:
    """The normalised rule from a request body, or CorrectionError (HTTP 422)."""
    if not isinstance(data, dict):
        raise CorrectionError("Cerere invalidă.")
    allowed = {"board", "field", "wrong_value", "correct_value", "station", "sched_time",
               "date_from", "date_to", "note", "source_capture_id", "source_row_index"}
    extra = set(data) - allowed
    if extra:
        raise CorrectionError("Câmpuri necunoscute: " + ", ".join(sorted(map(str, extra))[:5]))
    board, field = data.get("board"), data.get("field")
    if board not in BOARDS:
        raise CorrectionError("Panou invalid (Sosiri sau Plecări).")
    if field not in FIELDS:
        raise CorrectionError("Câmp invalid.")
    wrong = norm_value(field, data.get("wrong_value"), "Valoarea citită", allow_empty=True)
    right = norm_value(field, data.get("correct_value"), "Valoarea corectă", allow_empty=False)
    if wrong == right:
        raise CorrectionError("Valoarea corectă este identică cu cea citită.")
    st = data.get("station")
    station = None if st in (None, "") else _name(str(st), "Stația (limitare)", 2, 60)
    sc = data.get("sched_time")
    sched = None if sc in (None, "") else norm_value("time", sc, "Ora (limitare)",
                                                     allow_empty=False)
    d_from = _opt_date(data.get("date_from"), "Data de început")
    d_to = _opt_date(data.get("date_to"), "Data de sfârșit")
    if d_from and d_to:
        if d_from > d_to:
            raise CorrectionError("Intervalul de zile este invers (început după sfârșit).")
        if (date.fromisoformat(d_to) - date.fromisoformat(d_from)).days > MAX_SPAN_DAYS:
            raise CorrectionError("Intervalul de zile este prea mare.")
    note = data.get("note")
    if not isinstance(note, str):
        raise CorrectionError("Nota este obligatorie.")
    note = note.strip()
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in note):
        raise CorrectionError("Nota conține caractere de control.")
    if not NOTE_MIN <= len(note) <= NOTE_MAX:
        raise CorrectionError(f"Nota trebuie să aibă {NOTE_MIN}–{NOTE_MAX} caractere.")
    return {"board": board, "field": field, "wrong_value": wrong, "correct_value": right,
            "station": station, "sched_time": sched, "date_from": d_from, "date_to": d_to,
            "note": note, "source_capture_id": _opt_int(data.get("source_capture_id"), "Captura"),
            "source_row_index": _opt_int(data.get("source_row_index"), "Rândul")}


def _scope_count(r: dict) -> int:
    return sum(1 for k in ("station", "sched_time", "date_from", "date_to") if r.get(k))


# -- rules in the database -------------------------------------------------------------------

_RULE_COLS = ("id, board, field, wrong_value, correct_value, station, sched_time, date_from,"
              " date_to, note, source_capture_id, source_row_index, status, created_at,"
              " created_by, deleted_at")


def _rule(r) -> dict:
    return {k: r[k] for k in r.keys()}


def active_rules(conn: sqlite3.Connection) -> list[dict]:
    """Active rules, narrowest first (more limits, then lower id)."""
    if not has_tables(conn):
        return []
    rules = [_rule(r) for r in conn.execute(
        f"SELECT {_RULE_COLS} FROM corrections WHERE status='active' ORDER BY id")]
    rules.sort(key=lambda r: (-_scope_count(r), r["id"]))
    return rules


def get_rule(conn: sqlite3.Connection, rid: int) -> dict | None:
    r = conn.execute(f"SELECT {_RULE_COLS} FROM corrections WHERE id=?", (rid,)).fetchone()
    return _rule(r) if r else None


def audit(conn: sqlite3.Connection, action: str, *, actor: str = "admin", ip: str | None = None,
          correction_id: int | None = None, batch: str | None = None,
          detail: dict | None = None) -> None:
    conn.execute("INSERT INTO correction_audit(ts, actor, ip, action, correction_id, batch,"
                 " detail_json) VALUES (?,?,?,?,?,?,?)",
                 (_now(), actor, ip, action, correction_id, batch,
                  json.dumps(detail or {}, ensure_ascii=False)))


def create_rule(store, rule: dict, *, actor: str = "admin", ip: str | None = None) -> dict:
    """Insert a validated rule (active, effective on new frames at once)."""
    with store._lock:
        c = store._conn
        c.execute("BEGIN IMMEDIATE")
        try:
            if c.execute("SELECT COUNT(*) FROM corrections WHERE status='active'"
                         ).fetchone()[0] >= MAX_ACTIVE_RULES:
                raise CorrectionError("Prea multe reguli active.", 409)
            dup = c.execute(
                "SELECT id FROM corrections WHERE status='active' AND board=? AND field=?"
                " AND wrong_value=? AND IFNULL(station,'')=? AND IFNULL(sched_time,'')=?"
                " AND IFNULL(date_from,'')=? AND IFNULL(date_to,'')=?",
                (rule["board"], rule["field"], rule["wrong_value"], rule["station"] or "",
                 rule["sched_time"] or "", rule["date_from"] or "", rule["date_to"] or "")
            ).fetchone()
            if dup:
                raise CorrectionError(f"Există deja regula activă #{dup[0]} pentru aceeași "
                                      "valoare și aceleași limite.", 409)
            rid = c.execute(
                "INSERT INTO corrections(board, field, wrong_value, correct_value, station,"
                " sched_time, date_from, date_to, note, source_capture_id, source_row_index,"
                " status, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?,?)",
                (rule["board"], rule["field"], rule["wrong_value"], rule["correct_value"],
                 rule["station"], rule["sched_time"], rule["date_from"], rule["date_to"],
                 rule["note"], rule["source_capture_id"], rule["source_row_index"], _now(),
                 actor)).lastrowid
            audit(c, "create", actor=actor, ip=ip, correction_id=rid, detail=rule)
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        return get_rule(c, rid)


def list_rules(store, status: str = "active") -> list[dict]:
    where = "" if status == "all" else " WHERE status=?"
    with store._lock:
        c = store._conn
        out = [_rule(r) for r in c.execute(
            f"SELECT {_RULE_COLS} FROM corrections{where} ORDER BY id DESC",
            () if status == "all" else (status,))]
        for r in out:
            r["batches"] = [{"id": b["id"], "applied_at": b["applied_at"],
                             "restored_at": b["restored_at"],
                             "summary": json.loads(b["summary_json"] or "{}")}
                            for b in c.execute(
                                "SELECT * FROM correction_batches WHERE correction_id=?"
                                " ORDER BY applied_at DESC, id DESC", (r["id"],))]
    return out


def audit_log(store, limit: int = 100) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    with store._lock:
        return [{"id": r["id"], "ts": r["ts"], "actor": r["actor"], "ip": r["ip"],
                 "action": r["action"], "correction_id": r["correction_id"],
                 "batch": r["batch"], "detail": json.loads(r["detail_json"] or "{}")}
                for r in store._conn.execute(
                    "SELECT * FROM correction_audit ORDER BY id DESC LIMIT ?", (limit,))]


# -- new frames --------------------------------------------------------------------------------

def row_value(row: Row, field: str) -> str:
    if field == "type":
        return row.train_type
    if field == "no":
        return str(row.train_no)
    if field == "station":
        return row.station
    if field == "operator":
        return row.operator
    if field == "time":
        return row.sched_time
    if field == "platform":
        return "" if row.platform is None else str(row.platform)
    return str(row.delay_min) if row.delay_read else ""  # delay


def _with_value(row: Row, field: str, value: str) -> Row:
    if field == "type":
        return dataclasses.replace(row, train_type=value)
    if field == "no":
        return dataclasses.replace(row, train_no=int(value))
    if field == "station":
        return dataclasses.replace(row, station=value)
    if field == "operator":
        return dataclasses.replace(row, operator=value)
    if field == "time":
        return dataclasses.replace(row, sched_time=value)
    if field == "platform":
        return dataclasses.replace(row, platform=int(value))
    return dataclasses.replace(row, delay_min=int(value), delay_read=True)


def _matches(rule: dict, row: Row, day: str) -> bool:
    if rule["board"] != row.board or row_value(row, rule["field"]) != rule["wrong_value"]:
        return False
    if rule["station"] and (row.station or "").upper() != rule["station"]:
        return False
    if rule["sched_time"] and row.sched_time != rule["sched_time"]:
        return False
    if rule["date_from"] and day < rule["date_from"]:
        return False
    return not (rule["date_to"] and day > rule["date_to"])


def correct_row(row: Row, rules: list[dict], when: datetime) -> tuple[Row, list[dict]]:
    """`row` with every matching rule applied (one rule per field, narrowest first; all
    rules are matched against the row as read), and the list of applied changes
    ``{id, field, from, to}``."""
    day = service_date(row.sched_time, when).isoformat()
    done: dict[str, dict] = {}
    new = row
    for rule in rules:  # `rules` is narrowest-first
        if rule["field"] in done or not _matches(rule, row, day):
            continue
        done[rule["field"]] = {"id": rule["id"], "field": rule["field"],
                               "from": rule["wrong_value"], "to": rule["correct_value"]}
        new = _with_value(new, rule["field"], rule["correct_value"])
    return new, sorted(done.values(), key=lambda d: d["id"])


def _frame_rules(store) -> list[dict]:
    with store._lock:
        return active_rules(store._conn)


def correct_rows(store, rows, when: datetime) -> list[Row]:
    """The rows of a frame with the active rules applied (fail-open: on any error the rows
    come back as read, the board is never affected)."""
    try:
        rules = _frame_rules(store)
        if not rules or not rows:
            return rows
        return [correct_row(r, rules, when)[0] for r in rows]
    except Exception:
        log.exception("manual corrections failed; frame ingested as read")
        return rows


def correct_frame(store, rows, debug, when: datetime):
    """(rows, debug) with the active rules applied. A corrected debug entry gets
    ``corr`` (the rule ids -> ``+corr:<id>`` in the observation's version) and, per
    corrected field, ``fields[f]["corr"] = {id, from, to}``; the OCR raw/norm text stays."""
    try:
        rules = _frame_rules(store)
        if not rules or (not rows and not debug):
            return rows, debug
        new_rows = [correct_row(r, rules, when)[0] for r in rows] if rows else rows
        new_debug = debug
        if debug:
            new_debug = []
            for e in debug:
                r = e.get("row")
                if r is None:
                    new_debug.append(e)
                    continue
                nr, applied = correct_row(r, rules, when)
                if not applied:
                    new_debug.append(e)
                    continue
                fields = {k: (dict(v) if isinstance(v, dict) else v)
                          for k, v in (e.get("fields") or {}).items()}
                for a in applied:
                    cell = fields.get(a["field"])
                    if isinstance(cell, dict):
                        cell["corr"] = {"id": a["id"], "from": a["from"], "to": a["to"]}
                    else:
                        fields[a["field"]] = {"corr": {"id": a["id"], "from": a["from"],
                                                       "to": a["to"]}}
                new_debug.append({**e, "row": nr, "fields": fields,
                                  "corr": [a["id"] for a in applied]})
        return new_rows, new_debug
    except Exception:
        log.exception("manual corrections failed; frame recorded as read")
        return rows, debug


# -- retroactive: plan (dry run) ---------------------------------------------------------------

def _has(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _local_day(observed_at: str) -> str:
    try:
        d = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(TZ).date().isoformat()


def _typed(field: str, value: str):
    return value if field in ("type", "station", "operator", "time") else int(value)


def _svc_expr(field: str, has_q: bool) -> str:
    return {"type": "s.train_type", "no": "s.train_no", "time": "s.sched_time",
            "platform": "s.last_platform", "delay": "s.last_delay",
            "station": ("COALESCE(q.station_canonical, s.station)" if has_q else "s.station"),
            "operator": ("COALESCE(q.operator_canonical, s.operator)" if has_q
                         else "s.operator")}[field]


def _plan_services(conn, rule: dict) -> tuple[list[dict], list[dict]]:
    """(to_update, conflicts) services matching the rule."""
    has_q = _has(conn, "service_quality")
    f, wrong, right = rule["field"], rule["wrong_value"], rule["correct_value"]
    expr = _svc_expr(f, has_q)
    where, args = ["s.board=?"], [rule["board"]]
    if f == "delay":
        if wrong == "":
            where.append("s.delay_read_at IS NULL")
        else:
            where.append("s.delay_read_at IS NOT NULL AND s.last_delay=?")
            args.append(int(wrong))
    elif wrong == "":  # platform not read
        where.append("s.last_platform IS NULL")
    else:
        where.append(f"{expr}=?")
        args.append(_typed(f, wrong))
    if rule["station"]:
        where.append(f"UPPER({_svc_expr('station', has_q)})=?")
        args.append(rule["station"])
    if rule["sched_time"]:
        where.append("s.sched_time=?")
        args.append(rule["sched_time"])
    if rule["date_from"]:
        where.append("s.service_date>=?")
        args.append(rule["date_from"])
    if rule["date_to"]:
        where.append("s.service_date<=?")
        args.append(rule["date_to"])
    if has_q:
        where.append("COALESCE(q.ghost, 0)=0")
    sql = ("SELECT s.id, s.board, s.service_date, s.train_type, s.train_no, s.sched_time,"
           " s.station, s.operator, s.last_platform, s.last_delay, s.delay_read_at,"
           f" {expr} AS effective FROM services s"
           + (" LEFT JOIN service_quality q ON q.service_id=s.id" if has_q else "")
           + " WHERE " + " AND ".join(where) + " ORDER BY s.service_date, s.sched_time, s.id")
    found = [dict(r) for r in conn.execute(sql, args)]
    ok, conflicts = [], []
    for s in found:
        s["effective"] = s["effective"] if s["effective"] is not None else ""
        clash = None
        if f == "no":
            clash = conn.execute(
                "SELECT id FROM services WHERE board=? AND service_date=? AND train_no=?"
                " AND sched_time=? AND id<>?",
                (s["board"], s["service_date"], int(right), s["sched_time"], s["id"])
            ).fetchone()
        elif f == "time":
            clash = conn.execute(
                "SELECT id FROM services WHERE board=? AND service_date=? AND train_no=?"
                " AND sched_time=? AND id<>?",
                (s["board"], s["service_date"], s["train_no"], right, s["id"])).fetchone()
        if clash:
            s["conflict"] = (f"există deja serviciul #{clash[0]} cu valoarea corectă în același "
                             "loc (se comasează cu scripts/merge_number_dups.py)")
            conflicts.append(s)
        else:
            ok.append(s)
    return ok, conflicts


_OBS_COL = {"no": "train_no", "station": "station", "operator": "operator",
            "time": "sched_time", "platform": "platform", "delay": "delay_min"}


def _plan_observations(conn, rule: dict, skip_services: set[int]) -> list[dict]:
    f = rule["field"]
    if f == "type":  # the type of a line lives only in fields_json (raw OCR evidence)
        return []
    col, wrong = _OBS_COL[f], rule["wrong_value"]
    where, args = ["o.board=?", "o.train_no IS NOT NULL"], [rule["board"]]
    if f == "delay":
        if wrong == "":
            where.append("o.delay_read=0")
        else:
            where.append("o.delay_read=1 AND o.delay_min=?")
            args.append(int(wrong))
    elif wrong == "":
        where.append("o.platform IS NULL")
    else:
        where.append(f"o.{col}=?")
        args.append(_typed(f, wrong))
    if rule["station"]:
        where.append("UPPER(o.station)=?")
        args.append(rule["station"])
    if rule["sched_time"]:
        where.append("o.sched_time=?")
        args.append(rule["sched_time"])
    sql = ("SELECT o.id, o.capture_id, o.service_id, o.observed_at, o.row_index, o.train_no,"
           " o.station, o.operator, o.sched_time, o.platform, o.delay_min, o.delay_read,"
           " o.processing_version, s.service_date FROM observations o"
           " LEFT JOIN services s ON s.id=o.service_id WHERE " + " AND ".join(where)
           + " ORDER BY o.id")
    out = []
    for r in conn.execute(sql, args):
        if r["service_id"] in skip_services:
            continue
        day = r["service_date"] or _local_day(r["observed_at"])
        if (rule["date_from"] and day < rule["date_from"]) or \
                (rule["date_to"] and day > rule["date_to"]):
            continue
        out.append(dict(r))
    return out


def _plan_events(conn, rule: dict, service_ids: list[int]) -> list[dict]:
    f = rule["field"]
    if f not in ("delay", "platform") or rule["wrong_value"] == "" or not service_ids:
        return []
    out = []
    for i in range(0, len(service_ids), 500):
        part = service_ids[i:i + 500]
        marks = ",".join("?" * len(part))
        out += [dict(r) for r in conn.execute(
            f"SELECT id, service_id, kind, old, new FROM events WHERE kind=?"
            f" AND service_id IN ({marks}) AND (new=? OR old=?) ORDER BY id",
            (f, *part, rule["wrong_value"], rule["wrong_value"]))]
    return out


def plan(conn: sqlite3.Connection, rule: dict) -> dict:
    """Dry run: what applying `rule` retroactively would change. Writes nothing.
    ``plan_hash`` identifies exactly this change set (``apply`` refuses a stale one)."""
    services, conflicts = _plan_services(conn, rule)
    skip = {s["id"] for s in conflicts}
    obs = _plan_observations(conn, rule, skip)
    events = _plan_events(conn, rule, [s["id"] for s in services])
    nos = sorted({s["train_no"] for s in services + conflicts}
                 | ({int(rule["correct_value"])} if rule["field"] == "no" else set()))
    h = hashlib.sha256(json.dumps(
        [rule["id"] if "id" in rule else None, rule["field"], rule["wrong_value"],
         rule["correct_value"], [s["id"] for s in services], [o["id"] for o in obs],
         [e["id"] for e in events]]).encode()).hexdigest()[:16]

    def brief(s):
        return {"id": s["id"], "date": s["service_date"], "train": f"{s['train_type']} {s['train_no']}",
                "sched_time": s["sched_time"], "station": s["station"],
                "from": rule["wrong_value"], "to": rule["correct_value"],
                **({"conflict": s["conflict"]} if "conflict" in s else {})}
    return {
        "rule": {k: rule.get(k) for k in ("id", "board", "field", "wrong_value", "correct_value",
                                         "station", "sched_time", "date_from", "date_to")},
        "services": {"count": len(services), "sample": [brief(s) for s in services[:SAMPLE]]},
        "conflicts": {"count": len(conflicts), "sample": [brief(s) for s in conflicts[:SAMPLE]]},
        "observations": {"count": len(obs), "captures": len({o["capture_id"] for o in obs}),
                         "sample": [{"id": o["id"], "capture_id": o["capture_id"],
                                     "row_index": o["row_index"]} for o in obs[:SAMPLE]]},
        "events": {"count": len(events)},
        "trains_refreshed": nos,
        "plan_hash": h,
        "empty": not (services or obs),
    }


@contextlib.contextmanager
def read_conn(store):
    """A connection for a dry run: read-only and separate from the live store connection
    (the ingest never waits for a scan); the store's own connection for ``:memory:``."""
    if store.path == ":memory:":
        with store._lock:
            yield store._conn
        return
    c = sqlite3.connect(f"file:{store.path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout = 5000")
    try:
        yield c
    finally:
        c.close()


def preview(store, rule: dict) -> dict:
    with read_conn(store) as c:
        return plan(c, rule)


# -- retroactive: apply / restore ------------------------------------------------------------

def _archive(conn, batch: str, table: str, row_id: int, before: dict, after: dict) -> None:
    conn.execute("INSERT INTO correction_archive(batch, table_name, row_id, data_json)"
                 " VALUES (?,?,?,?)",
                 (batch, table, row_id, json.dumps({"before": before, "after": after})))


def _new_batch(conn, rid: int) -> str:
    base = datetime.now(timezone.utc).strftime("CR%Y%m%dT%H%M%SZ") + f"-{rid}"
    batch, n = base, 1
    while conn.execute("SELECT 1 FROM correction_batches WHERE id=?", (batch,)).fetchone():
        n += 1
        batch = f"{base}.{n}"
    return batch


def _tag(pv: str | None, rid: int) -> str:
    pv = pv or ""
    t = f"{CORR_TAG}{rid}"
    return pv if re.search(re.escape(t) + r"(?![0-9])", pv) else pv + t


def apply(store, rid: int, expected_hash: str, *, actor: str = "admin",
          ip: str | None = None) -> dict:
    """Apply rule `rid` to the stored data, in one transaction with its archive. The plan
    is recomputed inside the transaction and must equal the previewed one
    (`expected_hash`); otherwise 409. Returns the batch summary."""
    from app.observations import refresh_trains

    with store._lock:
        c = store._conn
        c.execute("BEGIN IMMEDIATE")
        try:
            rule = get_rule(c, rid)
            if rule is None:
                raise CorrectionError("Regula nu există.", 404)
            if rule["status"] != "active":
                raise CorrectionError("Regula este ștearsă.", 409)
            pl = plan(c, rule)
            if pl["plan_hash"] != expected_hash:
                raise CorrectionError("Previzualizarea nu mai este valabilă (datele s-au "
                                      "schimbat). Previzualizează din nou.", 409)
            if pl["empty"]:
                raise CorrectionError("Nimic de aplicat: nicio înregistrare nu se potrivește.",
                                      409)
            services, conflicts = _plan_services(c, rule)
            sids = [s["id"] for s in services]
            skip = {s["id"] for s in conflicts}
            obs = _plan_observations(c, rule, skip)
            events = _plan_events(c, rule, sids)
            f, right = rule["field"], rule["correct_value"]
            batch = _new_batch(c, rid)
            now = _now()
            nos = set(pl["trains_refreshed"])
            has_q = _has(c, "service_quality")
            # services
            for s in services:
                before, after = {}, {}
                if f == "type":
                    before["train_type"], after["train_type"] = s["train_type"], right
                elif f == "no":
                    before["train_no"], after["train_no"] = s["train_no"], int(right)
                elif f == "time":
                    before["sched_time"], after["sched_time"] = s["sched_time"], right
                elif f == "platform":
                    before["last_platform"], after["last_platform"] = s["last_platform"], int(right)
                elif f == "delay":
                    before.update(last_delay=s["last_delay"], delay_read_at=s["delay_read_at"])
                    after.update(last_delay=int(right),
                                 delay_read_at=s["delay_read_at"] or now)
                else:  # station / operator
                    before[f], after[f] = s[f], right
                _archive(c, batch, "services", s["id"], before, after)
                c.execute("UPDATE services SET " + ", ".join(f"{k}=?" for k in after)
                          + " WHERE id=?", [*after.values(), s["id"]])
                if has_q and f in ("station", "operator"):
                    col = f + "_canonical"
                    q = c.execute(f"SELECT {col} FROM service_quality WHERE service_id=?",
                                  (s["id"],)).fetchone()
                    if q is not None and q[0] is not None:
                        _archive(c, batch, "quality", s["id"], {col: q[0]}, {col: right})
                        c.execute(f"UPDATE service_quality SET {col}=? WHERE service_id=?",
                                  (right, s["id"]))
                if has_q and f == "delay":
                    q = c.execute("SELECT delay_checked, max_delay_clean, last_delay_clean"
                                  " FROM service_quality WHERE service_id=?",
                                  (s["id"],)).fetchone()
                    if q is not None and q[0]:
                        b, a = {}, {}
                        if q[2] is not None and str(q[2]) == rule["wrong_value"]:
                            b["last_delay_clean"], a["last_delay_clean"] = q[2], int(right)
                        if q[1] is not None and (str(q[1]) == rule["wrong_value"]
                                                 or q[1] < int(right)):
                            b["max_delay_clean"], a["max_delay_clean"] = q[1], int(right)
                        if a:
                            _archive(c, batch, "quality", s["id"], b, a)
                            c.execute("UPDATE service_quality SET "
                                      + ", ".join(f"{k}=?" for k in a) + " WHERE service_id=?",
                                      [*a.values(), s["id"]])
            # observations
            for o in obs:
                before, after = {"processing_version": o["processing_version"]}, {}
                after["processing_version"] = _tag(o["processing_version"], rid)
                if f == "no":
                    before["train_no"], after["train_no"] = o["train_no"], int(right)
                elif f == "time":
                    before["sched_time"], after["sched_time"] = o["sched_time"], right
                elif f == "platform":
                    before["platform"], after["platform"] = o["platform"], int(right)
                elif f == "delay":
                    before.update(delay_min=o["delay_min"], delay_read=o["delay_read"])
                    after.update(delay_min=int(right), delay_read=1)
                else:
                    before[f], after[f] = o[f], right
                _archive(c, batch, "observations", o["id"], before, after)
                c.execute("UPDATE observations SET " + ", ".join(f"{k}=?" for k in after)
                          + " WHERE id=?", [*after.values(), o["id"]])
                if f == "no":
                    nos.add(o["train_no"])
            for e in events:
                before, after = {"old": e["old"], "new": e["new"]}, {"old": e["old"],
                                                                      "new": e["new"]}
                if e["old"] == rule["wrong_value"]:
                    after["old"] = right
                if e["new"] == rule["wrong_value"]:
                    after["new"] = right
                _archive(c, batch, "events", e["id"], before, after)
                c.execute("UPDATE events SET old=?, new=? WHERE id=?",
                          (after["old"], after["new"], e["id"]))
            refresh_trains(c, nos)
            summary = {"services": len(services), "observations": len(obs),
                       "events": len(events), "conflicts_skipped": pl["conflicts"]["count"],
                       "trains_refreshed": sorted(nos), "plan_hash": expected_hash}
            c.execute("INSERT INTO correction_batches(id, correction_id, applied_at,"
                      " applied_by, summary_json) VALUES (?,?,?,?,?)",
                      (batch, rid, now, actor, json.dumps(summary)))
            audit(c, "apply", actor=actor, ip=ip, correction_id=rid, batch=batch, detail=summary)
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
    _forget_caches(store, sids)
    return {"batch": batch, **summary}


def _forget_caches(store, service_ids) -> None:
    """The store keeps per-service state in memory; drop it for services whose stored
    values changed so the next frames start from the database."""
    with store._lock:
        for sid in service_ids:
            for name in ("_delay_read", "_votes", "_nreads"):
                getattr(store, name, {}).pop(sid, None)
            for name in ("_cand", "_cand_next"):
                d = getattr(store, name, {})
                for k in [k for k in d if k[1] == sid]:
                    d.pop(k, None)
        store._known_cache = None


_TABLE_KEY = {"services": "id", "observations": "id", "events": "id",
              "quality": "service_id"}
_TABLE_NAME = {"quality": "service_quality"}


def restore(store, batch: str, *, actor: str = "admin", ip: str | None = None) -> dict:
    """Put a batch back: every archived column returns to its value from before, but only
    on a row that still holds the corrected value (a row changed since is skipped and
    counted). The batch stays on record, marked restored."""
    from app.observations import refresh_trains

    with store._lock:
        c = store._conn
        own = not c.in_transaction
        if own:
            c.execute("BEGIN IMMEDIATE")
        try:
            b = c.execute("SELECT * FROM correction_batches WHERE id=?", (batch,)).fetchone()
            if b is None:
                raise CorrectionError("Lotul nu există.", 404)
            if b["restored_at"]:
                raise CorrectionError("Lotul a fost deja restaurat.", 409)
            out = {"services": 0, "observations": 0, "events": 0, "quality": 0, "skipped": 0}
            nos, sids = set(), []
            rows = c.execute("SELECT * FROM correction_archive WHERE batch=? ORDER BY id DESC",
                             (batch,)).fetchall()
            for r in rows:
                d = json.loads(r["data_json"])
                table, key = _TABLE_NAME.get(r["table_name"], r["table_name"]),                     _TABLE_KEY[r["table_name"]]
                cur = c.execute(f"SELECT * FROM {table} WHERE {key}=?", (r["row_id"],)).fetchone()
                if cur is None:
                    out["skipped"] += 1
                    continue
                # a row changed since the correction (another value than the one we wrote)
                # is left exactly as it is now
                if any(cur[k] != v for k, v in d["after"].items() if k != "processing_version"):
                    out["skipped"] += 1
                    continue
                cols = {k: v for k, v in d["before"].items()
                        if k != "processing_version"
                        or cur["processing_version"] == d["after"]["processing_version"]}
                if table == "services":
                    sids.append(cur["id"])
                    nos.add(cur["train_no"])
                    nos.update(v for k, v in d["before"].items() if k == "train_no")
                if table == "observations":
                    nos.update(v for k, v in d["before"].items() if k == "train_no")
                    nos.update(v for k, v in d["after"].items() if k == "train_no")
                c.execute(f"UPDATE {table} SET " + ", ".join(f"{k}=?" for k in cols)
                          + f" WHERE {key}=?", [*cols.values(), r["row_id"]])
                out[r["table_name"]] = out.get(r["table_name"], 0) + 1
            summary = json.loads(b["summary_json"] or "{}")
            nos.update(summary.get("trains_refreshed") or [])
            refresh_trains(c, nos)
            c.execute("UPDATE correction_batches SET restored_at=? WHERE id=?", (_now(), batch))
            audit(c, "restore", actor=actor, ip=ip, correction_id=b["correction_id"],
                  batch=batch, detail=out)
            if own:
                c.execute("COMMIT")
        except BaseException:
            if own and c.in_transaction:
                c.execute("ROLLBACK")
            raise
    _forget_caches(store, sids)
    return {"batch": batch, **out}


def soft_delete(store, rid: int, *, restore_batches: bool = False, actor: str = "admin",
                ip: str | None = None) -> dict:
    """Soft-delete a rule: it stops acting on new frames. A rule with applied (not yet
    restored) batches is refused (409) unless `restore_batches` puts them back first."""
    with store._lock:
        c = store._conn
        rule = get_rule(c, rid)
        if rule is None:
            raise CorrectionError("Regula nu există.", 404)
        if rule["status"] == "deleted":
            raise CorrectionError("Regula este deja ștearsă.", 409)
        live = [r[0] for r in c.execute(
            "SELECT id FROM correction_batches WHERE correction_id=? AND restored_at IS NULL"
            " ORDER BY applied_at DESC, id DESC", (rid,))]
        if live and not restore_batches:
            raise CorrectionError(
                f"Regula are {len(live)} lot(uri) aplicate retroactiv. Restaurează-le sau "
                "șterge cu restaurare.", 409)
        restored = [restore(store, b, actor=actor, ip=ip) for b in live]
        c.execute("BEGIN IMMEDIATE")
        try:
            c.execute("UPDATE corrections SET status='deleted', deleted_at=? WHERE id=?",
                      (_now(), rid))
            audit(c, "delete", actor=actor, ip=ip, correction_id=rid,
                  detail={"restored_batches": live})
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return {"id": rid, "status": "deleted", "restored": restored}
