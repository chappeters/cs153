#!/usr/bin/env python3
"""
ingest.py - Parse Garmin FIT files into the sailing-coach database.

Usage:
    python ingest.py                       # ingest every .fit/.tcx/.zip in data/raw/
    python ingest.py path/to/file.fit ...  # ingest specific files

Accepts raw .fit / .tcx files and the .zip exports Garmin Connect produces from
"Export Original" (each zip wraps a single .fit) — no manual unzipping needed.

For each session it computes summary metrics, HR time-in-zone, and (for cycling,
which has power) normalized power, efficiency factor, and aerobic decoupling.
A session whose filename contains "race", "regatta", or "event" is flagged
is_race=1 (the zip name is checked too) so the coach can compare competition
demands against training.

Re-running is safe: sessions are keyed on filename, so existing ones are skipped.
"""
import io, sys, os, json, sqlite3, glob, math, zipfile

try:
    import fitparse
except ImportError:
    sys.exit("Missing dependency. Run: pip install -r requirements.txt")

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "sailing_coach.db")
SCHEMA = os.path.join(HERE, "schema.sql")
CONFIG = os.path.join(HERE, "config.json")
RAW_DIR = os.path.join(HERE, "data", "raw")
DOWNSAMPLE_S = 5  # store one detail record every N seconds to keep the DB small


def load_config():
    with open(CONFIG) as f:
        return json.load(f)


def db():
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA) as f:
        conn.executescript(f.read())
    return conn


def parse_fit(fileish):
    """Return (session_summary_dict, records_list) from a FIT file.

    `fileish` may be a path or any file-like object (so we can parse a .fit read
    straight out of a Garmin .zip without writing it to disk first)."""
    ff = fitparse.FitFile(fileish)

    summary = {}
    for m in ff.get_messages("session"):
        for d in m:
            if d.value is not None:
                summary[d.name] = d.value
        break  # one session per file

    records = []
    start_ts = None
    for m in ff.get_messages("record"):
        r = {d.name: d.value for d in m}
        ts = r.get("timestamp")
        if ts is None:
            continue
        if start_ts is None:
            start_ts = ts
        records.append({
            "t": (ts - start_ts).total_seconds(),
            "hr": r.get("heart_rate"),
            "power": r.get("power"),
            "cadence": r.get("cadence"),
            "speed": r.get("enhanced_speed") or r.get("speed"),
            "lat": _semicircles(r.get("position_lat")),
            "lon": _semicircles(r.get("position_long")),
        })
    return summary, records


def _semicircles(v):
    # Garmin stores GPS as semicircles; convert to degrees.
    return None if v is None else v * (180.0 / 2**31)


def parse_tcx(fileish):
    """Fallback parser for TCX files (XML) exported from TrainingPeaks/Garmin.

    `fileish` may be a path or a file-like object (ET.parse accepts both)."""
    import xml.etree.ElementTree as ET
    import datetime as _dt
    ns = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
          "x": "http://www.garmin.com/xmlschemas/ActivityExtension/v2"}
    root = ET.parse(fileish).getroot()
    act = root.find(".//t:Activity", ns)
    sport = (act.get("Sport").lower() if act is not None and act.get("Sport") else "other")
    records, start_ts = [], None
    for tp in root.findall(".//t:Trackpoint", ns):
        tnode = tp.find("t:Time", ns)
        if tnode is None:
            continue
        ts = _dt.datetime.fromisoformat(tnode.text.replace("Z", "+00:00"))
        if start_ts is None:
            start_ts = ts
        def g(p):
            n = tp.find(p, ns)
            return float(n.text) if n is not None and n.text else None
        records.append({
            "t": (ts - start_ts).total_seconds(),
            "hr": g("t:HeartRateBpm/t:Value"),
            "power": g(".//x:Watts"),
            "cadence": g("t:Cadence"),
            "speed": g(".//x:Speed"),
            "lat": g("t:Position/t:LatitudeDegrees"),
            "lon": g("t:Position/t:LongitudeDegrees"),
        })
    return {"sport": sport, "start_time": start_ts}, records


def hr_zones(records, hr_max, bounds):
    """Seconds spent in each of 5 HR zones, based on %HRmax."""
    z = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    hrs = [r["hr"] for r in records if r["hr"]]
    if not hrs:
        return z
    # assume ~1 sample/sec; weight each sample by avg gap so totals ~= duration
    dt = 1.0
    for hr in hrs:
        frac = hr / hr_max
        if frac < bounds["z1_upper"]:   z["z1"] += dt
        elif frac < bounds["z2_upper"]: z["z2"] += dt
        elif frac < bounds["z3_upper"]: z["z3"] += dt
        elif frac < bounds["z4_upper"]: z["z4"] += dt
        else:                           z["z5"] += dt
    return {k: round(v) for k, v in z.items()}


def normalized_power(records):
    """NP = 4th root of the mean of the 30s-rolling-avg power, to the 4th power."""
    p = [r["power"] for r in records if r["power"] is not None]
    if len(p) < 30:
        return None
    roll = []
    for i in range(29, len(p)):
        roll.append(sum(p[i-29:i+1]) / 30.0)
    if not roll:
        return None
    return round((sum(x**4 for x in roll) / len(roll)) ** 0.25, 1)


def decoupling(records):
    """Aerobic decoupling: % drift in power:HR from 1st half to 2nd half (cycling)."""
    pairs = [(r["power"], r["hr"]) for r in records if r["power"] and r["hr"]]
    if len(pairs) < 60:
        return None
    half = len(pairs) // 2
    def ratio(seg):
        ap = sum(p for p, _ in seg) / len(seg)
        ah = sum(h for _, h in seg) / len(seg)
        return ap / ah if ah else None
    r1, r2 = ratio(pairs[:half]), ratio(pairs[half:])
    if not r1 or not r2:
        return None
    return round((r1 - r2) / r1 * 100, 1)


def avg(records, key):
    vals = [r[key] for r in records if r[key] is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def mx(records, key):
    vals = [r[key] for r in records if r[key] is not None]
    return max(vals) if vals else None


def insert_session(conn, source_file, sport, sub_sport, is_race, summary, records, cfg):
    """Compute metrics for one session and insert it (+ downsampled records)."""
    has_power = any(r["power"] for r in records)
    row = {
        "source_file": source_file,
        "sport": sport,
        "sub_sport": sub_sport,
        "is_race": is_race,
        "start_time": str(summary.get("start_time")),
        "duration_s": summary.get("total_timer_time") or (records[-1]["t"] if records else None),
        "distance_m": summary.get("total_distance"),
        "avg_hr": summary.get("avg_heart_rate") or avg(records, "hr"),
        "max_hr": summary.get("max_heart_rate") or mx(records, "hr"),
        "avg_power": (summary.get("avg_power") or avg(records, "power")) if has_power else None,
        "max_power": (summary.get("max_power") or mx(records, "power")) if has_power else None,
        "normalized_power": normalized_power(records) if has_power else None,
        "calories": summary.get("total_calories"),
        "hr_zones_json": json.dumps(hr_zones(records, cfg["hr_max"], cfg["hr_zone_bounds_pct"])),
        "notes": None,
    }
    if has_power and row["normalized_power"] and row["avg_hr"]:
        row["efficiency_factor"] = round(row["normalized_power"] / row["avg_hr"], 3)
        row["decoupling_pct"] = decoupling(records)
    else:
        row["efficiency_factor"] = None
        row["decoupling_pct"] = None

    cols = ",".join(row.keys())
    qs = ",".join("?" * len(row))
    cur = conn.execute(f"INSERT INTO sessions ({cols}) VALUES ({qs})", list(row.values()))
    sid = cur.lastrowid

    last_t = -999
    detail = []
    for r in records:
        if r["t"] - last_t >= DOWNSAMPLE_S:
            detail.append((sid, r["t"], r["hr"], r["power"], r["cadence"], r["speed"], r["lat"], r["lon"]))
            last_t = r["t"]
    conn.executemany(
        "INSERT INTO records (session_id,t_offset_s,hr,power,cadence,speed,lat,lon) VALUES (?,?,?,?,?,?,?,?)",
        detail,
    )
    conn.commit()
    return row


RACE_TOKENS = ("race", "regatta", "event")


def _iter_sources(path):
    """Yield (source_name, summary, records) for each activity in `path`.

    Handles raw .fit / .tcx and Garmin .zip exports (which wrap one .fit each;
    rare multi-activity zips are all ingested). source_name is the inner activity
    filename so re-runs dedupe on the real activity, not the zip wrapper."""
    low = path.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.namelist() if m.lower().endswith((".fit", ".tcx"))]
            if not members:
                raise ValueError("no .fit/.tcx inside zip")
            for m in members:
                data = zf.read(m)
                name = os.path.basename(m)
                if name.lower().endswith(".tcx"):
                    summary, records = parse_tcx(io.BytesIO(data))
                else:
                    summary, records = parse_fit(io.BytesIO(data))
                yield name, summary, records
    elif low.endswith(".tcx"):
        yield os.path.basename(path), *parse_tcx(path)
    else:
        yield os.path.basename(path), *parse_fit(path)


def ingest_file(conn, path, cfg):
    archive = os.path.basename(path)
    for source_file, summary, records in _iter_sources(path):
        cur = conn.execute("SELECT 1 FROM sessions WHERE source_file=?", (source_file,))
        if cur.fetchone():
            print(f"  skip (already imported): {source_file}")
            continue

        sport = summary.get("sport") or "other"
        # check both the archive name and the inner activity name for race tags
        tag_src = f"{archive} {source_file}".lower()
        is_race = 1 if any(t in tag_src for t in RACE_TOKENS) else 0
        row = insert_session(conn, source_file, sport, summary.get("sub_sport"), is_race, summary, records, cfg)

        tag = " [RACE]" if row["is_race"] else ""
        print(f"  imported: {source_file}  ({row['sport']}, {row['duration_s'] and round(row['duration_s']/60)}min, "
              f"avg HR {row['avg_hr']}, NP {row['normalized_power']}){tag}")


def main():
    cfg = load_config()
    conn = db()
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(RAW_DIR, "*.fit")) +
                                   glob.glob(os.path.join(RAW_DIR, "*.tcx")) +
                                   glob.glob(os.path.join(RAW_DIR, "*.zip")))
    if not paths:
        print(f"No .fit/.tcx/.zip files found in {RAW_DIR}. Export 'Original' files from Garmin Connect into there.")
        return
    print(f"Ingesting {len(paths)} file(s)...")
    for p in paths:
        try:
            ingest_file(conn, p, cfg)
        except Exception as e:
            print(f"  ERROR on {os.path.basename(p)}: {e}")
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    print(f"Done. {n} session(s) in the database.")


if __name__ == "__main__":
    main()
