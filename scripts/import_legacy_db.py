# © 2026 Andy217Ace
"""Reversible import of an OLD production database (another server, older schema) into
the current database, for a history that does not overlap in time.

DEFAULT IS A DRY RUN: it only reads and prints what would be imported.

    python scripts/import_legacy_db.py --source OLD.db --target /var/lib/tabela/tabela.db
    python scripts/import_legacy_db.py --source OLD.db --target ... --apply [--manifest M.json]
    python scripts/import_legacy_db.py --target ... --restore M.json          # undo

Stop the service (and the watchdog timer, which would restart it) before ``--apply`` /
``--restore``; run as the service user so the database files keep their owner.

Step 1: the source (and its -wal/-shm) is COPIED into a temporary directory and the copy
is brought to the current schema with the app's own migration (``Store.migrate``). The
source file is never opened for writing (its SHA-256 is printed before and after).

Step 2: everything is inserted into the target in ONE transaction (all or nothing).
Integer primary keys are remapped so they can never collide with the target's:

- ``captures``, ``services``, ``events``, ``observations``, ``weather_observations``,
  ``quality_periods``: new id = old id + offset, placed ABOVE the target's largest id.
  Every reference follows: observations.capture_id / service_id, events.service_id,
  service_quality.service_id / ghost_of, event_quality.event_id.
- ``runs``: new ids BELOW the target's smallest id (0 and negative). Nothing references a
  run, and the app takes "the latest successful reading" as the run with the LARGEST id
  (``Store._last_ok_ts``, ``last_ok_run``): old runs above the current ones would make the
  LIVE board look stale until the next reading.

Decisions, table by table:

- IMPORT (remapped): runs, captures, services, events, observations, service_quality,
  event_quality, weather_observations, quality_periods.
  * services still ``listed`` in the source (the old server stopped while they were on the
    board) are imported as ``gone`` with miss_count + 1, exactly what the store's
    "unseen for STALE_MIN" retirement would do on the next reading (silently, no event):
    otherwise they would appear on today's LIVE board.
  * captures: the rows are imported with ``path = NULL``; the image files stayed on the
    old disk. The app treats a NULL path as "image no longer available" (retention does the
    same: rows kept, files gone; the admin image route answers 404). The rows must exist:
    observations.capture_id is NOT NULL and references captures.
  * quality_periods: the same (start, end) already in the target with the same label/note
    is skipped (it is the constant app.quality.LOW_QUALITY_PERIODS); different content
    aborts.
- MERGE ``trains`` (catalog keyed by train number): a number missing from the target is
  inserted as stored in the source; a number already in the target is recomputed by the
  app's own ``refresh_trains`` over the combined services/observations (earliest
  first_seen, latest last_seen, union of operators/routes with summed journeys). The same
  happens to target numbers that only gain source services/observations. The catalog is a
  pure aggregate of the stored data, so there is no hand-edited field to lose. The
  manifest keeps the before/after rows of every merged number.
- SKIP:
  * ``subscriptions``: push endpoints/keys are personal data of browsers, and stale
    (a browser re-subscribes on the new server); ``follows`` only exists through a
    subscription (FK ON DELETE CASCADE), so it is skipped too.
  * ``dq_meta``: ``version`` / ``live_since`` describe THIS installation (when live
    validation started here); overriding them would change app.quality's backfill.
  * ``settings`` (admin overrides) and ``corrections`` / ``correction_*``: configuration
    and audit of the current installation (the source has none before schema v9).
  * ``purged_rows`` / ``merged_rows``: undo archives of purge_ghosts.py /
    merge_number_dups.py with the OLD ids inside their JSON; imported, a later
    ``--restore`` of those scripts would re-insert rows with wrong ids into the live
    database. They stay in the source file, which is kept.

Guards (checked by the dry run too; any hit aborts before writing): the same
(board, service_date, train_no) service or the same UNIQUE key (services, captures
image_hash, weather observed_at) in both databases, source newer than the app's schema,
column lists that differ, a source table this script does not know.

``--apply`` first writes a full online backup of the target (``sqlite3 backup``, integrity
checked) next to it, writes the manifest (``--manifest``, default next to the target:
the new id of every inserted row per table, a fingerprint of their keys, the merged
catalog rows before/after), checks ``foreign_key_check`` inside the transaction, commits,
then runs ``integrity_check`` and prints per-table counts before/after.

``--restore MANIFEST`` deletes exactly the imported rows (after checking their keys still
match the fingerprints) and puts the merged catalog rows back (a row the app changed since
is recomputed with ``refresh_trains`` instead), in one transaction, with its own backup.
Corrections applied by the admin to imported rows are not undone by it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Ordinea conteaza: parintii inaintea copiilor (cheile straine sunt verificate imediat).
IMPORT_ORDER = ("runs", "captures", "services", "events", "observations",
                "service_quality", "event_quality", "weather_observations", "quality_periods")
MERGE = ("trains",)
SKIP = {
    "subscriptions": "push endpoints = personal data of browsers, stale on a new server",
    "follows": "exists only through a subscription (not imported)",
    "dq_meta": "version/live_since of THIS installation (app.quality backfill)",
    "settings": "admin configuration of the current installation",
    "corrections": "admin rules of the current installation (schema v9)",
    "correction_batches": "audit of the current installation",
    "correction_archive": "audit of the current installation",
    "correction_audit": "audit of the current installation",
    "purged_rows": "undo archive of purge_ghosts.py with old ids inside its JSON",
    "merged_rows": "undo archive of merge_number_dups.py with old ids inside its JSON",
}
# Coloanele care identifica un rand importat (amprenta verificata la --restore).
KEYS = {
    "runs": ("ts",),
    "captures": ("image_hash",),
    "services": ("board", "service_date", "train_no", "sched_time"),
    "events": ("service_id", "ts", "kind"),
    "observations": ("capture_id", "board", "row_index", "observed_at"),
    "service_quality": (),
    "event_quality": (),
    "weather_observations": ("observed_at",),
    "quality_periods": ("start_ts", "end_ts"),
}
PK = {"service_quality": "service_id", "event_quality": "event_id"}
OFFSET_TABLES = ("captures", "services", "events", "observations", "weather_observations",
                 "quality_periods")
CHUNK = 500


class ImportAborted(Exception):
    """Nothing was written: the reason is in the message."""


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _hashes(path: Path) -> dict:
    return {p.name: _sha256(p) for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
            if p.exists()}


def _tables(conn, schema: str = "main") -> list[str]:
    return [r[0] for r in conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _cols(conn, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def counts(conn, schema: str = "main") -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {schema}.{t}").fetchone()[0]
            for t in _tables(conn, schema)}


def _one(conn, sql: str, args=()):
    return conn.execute(sql, args).fetchone()[0]


# -- pasul 1: copia sursei, adusa la schema curenta ------------------------------------

def prepare_source(source: Path, work: Path) -> tuple[Path, int]:
    """Copiaza sursa (+ -wal/-shm) in `work` si o migreaza cu Store.migrate. Intoarce
    (copia, versiunea originala). Originalul nu e deschis niciodata de sqlite."""
    from app.store import SCHEMA_VERSION, Store

    copy = work / "source-copy.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{source}{suffix}")
        if p.exists():
            shutil.copy2(p, f"{copy}{suffix}")
    probe = sqlite3.connect(copy)
    try:
        version = probe.execute("PRAGMA user_version").fetchone()[0]
        ok = probe.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        probe.close()
    if ok != "ok":
        raise ImportAborted(f"source copy fails integrity_check: {ok}")
    if version > SCHEMA_VERSION:
        raise ImportAborted(f"source schema v{version} is newer than this app (v{SCHEMA_VERSION})")
    if version < 1:
        raise ImportAborted("source has no schema version: not a Tabela database")
    # migrarea face un backup pre-migrare (app.dbbackup): il tinem in directorul temporar
    old_env = os.environ.get("BACKUP_DIR")
    os.environ["BACKUP_DIR"] = str(work / "backups")
    try:
        st = Store(str(copy))
        try:
            st.migrate()
        finally:
            st.close()
    finally:
        if old_env is None:
            os.environ.pop("BACKUP_DIR", None)
        else:
            os.environ["BACKUP_DIR"] = old_env
    c = sqlite3.connect(copy)
    try:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.execute("PRAGMA journal_mode=DELETE")  # citibila si dintr-o conexiune read-only
        if c.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ImportAborted("source copy did not reach the current schema")
    finally:
        c.close()
    return copy, version


# -- planul (dry run si apply) -----------------------------------------------------------

def _offsets(conn) -> dict[str, int]:
    off = {}
    for t in OFFSET_TABLES:
        src_min = _one(conn, f"SELECT MIN(id) FROM src.{t}")
        tgt_max = _one(conn, f"SELECT COALESCE(MAX(id), 0) FROM main.{t}")
        off[t] = 0 if src_min is None else tgt_max + 1 - src_min
    # runs: SUB cele existente (cel mai mare id = ultima citire, vezi docstring)
    src_max = _one(conn, "SELECT MAX(id) FROM src.runs")
    tgt_min = _one(conn, "SELECT MIN(id) FROM main.runs")
    off["runs"] = 0 if src_max is None else min(tgt_min if tgt_min is not None else 1, 1) - 1 - src_max
    return off


def _exprs(table: str, off: dict[str, int]) -> dict[str, str]:
    """Coloana -> expresia SQL (peste src.<table>) cu id-urile remapate."""
    s_ids = "(SELECT id FROM src.services)"
    if table == "runs":
        return {"id": f"id + {off['runs']}"}
    if table == "captures":
        return {"id": f"id + {off['captures']}", "path": "NULL"}
    if table == "services":
        return {"id": f"id + {off['services']}",
                "status": "CASE WHEN status='listed' THEN 'gone' ELSE status END",
                "miss_count": "miss_count + (status='listed')"}
    if table == "events":
        return {"id": f"id + {off['events']}", "service_id": f"service_id + {off['services']}"}
    if table == "observations":
        return {"id": f"id + {off['observations']}",
                "capture_id": f"capture_id + {off['captures']}",
                "service_id": f"CASE WHEN service_id IN {s_ids}"
                              f" THEN service_id + {off['services']} END"}
    if table == "service_quality":
        return {"service_id": f"service_id + {off['services']}",
                "ghost_of": f"CASE WHEN ghost_of IN {s_ids} THEN ghost_of + {off['services']} END"}
    if table == "event_quality":
        return {"event_id": f"event_id + {off['events']}"}
    if table in ("weather_observations", "quality_periods"):
        return {"id": f"id + {off[table]}"}
    raise KeyError(table)


def _source_where(table: str) -> str:
    if table == "quality_periods":  # aceeasi perioada, acelasi continut: exista deja
        return (" WHERE NOT EXISTS (SELECT 1 FROM main.quality_periods q"
                " WHERE q.start_ts = src.quality_periods.start_ts"
                " AND q.end_ts = src.quality_periods.end_ts)")
    return ""


def _examples(conn, sql: str, n: int = 10) -> list:
    return [list(r) for r in conn.execute(sql + f" LIMIT {n}")]


def plan(conn) -> dict:
    """Ce s-ar importa, cu verificarile. `conn` = tinta (main) + copia sursei (src)."""
    src_tables, tgt_tables = set(_tables(conn, "src")), set(_tables(conn, "main"))
    problems: list[str] = []
    unknown = sorted(src_tables - set(IMPORT_ORDER) - set(MERGE) - set(SKIP))
    if unknown:
        problems.append(f"source tables this script does not know: {unknown}")
    for t in (*IMPORT_ORDER, *MERGE):
        if t not in src_tables or t not in tgt_tables:
            problems.append(f"table {t} missing in {'source' if t not in src_tables else 'target'}")
        elif set(_cols(conn, t, "src")) != set(_cols(conn, t, "main")):
            problems.append(f"table {t}: columns differ between source and target")
    if problems:
        return {"problems": problems}

    collisions: dict[str, dict] = {}

    def collide(name: str, count_sql: str, ex_sql: str) -> None:
        n = _one(conn, count_sql)
        if n:
            collisions[name] = {"count": n, "examples": _examples(conn, ex_sql)}

    j = (" FROM src.services s JOIN main.services t ON t.board = s.board"
         " AND t.service_date = s.service_date AND t.train_no = s.train_no")
    collide("services (board, service_date, train_no)", "SELECT COUNT(*)" + j,
            "SELECT s.board, s.service_date, s.train_no, s.sched_time, t.sched_time" + j)
    j = " FROM src.captures s JOIN main.captures t ON t.image_hash = s.image_hash"
    collide("captures.image_hash", "SELECT COUNT(*)" + j, "SELECT s.id, t.id, s.image_hash" + j)
    j = (" FROM src.weather_observations s JOIN main.weather_observations t"
         " ON t.observed_at = s.observed_at")
    collide("weather_observations.observed_at", "SELECT COUNT(*)" + j,
            "SELECT s.observed_at" + j)
    j = (" FROM src.quality_periods s JOIN main.quality_periods t ON t.start_ts = s.start_ts"
         " AND t.end_ts = s.end_ts WHERE t.label IS NOT s.label OR t.note IS NOT s.note")
    collide("quality_periods (start_ts, end_ts) with different content", "SELECT COUNT(*)" + j,
            "SELECT s.start_ts, s.end_ts, s.label, t.label" + j)

    off = _offsets(conn)
    tables: dict[str, dict] = {}
    for t in IMPORT_ORDER:
        n = _one(conn, f"SELECT COUNT(*) FROM src.{t}{_source_where(t)}")
        pk = PK.get(t, "id")
        lo, hi = conn.execute(f"SELECT MIN({pk}), MAX({pk}) FROM src.{t}").fetchone()
        o = off.get(t) if t in off else off["services" if t == "service_quality" else "events"]
        tables[t] = {"action": "import", "rows": n,
                     "new_id_range": None if lo is None else [lo + o, hi + o]}
    tables["quality_periods"]["already_present"] = _one(
        conn, "SELECT COUNT(*) FROM src.quality_periods") - tables["quality_periods"]["rows"]
    tables["services"]["listed_retired_as_gone"] = _one(
        conn, "SELECT COUNT(*) FROM src.services WHERE status='listed'")
    tables["captures"]["image_paths_cleared"] = _one(
        conn, "SELECT COUNT(*) FROM src.captures WHERE path IS NOT NULL")
    tables["service_quality"]["ghost_of_remapped"] = _one(
        conn, "SELECT COUNT(*) FROM src.service_quality WHERE ghost_of IN"
        " (SELECT id FROM src.services)")
    new_nos, refresh_nos = trains_plan(conn)
    tables["trains"] = {"action": "merge", "rows_inserted": len(new_nos),
                        "rows_recomputed": len(refresh_nos),
                        "recomputed_examples": refresh_nos[:15]}
    for t in sorted(src_tables & set(SKIP)):
        tables[t] = {"action": "skip", "rows": _one(conn, f"SELECT COUNT(*) FROM src.{t}"),
                     "reason": SKIP[t]}
    src_days = [r[0] for r in conn.execute(
        "SELECT DISTINCT service_date FROM src.services ORDER BY 1")]
    tgt_days = {r[0] for r in conn.execute("SELECT DISTINCT service_date FROM main.services")}
    warnings = []
    shared_days = sorted(set(src_days) & tgt_days)
    if shared_days:
        warnings.append(f"service dates present in both databases: {shared_days}")
    return {"offsets": off, "tables": tables, "collisions": collisions,
            "source_service_dates": src_days[:1] + src_days[-1:],
            "warnings": warnings, "problems": []}


def trains_plan(conn) -> tuple[list[int], list[int]]:
    """(numere noi in catalog, numere existente de recalculat cu refresh_trains)."""
    new = [r[0] for r in conn.execute(
        "SELECT train_no FROM src.trains WHERE train_no NOT IN (SELECT train_no FROM main.trains)"
        " ORDER BY train_no")]
    refresh = [r[0] for r in conn.execute(
        "SELECT train_no FROM main.trains WHERE train_no IN ("
        " SELECT train_no FROM src.trains UNION SELECT train_no FROM src.services"
        " UNION SELECT train_no FROM src.observations WHERE train_no IS NOT NULL"
        " AND validation_state IN ('ok', 'uncertain')) ORDER BY train_no")]
    return new, refresh


# -- amprente pentru --restore ------------------------------------------------------------

def _fingerprint(conn, table: str, ids: list[int]) -> str:
    pk = PK.get(table, "id")
    cols = ", ".join((pk, *KEYS[table]))
    h = hashlib.sha256()
    for part in _chunks(sorted(ids)):
        for r in conn.execute(f"SELECT {cols} FROM main.{table} WHERE {pk} IN ({_in(part)})"
                              f" ORDER BY {pk}"):
            h.update(json.dumps(list(r), ensure_ascii=False).encode())
            h.update(b"\n")
    return h.hexdigest()


def _chunks(ids: list[int]):
    for i in range(0, len(ids), CHUNK):
        yield ids[i:i + CHUNK]


def _in(ids) -> str:
    return ",".join(str(int(i)) for i in ids) or "NULL"


def _row(conn, train_no: int) -> dict | None:
    r = conn.execute("SELECT * FROM main.trains WHERE train_no=?", (train_no,)).fetchone()
    return None if r is None else dict(r)


# -- backup (ca merge_number_dups.backup, langa tinta) -----------------------------------

def _new_path(directory: Path, prefix: str, suffix: str) -> Path:
    """Nume nou, creat exclusiv (open 'x'): nu suprascrie niciodata un fisier existent."""
    stamp = f"{datetime.now():%Y%m%d-%H%M%S-%f}"
    n = 0
    while True:
        p = directory / f"{prefix}{stamp}{'' if n == 0 else f'_{n}'}{suffix}"
        try:
            with open(p, "x"):
                pass
            return p
        except FileExistsError:
            n += 1


def backup(db: Path, backup_dir: Path, prefix: str) -> str:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = _new_path(backup_dir, f"{db.stem}-{prefix}-", ".db")
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        src.close()
        dst.close()
    if ok != "ok":
        raise ImportAborted(f"backup integrity check failed: {ok}")
    os.chmod(dest, 0o600)
    return str(dest)


def _checks(conn) -> dict:
    return {"integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_check": [list(r) for r in conn.execute("PRAGMA foreign_key_check")]}


# -- apply ------------------------------------------------------------------------------

def apply(conn, manifest_path: Path, meta: dict) -> dict:
    """Importul intr-o singura tranzactie. Manifestul e scris (temporar) inainte de COMMIT
    si mutat la locul lui dupa; un esec lasa tinta neschimbata."""
    from app.observations import refresh_trains

    tmp = Path(f"{manifest_path}.tmp")
    conn.execute("BEGIN IMMEDIATE")
    try:
        pl = plan(conn)  # recalculat in tranzactia de scriere
        if pl["problems"] or pl["collisions"]:
            raise ImportAborted(json.dumps({"problems": pl["problems"],
                                            "collisions": pl["collisions"]},
                                           ensure_ascii=False))
        off = pl["offsets"]
        man: dict = {"kind": "tabela-import-legacy", "version": 1, **meta,
                     "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "offsets": off, "tables": {}, "trains": {}}
        inserted: dict[str, int] = {}
        for t in IMPORT_ORDER:
            cols = _cols(conn, t, "main")
            ex = _exprs(t, off)
            pk = PK.get(t, "id")
            where = _source_where(t)
            src_pk = ex.get(pk, pk)
            ids = [r[0] for r in conn.execute(f"SELECT {src_pk} FROM src.{t}{where}")]
            cur = conn.execute(
                f"INSERT INTO main.{t}({', '.join(cols)})"
                f" SELECT {', '.join(ex.get(c, c) for c in cols)} FROM src.{t}{where}")
            if cur.rowcount != len(ids):
                raise ImportAborted(f"{t}: inserted {cur.rowcount} rows, expected {len(ids)}")
            inserted[t] = len(ids)
            man["tables"][t] = {"pk": pk, "ids": sorted(ids)}
        new_nos, refresh_nos = trains_plan(conn)
        before = {no: _row(conn, no) for no in refresh_nos}
        tcols = _cols(conn, "trains", "main")
        if new_nos:
            conn.execute(f"INSERT INTO main.trains({', '.join(tcols)})"
                         f" SELECT {', '.join(tcols)} FROM src.trains"
                         f" WHERE train_no IN ({_in(new_nos)})")
        refresh_trains(conn, refresh_nos)
        man["trains"] = {
            "inserted": [{"train_no": no, "after": _row(conn, no)} for no in new_nos],
            "merged": [{"train_no": no, "before": before[no], "after": _row(conn, no)}
                       for no in refresh_nos]}
        for t in IMPORT_ORDER:
            man["tables"][t]["fingerprint"] = _fingerprint(conn, t, man["tables"][t]["ids"])
        fk = [list(r) for r in conn.execute("PRAGMA foreign_key_check")]
        if fk:
            raise ImportAborted(f"foreign_key_check failed: {fk[:20]}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, manifest_path)
    os.chmod(manifest_path, 0o600)
    return {"inserted": inserted, "trains_inserted": len(new_nos),
            "trains_merged": len(refresh_nos)}


# -- restore ----------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> dict:
    try:
        man = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ImportAborted(f"cannot read manifest {manifest_path}: {e}") from None
    if not isinstance(man, dict) or man.get("kind") != "tabela-import-legacy":
        raise ImportAborted(f"{manifest_path} is not an import manifest")
    if man.get("restored_at"):
        raise ImportAborted(f"this import was already restored at {man['restored_at']}")
    return man


def restore(conn, manifest_path: Path) -> dict:
    from app.observations import refresh_trains

    man = load_manifest(manifest_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for t in IMPORT_ORDER:  # randurile inca sunt cele importate?
            e = man["tables"][t]
            have = _one(conn, f"SELECT COUNT(*) FROM main.{t} WHERE {e['pk']} IN"
                              f" ({_in(e['ids'])})") if e["ids"] else 0
            if have != len(e["ids"]) or _fingerprint(conn, t, e["ids"]) != e["fingerprint"]:
                raise ImportAborted(
                    f"{t}: the imported rows changed or are missing ({have} of"
                    f" {len(e['ids'])} present); nothing deleted. Use the backup made"
                    f" before --apply.")
        deleted: dict[str, int] = {}
        for t in reversed(IMPORT_ORDER):
            e = man["tables"][t]
            n = 0
            for part in _chunks(e["ids"]):
                n += conn.execute(f"DELETE FROM main.{t} WHERE {e['pk']} IN ({_in(part)})"
                                  ).rowcount
            deleted[t] = n
        tcols = None
        trains = {"deleted": 0, "reverted": 0, "recomputed": 0}
        for item in man["trains"]["inserted"]:
            no = item["train_no"]
            if _row(conn, no) == item["after"]:  # neatins de aplicatie: era doar al nostru
                trains["deleted"] += conn.execute(
                    "DELETE FROM main.trains WHERE train_no=?", (no,)).rowcount
            else:  # aplicatia l-a vazut intre timp: recalculat din datele ramase
                refresh_trains(conn, [no])
                trains["recomputed"] += 1
        for item in man["trains"]["merged"]:
            no, b = item["train_no"], item["before"]
            if _row(conn, no) == item["after"] and b is not None:
                tcols = tcols or [c for c in b if c != "train_no"]
                conn.execute("UPDATE main.trains SET " + ", ".join(f"{c}=?" for c in tcols)
                             + " WHERE train_no=?", [b[c] for c in tcols] + [no])
                trains["reverted"] += 1
            else:
                refresh_trains(conn, [no])
                trains["recomputed"] += 1
        fk = [list(r) for r in conn.execute("PRAGMA foreign_key_check")]
        if fk:
            raise ImportAborted(f"foreign_key_check failed: {fk[:20]}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    man["restored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = Path(f"{manifest_path}.tmp")
    tmp.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, manifest_path)
    return {"deleted": deleted, "trains": trains}


# -- main -------------------------------------------------------------------------------

def _connect(target: Path, write: bool):
    conn = (sqlite3.connect(target, isolation_level=None) if write
            else sqlite3.connect(f"file:{target}?mode=ro", uri=True, isolation_level=None))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def run(source: Path | None, target: Path, *, do_apply: bool = False,
        restore_manifest: Path | None = None, manifest: Path | None = None,
        backup_dir: Path | None = None, work_dir: Path | None = None) -> dict:
    from app.store import SCHEMA_VERSION

    if not target.is_file():
        raise ImportAborted(f"no database at {target}")
    backup_dir = backup_dir or target.parent
    rep: dict = {"target": str(target)}
    if restore_manifest is not None:
        load_manifest(restore_manifest)  # inainte de backup: un manifest gresit nu scrie nimic
        conn = _connect(target, True)
        try:
            rep["mode"] = "restore"
            rep["counts_before"] = counts(conn)
            rep["backup"] = backup(target, backup_dir, "before-legacy-restore")
            t0 = time.monotonic()
            rep["restored"] = restore(conn, restore_manifest)
            rep["duration_s"] = round(time.monotonic() - t0, 3)
            rep["counts_after"] = counts(conn)
            rep["checks"] = _checks(conn)
        finally:
            conn.close()
        return rep

    if source is None or not source.is_file():
        raise ImportAborted(f"no source database at {source}")
    if source.resolve() == target.resolve():
        raise ImportAborted("source and target are the same file")
    rep.update(mode="apply" if do_apply else "dry-run", source=str(source))
    rep["source_sha256_before"] = _hashes(source)
    own_work = work_dir is None
    work = Path(tempfile.mkdtemp(prefix="import-legacy-")) if own_work else work_dir
    try:
        copy, version = prepare_source(source, work)
        rep["source_schema"] = {"original": version, "migrated_copy": SCHEMA_VERSION}
        conn = _connect(target, do_apply)
        try:
            tv = _one(conn, "PRAGMA user_version")
            if tv != SCHEMA_VERSION:
                raise ImportAborted(f"target schema v{tv}, this app expects v{SCHEMA_VERSION}")
            conn.execute("ATTACH DATABASE ? AS src", (str(copy),))
            rep["counts_source_copy"] = counts(conn, "src")
            rep["counts_before"] = counts(conn)
            pl = plan(conn)
            rep["plan"] = pl
            if pl["problems"]:
                raise ImportAborted("; ".join(pl["problems"]))
            if pl["collisions"]:
                raise ImportAborted("natural-key collisions between source and target (already"
                                    " imported?): " + json.dumps(pl["collisions"],
                                                                 ensure_ascii=False))
            if do_apply:
                if manifest is not None and manifest.exists():
                    raise ImportAborted(f"manifest {manifest} already exists")
                rep["backup"] = backup(target, backup_dir, "before-legacy-import")
                placeholder = manifest is None
                manifest = manifest or _new_path(
                    target.parent, "import-legacy-", ".manifest.json")
                rep["manifest"] = str(manifest)
                meta = {"source": str(source), "source_sha256": rep["source_sha256_before"],
                        "target": str(target), "backup": rep["backup"]}
                t0 = time.monotonic()
                try:
                    rep["applied"] = apply(conn, Path(manifest), meta)
                except BaseException:
                    if placeholder:  # numele rezervat, gol: nu a fost aplicat nimic
                        Path(manifest).unlink(missing_ok=True)
                    raise
                rep["duration_s"] = round(time.monotonic() - t0, 3)
                conn.execute("DETACH DATABASE src")
                rep["counts_after"] = counts(conn)
                rep["checks"] = _checks(conn)
            else:
                proj = dict(rep["counts_before"])
                for t, d in pl["tables"].items():
                    if d["action"] == "import":
                        proj[t] = proj.get(t, 0) + d["rows"]
                    elif d["action"] == "merge":
                        proj[t] = proj.get(t, 0) + d["rows_inserted"]
                rep["counts_after_projected"] = proj
        finally:
            conn.close()
    finally:
        if own_work:
            shutil.rmtree(work, ignore_errors=True)  # copia contine date private
        rep["source_sha256_after"] = _hashes(source)
        if rep["source_sha256_after"] != rep["source_sha256_before"]:
            rep["source_changed"] = True
    return rep


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", type=Path, help="old database (never modified)")
    p.add_argument("--target", type=Path, required=True, help="current database")
    p.add_argument("--apply", action="store_true", help="import (reversible with --restore)")
    p.add_argument("--restore", type=Path, metavar="MANIFEST", help="undo an applied import")
    p.add_argument("--manifest", type=Path, help="with --apply: where to write the manifest"
                   " (default: next to the target, timestamped)")
    p.add_argument("--backup-dir", type=Path, help="where the pre-write backup goes"
                   " (default: next to the target)")
    p.add_argument("--work-dir", type=Path, help="temporary directory for the source copy")
    a = p.parse_args(argv)
    if a.apply and a.restore:
        p.error("--apply and --restore are exclusive")
    if not a.restore and not a.source:
        p.error("--source is required (except with --restore)")
    try:
        rep = run(a.source, a.target, do_apply=a.apply, restore_manifest=a.restore,
                  manifest=a.manifest, backup_dir=a.backup_dir, work_dir=a.work_dir)
    except ImportAborted as e:
        print(f"ABORTED, nothing written: {e}", file=sys.stderr)
        return 2
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    bad = rep.get("checks") and (rep["checks"]["integrity_check"] != "ok"
                                 or rep["checks"]["foreign_key_check"])
    return 1 if bad or rep.get("source_changed") else 0


if __name__ == "__main__":
    sys.exit(main())
