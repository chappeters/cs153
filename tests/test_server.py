"""Tests for the plain query functions behind the MCP tools (server.py)."""
import sqlite3
import server


def test_list_recent_orders_and_limits(db):
    rows = server._list_recent(limit=2)
    assert len(rows) == 2
    # most recent first: recent_ride (5d ago) before sail_training (8d ago)
    assert rows[0]["source_file"] == "recent_ride.fit"
    assert rows[0]["duration_min"] == 60.0  # derived field


def test_list_recent_sport_filter(db):
    rows = server._list_recent(limit=10, sport="sailing")
    assert {r["sport"] for r in rows} == {"sailing"}
    assert len(rows) == 2


def test_get_session_by_filename(db):
    s = server._get_session("regatta_day1.fit")
    assert s["is_race"] == 1
    assert s["hr_zones_sec"]["z4"] == 600  # parsed back from JSON


def test_get_session_missing_returns_error(db):
    assert "error" in server._get_session("nope.fit")


def test_training_load_window_excludes_old(db):
    # 28-day window: the 100-day-old ride must NOT count
    load = server._training_load(days=28)
    by = {r["sport"]: r for r in load["by_sport"]}
    assert by["cycling"]["n"] == 1            # only recent_ride
    assert by["sailing"]["n"] == 2
    assert "since" in load


def test_training_load_wide_window_includes_all(db):
    load = server._training_load(days=365)
    by = {r["sport"]: r for r in load["by_sport"]}
    assert by["cycling"]["n"] == 2            # old ride now included


def test_compare_race_vs_training_gap(db):
    cmp = server._compare_race_vs_training("sailing")
    assert cmp["n_races"] == 1 and cmp["n_training"] == 1
    assert cmp["avg_hr_racing"] == 160.0
    assert cmp["avg_hr_training"] == 130.0
    assert cmp["avg_hr_gap_bpm"] == 30.0
    assert cmp["race_hr_zone_pct"]["z4"] == 100   # race fully in Z4
    assert cmp["training_hr_zone_pct"]["z1"] == 100


def test_compare_no_race_returns_error(db):
    assert "error" in server._compare_race_vs_training("cycling")  # no cycling races


def test_cycling_efficiency_only_power_sessions(db):
    eff = server._cycling_efficiency()
    files = {s["source_file"] for s in eff["sessions"]}
    assert files == {"recent_ride.fit", "old_ride.fit"}  # sailing has no EF


def test_add_note_persists(db):
    res = server._add_note("regatta_day1.fit", "big breeze, 18kt")
    assert res["updated"] == 1
    assert server._get_session("regatta_day1.fit")["notes"] == "big breeze, 18kt"


def test_flag_race_round_trip(db):
    assert server._set_race("sail_training.fit", True)["is_race"] == 1
    assert server._get_session("sail_training.fit")["is_race"] == 1
    assert server._set_race("sail_training.fit", False)["is_race"] == 0
    assert server._get_session("sail_training.fit")["is_race"] == 0


def test_flag_race_unknown_identifier(db):
    res = server._set_race("ghost.fit", True)
    assert res["updated"] == 0 and "error" in res


def test_thresholds_reads_config(db):
    t = server._thresholds()
    assert t["hr_max"] == 195 and t["ftp_watts"] == 290
    assert t["hr_zone_bounds_pct"]["z4_upper"] == 0.9


def _add_session_with_hr(db_path, source_file, sport, is_race, minute_hr):
    """Insert a session plus one HR record per minute; returns its id."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("INSERT INTO sessions (source_file,sport,is_race,start_time,duration_s) "
                       "VALUES (?,?,?,?,?)",
                       (source_file, sport, is_race, "2025-01-01 09:00:00", len(minute_hr) * 60))
    sid = cur.lastrowid
    conn.executemany("INSERT INTO records (session_id,t_offset_s,hr) VALUES (?,?,?)",
                     [(sid, m * 60, hr) for m, hr in enumerate(minute_hr)])
    conn.commit(); conn.close()
    return sid


def test_hr_timeline_detects_two_race_blocks(db):
    # 20min easy, 40min hard (race 1), 15min easy break, 40min hard (race 2)
    minute_hr = [100] * 20 + [160] * 40 + [100] * 15 + [160] * 40
    sid = _add_session_with_hr(db, "regatta_2races.fit", "sailing", 1, minute_hr)
    r = server._hr_timeline(sid)              # default hot_hr ~127 (0.65*195)
    assert r["n_candidate_races"] == 2
    assert [b["duration_min"] for b in r["candidate_races"]] == [40, 40]
    # whole-session avg HR (~134) is far below the race-block avg (~160): the dilution point
    assert all(b["avg_hr"] >= 155 for b in r["candidate_races"])


def test_hr_timeline_no_blocks_when_hr_flat_low(db):
    # corrupt-capture analogue: HR never gets near race intensity
    sid = _add_session_with_hr(db, "bad_capture.fit", "sailing", 1, [70] * 120)
    assert server._hr_timeline(sid)["n_candidate_races"] == 0


def test_compare_excludes_noisy_hr_tagged_sessions(db):
    # tagging the only clean race with [noisy-hr] removes it from the comparison
    server._add_note("regatta_day1.fit", "watch on shore [noisy-hr]")
    assert "error" in server._compare_race_vs_training("sailing")
