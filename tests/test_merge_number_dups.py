# © 2026 Andy217Ace
"""scripts/merge_number_dups.py on a synthetic database (RE 9209 / 92011, aliases, ...)."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from app.store import Store

SPEC = importlib.util.spec_from_file_location(
    "merge_number_dups",
    Path(__file__).resolve().parent.parent / "scripts" / "merge_number_dups.py")
md = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(md)

D1, D2, D3 = "2026-10-21", "2026-10-22", "2026-10-23"


def _t(day, hh, mm=0):
    return f"{day}T{hh:02d}:{mm:02d}:00+03:00"


def _svc(c, board, day, no, station, sched, fs, ls, *, ttype="RE", status="gone",
         platform=None, delay=0, delay_read_at=None):
    return c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, last_delay, last_platform, status, station_raw,"
        " operator_raw, last_read, delay_read_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (board, day, ttype, no, station, "CFR", sched, fs, ls, delay, platform, status,
         station, "", delay_read_at, delay_read_at)).lastrowid


def _obs(c, sid, board, n, day, hh, *, capture=None, station="PITESTI", no=None):
    """n observations of service sid, one new capture each unless `capture` is given."""
    for k in range(n):
        cap = capture if capture is not None else c.execute(
            "INSERT INTO captures(captured_at, image_hash, ok)"
            " VALUES (?, ?, 1)", (_t(day, hh, k), f"h{sid}-{k}-{day}")).lastrowid
        c.execute(
            "INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
            " train_no, station, validation_state, processing_version)"
            " VALUES (?,?,?,?,?,?,?, 'ok', 't')",
            (cap, sid, board, 0, _t(day, hh, k), no, station))


def _ev(c, sid, day, hh, kind="delay", old="0", new="5"):
    return c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,?,?,?)",
                     (sid, _t(day, hh), kind, old, new)).lastrowid


def _db(tmp_path):
    db = tmp_path / "m.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    ids = {}
    # RE 9209 is a real train (two days); 92011 is its misread on D2 (disjoint frames)
    ids["real_d1"] = _svc(c, "departure", D1, 9209, "PITESTI", "14:36", _t(D1, 13),
                          _t(D1, 14, 40), platform=3)
    _obs(c, ids["real_d1"], "departure", 3, D1, 13, no=9209)
    ids["real"] = _svc(c, "departure", D2, 9209, "PITESTI", "14:36", _t(D2, 13, 5),
                       _t(D2, 14, 30), platform=None)
    _obs(c, ids["real"], "departure", 6, D2, 13, no=9209)
    ids["dup"] = _svc(c, "departure", D2, 92011, "PITESTI", "14:36", _t(D2, 14, 35),
                      _t(D2, 14, 55), platform=4, delay=10, delay_read_at=_t(D2, 14, 50))
    _obs(c, ids["dup"], "departure", 2, D2, 14, no=92011)
    ids["ev_dup"] = _ev(c, ids["dup"], D2, 14, "delay", "0", "10")
    ids["ev_real"] = _ev(c, ids["real"], D2, 13)
    # two real trains in the SAME frame (never merged): 1581 and 15811
    ids["a"] = _svc(c, "departure", D2, 1581, "CONSTANTA", "08:17", _t(D2, 7), _t(D2, 8),
                    ttype="IR")
    ids["b"] = _svc(c, "departure", D2, 15811, "CONSTANTA", "08:17", _t(D2, 7), _t(D2, 8),
                    ttype="IR")
    shared = c.execute("INSERT INTO captures(captured_at, image_hash, ok)"
                       " VALUES (?, 'shared', 1)", (_t(D2, 7, 30),)).lastrowid
    _obs(c, ids["a"], "departure", 1, D2, 7, capture=shared, station="CONSTANTA")
    _obs(c, ids["b"], "departure", 1, D2, 7, capture=shared, station="CONSTANTA")
    # equal-length "1" substitution and a truncated number: listed only
    ids["sub_w"] = _svc(c, "arrival", D2, 7017, "KIEV - CHISINAU", "06:38", _t(D2, 5),
                        _t(D2, 6), ttype="IRN")
    ids["sub_l"] = _svc(c, "arrival", D2, 7011, "KIEV -CHISINAU", "06:38", _t(D2, 5),
                        _t(D2, 6), ttype="IRN")
    _obs(c, ids["sub_w"], "arrival", 3, D2, 5, station="KIEV - CHISINAU")
    _obs(c, ids["sub_l"], "arrival", 1, D2, 5, station="KIEV -CHISINAU")
    ids["trunc_w"] = _svc(c, "departure", D2, 5019, "BUZAU", "17:08", _t(D2, 16), _t(D2, 17),
                          ttype="R")
    ids["trunc_l"] = _svc(c, "departure", D2, 19, "BUZAU", "17:08", _t(D2, 16), _t(D2, 17),
                          ttype="R")
    _obs(c, ids["trunc_w"], "departure", 2, D2, 16, station="BUZAU")
    _obs(c, ids["trunc_l"], "departure", 1, D2, 16, station="BUZAU")
    # R 5019 runs on 2 days, but R 19 also runs ALONE on D3: it has a life of its own,
    # so the truncation stays listed (the strict rule)
    ids["trunc_w1"] = _svc(c, "departure", D1, 5019, "BUZAU", "17:08", _t(D1, 16),
                           _t(D1, 17), ttype="R")
    _obs(c, ids["trunc_w1"], "departure", 1, D1, 16, station="BUZAU")
    ids["trunc_alone"] = _svc(c, "departure", D3, 19, "BUZAU", "17:08", _t(D3, 16),
                              _t(D3, 17), ttype="R")
    _obs(c, ids["trunc_alone"], "departure", 1, D3, 16, station="BUZAU")
    # alias + merge across the alias: IRN 401 (KIEV - CHISINAU) / 4011 (KIEV -CHISINAU)
    ids["iw"] = _svc(c, "arrival", D3, 401, "KIEV - CHISINAU", "06:38", _t(D3, 5),
                     _t(D3, 6), ttype="IRN")
    ids["il"] = _svc(c, "arrival", D3, 4011, "KIEV -CHISINAU", "06:38", _t(D3, 5),
                     _t(D3, 6), ttype="IRN")
    _obs(c, ids["iw"], "arrival", 4, D3, 5, station="KIEV - CHISINAU")
    _obs(c, ids["il"], "arrival", 1, D3, 5, station="KIEV -CHISINAU")
    ids["vd"] = _svc(c, "arrival", D3, 1658, "VATRA DORNEI BA", "05:35", _t(D3, 4),
                     _t(D3, 5), ttype="IRN")
    _obs(c, ids["vd"], "arrival", 2, D3, 4, station="VATRA DORNEI BA")
    # divergent scheduled time: 16593 at 03:00 and 08:00, never in one frame
    ids["t1"] = _svc(c, "departure", D2, 16593, "BRASOV", "03:00", _t(D2, 2), _t(D2, 3),
                     ttype="IR")
    ids["t2"] = _svc(c, "departure", D2, 16593, "BRASOV", "08:00", _t(D2, 7), _t(D2, 8),
                     ttype="IR")
    _obs(c, ids["t1"], "departure", 1, D2, 2, station="BRASOV")
    _obs(c, ids["t2"], "departure", 4, D2, 7, station="BRASOV")
    # a ghost is never touched here (purge_ghosts.py owns it)
    ids["ghost"] = _svc(c, "departure", D2, 92111, "PITESTI", "14:36", _t(D2, 14),
                        _t(D2, 14, 1))
    c.execute("INSERT INTO service_quality(service_id, ghost, ghost_reason, updated_at)"
              " VALUES (?, 1, 'short', 'x')", (ids["ghost"],))
    c.execute("INSERT INTO service_quality(service_id, station_canonical, updated_at)"
              " VALUES (?, 'KIEV -CHISINAU', 'x')", (ids["il"],))
    c.execute("INSERT INTO service_quality(service_id, station_canonical, updated_at)"
              " VALUES (?, 'KIEV -CHISINAU', 'x')", (ids["sub_l"],))
    for no in (9209, 92011, 401, 4011, 1658, 16593, 777):  # 777: unrelated orphan row
        c.execute("INSERT OR IGNORE INTO trains(train_no, journeys, observations)"
                  " VALUES (?, 1, 1)", (no,))
    s.close()
    return db, ids


def _dump(db):
    c = sqlite3.connect(db)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
           for t in ("services", "events", "service_quality", "observations", "trains")}
    c.close()
    return out


def _run(args, capsys):
    assert md.main(args) == 0
    return json.loads(capsys.readouterr().out)


def test_noise_cost_rules():
    cases = [(9209, 92011, True), (925, 92511, True), (1581, 45811, True), (109, 10109, True),
             (401, 4011, True), (7929, 79211, True), (1581, 1583, False),
             (1581, 1581, False), (5019, 19, False), (7011, 7017, False),  # equal length
             (92, 9211, False), (1000, 1111, False)]
    for a, b, want in cases:
        assert md.is_noise_pair(a, b) is want, (a, b)
    assert md.noise_cost("7011", "7017") == 1  # equal length: listed, not merged


def test_dry_run_is_default_and_writes_nothing(tmp_path, capsys):
    db, ids = _db(tmp_path)
    before = _dump(db)
    rep = _run(["--db", str(db), "--min-age-min", "0"], capsys)
    assert rep["mode"] == "dry-run"
    merged = {(m["loser"]["id"], m["winner"]["id"]) for m in rep["merge"]["list"]}
    # 92011 -> 9209 (the real train runs on 2 days), 4011 -> 401 (across the alias)
    assert merged == {(ids["dup"], ids["real"]), (ids["il"], ids["iw"])}
    assert rep["merge"]["services_affected"] == 2
    assert rep["merge"]["observations_to_move"] == 2 + 1
    assert rep["merge"]["by_number_pair"] == {"RE 92011 -> RE 9209": 1, "IRN 4011 -> IRN 401": 1}
    # never merged: same frame, equal-length substitution, truncation, ghost
    why = {(x["winner"]["id"], x["loser"]["id"]): x["why_not_merged"]
           for x in rep["listed_not_merged"]}
    assert "same frame" in why[(ids["a"], ids["b"])] or "same frame" in why[(ids["b"], ids["a"])]
    assert "equal-length" in why[(ids["sub_w"], ids["sub_l"])]
    assert "truncated" in why[(ids["trunc_w"], ids["trunc_l"])]
    assert "lives alone" in why[(ids["trunc_w"], ids["trunc_l"])] and D3 in why[
        (ids["trunc_w"], ids["trunc_l"])]
    assert all(ids["ghost"] not in (x["winner"]["id"], x["loser"]["id"])
               for x in rep["merge"]["list"] + rep["listed_not_merged"])
    assert rep["aliases"]["KIEV -CHISINAU"] == {"to": "KIEV - CHISINAU", "services": 2,
                                                "observations": 2, "service_quality": 2}
    assert rep["aliases"]["VATRA DORNEI BA"]["services"] == 1
    div = {x["train_no"]: x for x in rep["divergent_sched_listed_only"]}
    assert set(div) == {16593} and len(div[16593]["services"]) == 2
    assert "never in one frame" in div[16593]["evidence"] and div[16593]["decision"] == "user"
    assert _dump(db) == before
    assert "merged_rows" not in {r[0] for r in sqlite3.connect(db).execute(
        "SELECT name FROM sqlite_master")}


def test_recent_services_are_deferred(tmp_path, capsys):
    db, ids = _db(tmp_path)
    c = sqlite3.connect(db)
    c.execute("UPDATE services SET status='listed' WHERE id=?", (ids["dup"],))
    c.commit()
    c.close()
    rep = _run(["--db", str(db), "--min-age-min", "0"], capsys)
    assert {m["loser"]["id"] for m in rep["merge"]["list"]} == {ids["il"]}
    assert any("still on the board" in x["why_not_merged"] for x in rep["listed_not_merged"])
    # default 60 min: everything above is old, so the same two stay
    rep = _run(["--db", str(db)], capsys)
    assert {m["loser"]["id"] for m in rep["merge"]["list"]} == {ids["il"]}


def test_apply_needs_backup_dir(tmp_path):
    db, _ = _db(tmp_path)
    with pytest.raises(SystemExit):
        md.main(["--db", str(db), "--apply"])
    with pytest.raises(SystemExit):
        md.main(["--db", str(db), "--apply", "--restore"])


def test_apply_merges_archives_is_idempotent_and_restores(tmp_path, capsys):
    db, ids = _db(tmp_path)
    before = _dump(db)
    rep = _run(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
                "--min-age-min", "0"], capsys)
    assert rep["applied"]["services_merged"] == 2 and rep["batch"].startswith("MD")
    assert Path(rep["backup"]).exists()
    bk = sqlite3.connect(rep["backup"])
    assert bk.execute("SELECT COUNT(*) FROM services").fetchone()[0] == len(before["services"])
    bk.close()
    c = sqlite3.connect(db)
    left = {r[0] for r in c.execute("SELECT id FROM services")}
    assert ids["dup"] not in left and ids["il"] not in left
    assert {ids["real"], ids["iw"], ids["a"], ids["b"], ids["ghost"]} <= left
    # observations moved (kept, merged), events of the loser archived and gone
    assert c.execute("SELECT COUNT(*) FROM observations WHERE service_id=?",
                     (ids["real"],)).fetchone()[0] == 6 + 2
    assert not c.execute("SELECT 1 FROM events WHERE id=?", (ids["ev_dup"],)).fetchone()
    assert c.execute("SELECT 1 FROM events WHERE id=?", (ids["ev_real"],)).fetchone()
    # the winner widened its life and took the platform/delay it never had
    w = c.execute("SELECT first_seen, last_seen, last_platform, last_delay, delay_read_at"
                  " FROM services WHERE id=?", (ids["real"],)).fetchone()
    assert w == (_t(D2, 13, 5), _t(D2, 14, 55), 4, 10, _t(D2, 14, 50))
    # raw observation numbers untouched
    assert c.execute("SELECT COUNT(*) FROM observations WHERE train_no=92011").fetchone()[0] == 2
    # aliases applied everywhere
    assert not c.execute("SELECT 1 FROM services WHERE station IN"
                         " ('KIEV -CHISINAU', 'VATRA DORNEI BA')").fetchone()
    assert not c.execute("SELECT 1 FROM observations WHERE station IN"
                         " ('KIEV -CHISINAU', 'VATRA DORNEI BA')").fetchone()
    assert not c.execute("SELECT 1 FROM service_quality WHERE station_canonical="
                         "'KIEV -CHISINAU'").fetchone()
    assert c.execute("SELECT station FROM services WHERE id=?", (ids["vd"],)
                     ).fetchone()[0] == "VATRA DORNEI BAI"
    # catalog: the misread number has no service left, so no catalog row
    assert not c.execute("SELECT 1 FROM trains WHERE train_no IN (92011, 4011)").fetchone()
    assert c.execute("SELECT 1 FROM trains WHERE train_no=777").fetchone()  # untouched
    assert c.execute("SELECT COUNT(*) FROM merged_rows").fetchone()[0] > 8
    c.close()
    # idempotent
    rep2 = _run(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
                 "--min-age-min", "0"], capsys)
    assert rep2["applied"]["services_merged"] == 0 and rep2["merge"]["services_affected"] == 0
    # reversible: exactly as before (the catalog is recomputed from the data)
    _run(["--db", str(db), "--restore"], capsys)
    after = _dump(db)
    for t in ("services", "events", "service_quality", "observations"):
        assert after[t] == before[t], t
    assert after["trains"] == before["trains"]
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM merged_rows").fetchone()[0] == 0


def test_restore_one_batch_only(tmp_path, capsys):
    db, ids = _db(tmp_path)
    args = ["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
            "--min-age-min", "0"]
    rep = _run(args, capsys)
    out = _run(["--db", str(db), "--restore", "--batch", "nope"], capsys)
    assert out == {"restored": {}}
    out = _run(["--db", str(db), "--restore", "--batch", rep["batch"]], capsys)
    assert out["restored"]["services"] == 2
    assert sqlite3.connect(db).execute("SELECT 1 FROM services WHERE id=?",
                                       (ids["dup"],)).fetchone()


def test_purge_ghosts_restore_never_touches_merge_archive(tmp_path, capsys):
    """The two scripts keep separate archives: a ghost restore cannot undo a merge."""
    db, ids = _db(tmp_path)
    _run(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
          "--min-age-min", "0"], capsys)
    spec = importlib.util.spec_from_file_location(
        "purge_ghosts", Path(__file__).resolve().parent.parent / "scripts" / "purge_ghosts.py")
    pg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pg)
    pg.main(["--db", str(db), "--restore"])
    capsys.readouterr()
    c = sqlite3.connect(db)
    assert not c.execute("SELECT 1 FROM services WHERE id=?", (ids["dup"],)).fetchone()
    assert c.execute("SELECT COUNT(*) FROM merged_rows").fetchone()[0] > 0
    c.close()


def test_winner_prefers_the_established_number(tmp_path, capsys):
    """IR 16593 seen on 6 days beats a better-observed misread (IR 6593)."""
    db = tmp_path / "w.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    for k in range(3):
        d = f"2026-10-{20 + k}"
        i = _svc(c, "departure", d, 16593, "BRASOV", "08:00", _t(d, 7), _t(d, 8), ttype="IR")
        _obs(c, i, "departure", 1, d, 7, station="BRASOV")
    bad = _svc(c, "departure", "2026-10-23", 6593, "BRASOV", "08:00", _t("2026-10-23", 7),
               _t("2026-10-23", 8), ttype="IR")
    good = _svc(c, "departure", "2026-10-23", 16593, "BRASOV", "08:00", _t("2026-10-23", 7),
                _t("2026-10-23", 8), ttype="IR")
    _obs(c, bad, "departure", 9, "2026-10-23", 7, station="BRASOV")
    _obs(c, good, "departure", 2, "2026-10-23", 7, station="BRASOV")
    s.close()
    rep = _run(["--db", str(db), "--min-age-min", "0"], capsys)
    assert [(m["loser"]["id"], m["winner"]["id"]) for m in rep["merge"]["list"]] == [(bad, good)]
    assert rep["merge"]["winner_seen_on_less_than_2_days"] == 0


def _shared_frame(c, day, hh, *pairs, board="departure"):
    """One capture in which every (service id, train number) of `pairs` was read."""
    cap = c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES (?, ?, 1)",
                    (_t(day, hh), f"frame-{day}-{hh}")).lastrowid
    for sid, no in pairs:
        _obs(c, sid, board, 1, day, hh, capture=cap, no=no)


def test_coexisting_pair_is_never_merged(tmp_path, capsys):
    """Two numbers once read in the same frame (any day) are two real trains: never merged,
    listed for a human decision, even when today they look like "1" noise in one slot."""
    D0 = "2026-10-20"
    db = tmp_path / "c.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    ids = {}
    # R 5011 / R 5014: the same slot on D2 (disjoint frames), two rows of one frame on D0
    ids["r5011_d0"] = _svc(c, "departure", D0, 5011, "BUZAU", "04:47", _t(D0, 4), _t(D0, 5),
                           ttype="R")
    ids["r5014_d0"] = _svc(c, "departure", D0, 5014, "BUZAU", "05:10", _t(D0, 4), _t(D0, 5),
                           ttype="R")
    _shared_frame(c, D0, 4, (ids["r5011_d0"], 5011), (ids["r5014_d0"], 5014))
    ids["r5011"] = _svc(c, "departure", D2, 5011, "BUZAU", "04:47", _t(D2, 4), _t(D2, 5),
                        ttype="R")
    ids["r5014"] = _svc(c, "departure", D2, 5014, "BUZAU", "04:47", _t(D2, 4), _t(D2, 5),
                        ttype="R")
    _obs(c, ids["r5011"], "departure", 4, D2, 4, no=5011, station="BUZAU")
    _obs(c, ids["r5014"], "departure", 1, D2, 4, no=5014, station="BUZAU")
    # RE 9209 / 92011: "1" noise in one slot on D2 (merged today), but both numbers were
    # read in the same frame on D0 -> two real trains
    ids["re9209_d1"] = _svc(c, "departure", D1, 9209, "PITESTI", "14:36", _t(D1, 13),
                            _t(D1, 14, 40))
    _obs(c, ids["re9209_d1"], "departure", 3, D1, 13, no=9209)
    ids["re9209"] = _svc(c, "departure", D2, 9209, "PITESTI", "14:36", _t(D2, 13, 5),
                         _t(D2, 14, 30))
    _obs(c, ids["re9209"], "departure", 6, D2, 13, no=9209)
    ids["re92011"] = _svc(c, "departure", D2, 92011, "PITESTI", "14:36", _t(D2, 14, 35),
                          _t(D2, 14, 55))
    _obs(c, ids["re92011"], "departure", 2, D2, 14, no=92011)
    ids["re9209_d0"] = _svc(c, "departure", D0, 9209, "PITESTI", "14:36", _t(D0, 13),
                            _t(D0, 15))
    ids["re92011_d0"] = _svc(c, "departure", D0, 92011, "CURTEA DE ARGES", "18:40",
                             _t(D0, 13), _t(D0, 15))
    _shared_frame(c, D0, 13, (ids["re9209_d0"], 9209), (ids["re92011_d0"], 92011))
    s.close()
    before = _dump(db)

    rep = _run(["--db", str(db), "--min-age-min", "0"], capsys)
    assert rep["merge"]["list"] == []
    why = {frozenset((x["winner"]["id"], x["loser"]["id"])): x["why_not_merged"]
           for x in rep["listed_not_merged"]}
    for a, b in (("r5011", "r5014"), ("re9209", "re92011")):
        w = why[frozenset((ids[a], ids[b]))]
        assert w.startswith("coexist") and D0 in w, w

    rep = _run(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
                "--min-age-min", "0"], capsys)
    assert rep["applied"]["services_merged"] == 0
    after = _dump(db)
    for t in ("services", "events", "service_quality", "observations", "trains"):
        assert after[t] == before[t], t


def _dump_all(db):
    c = sqlite3.connect(db)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
           for t in ("services", "events", "service_quality", "event_quality",
                     "observations", "trains")}
    c.close()
    return out


def test_prefix_dup_is_merged_and_restorable(tmp_path, capsys):
    """R 93 is R 8093 with the left digits cut: same slot, never in one frame, 8093 runs
    on 2 days and 93 never alone -> merged by --apply; --restore puts back every row."""
    db = tmp_path / "p.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    ids = {}
    ids["long_d1"] = _svc(c, "departure", D1, 8093, "SUCEAVA", "10:05", _t(D1, 9), _t(D1, 10),
                          ttype="R")
    _obs(c, ids["long_d1"], "departure", 3, D1, 9, station="SUCEAVA", no=8093)
    ids["long"] = _svc(c, "departure", D2, 8093, "SUCEAVA", "10:05", _t(D2, 9), _t(D2, 10),
                       ttype="R")
    _obs(c, ids["long"], "departure", 4, D2, 9, station="SUCEAVA", no=8093)
    ids["short"] = _svc(c, "departure", D2, 93, "SUCEAVA", "10:05", _t(D2, 9, 30),
                        _t(D2, 10, 5), ttype="R", platform=2, delay=5,
                        delay_read_at=_t(D2, 10))
    _obs(c, ids["short"], "departure", 2, D2, 10, station="SUCEAVA", no=93)
    ids["ev"] = _ev(c, ids["short"], D2, 10, "delay", "0", "5")
    c.execute("INSERT INTO service_quality(service_id, station_canonical, updated_at)"
              " VALUES (?, 'SUCEAVA', 'x')", (ids["short"],))
    c.execute("INSERT INTO event_quality(event_id, suspect, reason) VALUES (?, 1, 'x')",
              (ids["ev"],))
    for no in (8093, 93):
        c.execute("INSERT OR IGNORE INTO trains(train_no, journeys, observations)"
                  " VALUES (?, 1, 1)", (no,))
    s.close()
    before = _dump_all(db)

    rep = _run(["--db", str(db), "--min-age-min", "0"], capsys)
    assert [(m["loser"]["id"], m["winner"]["id"], m["relation"]) for m in rep["merge"]["list"]
            ] == [(ids["short"], ids["long"], "truncated_number")]
    rep = _run(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
                "--min-age-min", "0"], capsys)
    assert rep["applied"]["services_merged"] == 1
    c = sqlite3.connect(db)
    assert not c.execute("SELECT 1 FROM services WHERE id=?", (ids["short"],)).fetchone()
    assert c.execute("SELECT COUNT(*) FROM observations WHERE service_id=?",
                     (ids["long"],)).fetchone()[0] == 4 + 2
    assert c.execute("SELECT COUNT(*) FROM observations WHERE train_no=93").fetchone()[0] == 2
    c.close()

    _run(["--db", str(db), "--restore"], capsys)
    assert _dump_all(db) == before


def _trunc_db(tmp_path, long_no, short_no, long_days):
    """long_no on `long_days` (the last one shared with short_no, same slot, never in
    one frame); short_no never alone."""
    db = tmp_path / "t.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    ids = {}
    for k, d in enumerate(long_days):
        ids["long"] = _svc(c, "departure", d, long_no, "ARAD", "12:20", _t(d, 11),
                           _t(d, 12), ttype="R")
        _obs(c, ids["long"], "departure", 3 + k, d, 11, station="ARAD", no=long_no)
    d = long_days[-1]
    ids["short"] = _svc(c, "departure", d, short_no, "ARAD", "12:20", _t(d, 11, 30),
                        _t(d, 12, 10), ttype="R", platform=1)
    _obs(c, ids["short"], "departure", 1, d, 12, station="ARAD", no=short_no)
    ids["ev"] = _ev(c, ids["short"], d, 12, "delay", "0", "3")
    c.execute("INSERT INTO service_quality(service_id, station_canonical, updated_at)"
              " VALUES (?, 'ARAD', 'x')", (ids["short"],))
    for no in (long_no, short_no):
        c.execute("INSERT OR IGNORE INTO trains(train_no, journeys, observations)"
                  " VALUES (?, 1, 1)", (no,))
    s.close()
    return db, ids


def test_start_truncation_is_merged_and_restorable(tmp_path, capsys):
    """R 64 is the START of R 6478 (right digits cut): every strict condition holds ->
    merged by --apply; --restore puts back every row."""
    assert md._is_truncation(6478, 64) and not md.is_noise_pair(6478, 64)
    db, ids = _trunc_db(tmp_path, 6478, 64, [D1, D2])
    before = _dump_all(db)
    rep = _run(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
                "--min-age-min", "0"], capsys)
    assert [(m["loser"]["id"], m["winner"]["id"], m["relation"]) for m in rep["merge"]["list"]
            ] == [(ids["short"], ids["long"], "truncated_number")]
    assert rep["applied"]["services_merged"] == 1
    c = sqlite3.connect(db)
    assert not c.execute("SELECT 1 FROM services WHERE id=?", (ids["short"],)).fetchone()
    c.close()
    _run(["--db", str(db), "--restore"], capsys)
    assert _dump_all(db) == before


def test_truncation_with_long_number_on_one_day_is_listed(tmp_path, capsys):
    db, ids = _trunc_db(tmp_path, 8093, 93, [D2])
    before = _dump_all(db)
    rep = _run(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk"),
                "--min-age-min", "0"], capsys)
    assert rep["merge"]["list"] == [] and rep["applied"]["services_merged"] == 0
    [item] = rep["listed_not_merged"]
    assert (item["winner"]["id"], item["loser"]["id"]) == (ids["long"], ids["short"])
    assert "truncated" in item["why_not_merged"] and "< 2" in item["why_not_merged"]
    assert _dump_all(db) == before


def test_lives_alone_reason_renders_missing_values_as_dash(tmp_path, capsys):
    """A NULL station of the lone slot is shown as "-", never as "None"."""
    db = tmp_path / "a.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE services (id INTEGER PRIMARY KEY, board TEXT, service_date TEXT,
          train_type TEXT, train_no INTEGER, station TEXT, operator TEXT, sched_time TEXT,
          first_seen TEXT, last_seen TEXT, last_delay INTEGER, last_platform INTEGER,
          flagged INTEGER DEFAULT 0, status TEXT, last_read TEXT, delay_read_at TEXT);""")
    for d, no, st in ((D1, 5019, "BUZAU"), (D2, 5019, "BUZAU"), (D2, 19, "BUZAU"),
                      (D3, 19, None)):
        c.execute("INSERT INTO services(board, service_date, train_type, train_no, station,"
                  " sched_time, first_seen, last_seen, status) VALUES"
                  " ('departure', ?, 'R', ?, ?, '17:08', ?, ?, 'gone')",
                  (d, no, st, _t(d, 16), _t(d, 17)))
    c.commit()
    c.close()
    rep = _run(["--db", str(db), "--min-age-min", "0"], capsys)
    [item] = rep["listed_not_merged"]
    assert "lives alone (departure %s - 17:08," % D3 in item["why_not_merged"]
    assert "None" not in item["why_not_merged"]


def test_old_db_without_quality_or_observations(tmp_path, capsys):
    """A pre-quality database (no service_quality) still dry-runs."""
    db = tmp_path / "o.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE services (id INTEGER PRIMARY KEY, board TEXT, service_date TEXT,
          train_type TEXT, train_no INTEGER, station TEXT, operator TEXT, sched_time TEXT,
          first_seen TEXT, last_seen TEXT, last_delay INTEGER, last_platform INTEGER,
          flagged INTEGER DEFAULT 0, status TEXT, last_read TEXT, delay_read_at TEXT);
        CREATE TABLE observations (id INTEGER PRIMARY KEY, capture_id INTEGER, service_id INTEGER,
          board TEXT, station TEXT, train_no INTEGER);""")
    c.commit()
    c.close()
    rep = _run(["--db", str(db)], capsys)
    assert rep["merge"]["services_affected"] == 0


def test_db_without_observations_table_dry_runs(tmp_path, capsys):
    """No observations table (oldest schema): no crash, slots still compared."""
    db = tmp_path / "n.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE services (id INTEGER PRIMARY KEY, board TEXT, service_date TEXT,
          train_type TEXT, train_no INTEGER, station TEXT, operator TEXT, sched_time TEXT,
          first_seen TEXT, last_seen TEXT, last_delay INTEGER, last_platform INTEGER,
          flagged INTEGER DEFAULT 0, status TEXT, last_read TEXT, delay_read_at TEXT);""")
    for d in (D1, D2):
        c.execute("INSERT INTO services(board, service_date, train_type, train_no, station,"
                  " sched_time, first_seen, last_seen, status) VALUES"
                  " ('departure', ?, 'RE', 9209, 'PITESTI', '14:36', ?, ?, 'gone')",
                  (d, _t(d, 13), _t(d, 14)))
    c.execute("INSERT INTO services(board, service_date, train_type, train_no, station,"
              " sched_time, first_seen, last_seen, status) VALUES"
              " ('departure', ?, 'RE', 92011, 'PITESTI', '14:36', ?, ?, 'gone')",
              (D2, _t(D2, 13), _t(D2, 14)))
    c.commit()
    c.close()
    rep = _run(["--db", str(db), "--min-age-min", "0"], capsys)
    assert rep["merge"]["by_number_pair"] == {"RE 92011 -> RE 9209": 1}
