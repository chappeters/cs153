"""Shared fixtures: a temporary, seeded database that server.py points at.

We build a throwaway SQLite DB from the real schema.sql, insert a handful of
known sessions, and monkeypatch server.DB_PATH / server.CONFIG so the plain
query functions run against it — no MCP client, no real health data.
"""
import os, json, sqlite3, datetime
import pytest
import server

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(HERE, "schema.sql")

# zones used by the fixture; full Z4 vs full Z1 makes the race/training gap exact
Z_RACE = json.dumps({"z1": 0, "z2": 0, "z3": 0, "z4": 600, "z5": 0})
Z_EASY = json.dumps({"z1": 600, "z2": 0, "z3": 0, "z4": 0, "z5": 0})


def _ago(days):
    return (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


# (source_file, sport, is_race, days_ago, duration_s, avg_hr, np, ef, decoup, zones)
SEED = [
    ("recent_ride.fit",   "cycling", 0,   5, 3600, 150, 200.0, 1.30, 5.0, Z_EASY),
    ("old_ride.fit",      "cycling", 0, 100, 3600, 140, 180.0, 1.28, 4.0, Z_EASY),
    ("regatta_day1.fit",  "sailing", 1,  10, 7200, 160, None,  None, None, Z_RACE),
    ("sail_training.fit", "sailing", 0,   8, 7200, 130, None,  None, None, Z_EASY),
]


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "hr_max": 195, "hr_threshold": 172, "ftp_watts": 290,
        "hr_zone_bounds_pct": {"z1_upper": 0.6, "z2_upper": 0.7, "z3_upper": 0.8, "z4_upper": 0.9},
    }))

    conn = sqlite3.connect(db_path)
    with open(SCHEMA) as f:
        conn.executescript(f.read())
    for sf, sport, is_race, days, dur, hr, np_, ef, dec, zones in SEED:
        conn.execute(
            "INSERT INTO sessions (source_file,sport,is_race,start_time,duration_s,avg_hr,"
            "normalized_power,efficiency_factor,decoupling_pct,hr_zones_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sf, sport, is_race, _ago(days), dur, hr, np_, ef, dec, zones))
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", str(db_path))
    monkeypatch.setattr(server, "CONFIG", str(cfg_path))
    return db_path
