#!/usr/bin/env python3
"""
server.py - MCP server that lets Claude query the sailing-coach database live.

Run standalone:        python server.py
Register w/ Claude Code:  claude mcp add sailing-coach -- python /abs/path/to/server.py

Design note: every tool is a thin wrapper around a plain function (prefixed _),
so the query logic can be unit-tested without an MCP client.
"""
import os, json, sqlite3, datetime
from collections import defaultdict
from typing import Optional

from mcp.server.fastmcp import FastMCP

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "sailing_coach.db")
CONFIG = os.path.join(HERE, "config.json")

mcp = FastMCP("sailing-coach")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _cfg():
    with open(CONFIG) as f:
        return json.load(f)


SESSION_COLS = ("id, source_file, sport, sub_sport, is_race, start_time, duration_s, "
                "distance_m, avg_hr, max_hr, avg_power, max_power, normalized_power, "
                "efficiency_factor, decoupling_pct, calories, hr_zones_json, notes")


def _row_to_dict(r):
    d = dict(r)
    if d.get("duration_s"):
        d["duration_min"] = round(d["duration_s"] / 60, 1)
    if d.get("distance_m"):
        d["distance_km"] = round(d["distance_m"] / 1000, 2)
    if d.get("hr_zones_json"):
        d["hr_zones_sec"] = json.loads(d.pop("hr_zones_json"))
    return d


# ---------- plain (testable) query functions ----------

def _list_recent(limit=10, sport=None):
    q = f"SELECT {SESSION_COLS} FROM sessions"
    args = []
    if sport:
        q += " WHERE sport=?"; args.append(sport)
    q += " ORDER BY start_time DESC LIMIT ?"; args.append(limit)
    with _conn() as c:
        return [_row_to_dict(r) for r in c.execute(q, args)]


def _get_session(identifier):
    with _conn() as c:
        r = c.execute(f"SELECT {SESSION_COLS} FROM sessions WHERE id=? OR source_file=?",
                      (identifier, identifier)).fetchone()
        if not r:
            return {"error": f"No session matching '{identifier}'"}
        d = _row_to_dict(r)
        series = c.execute("SELECT t_offset_s,hr,power,speed FROM records WHERE session_id=? "
                           "ORDER BY t_offset_s", (d["id"],)).fetchall()
        d["n_detail_points"] = len(series)
        return d


def _zone_pct(rows):
    tot = {f"z{i}": 0 for i in range(1, 6)}
    for r in rows:
        for k, v in json.loads(r["hr_zones_json"]).items():
            tot[k] += v
    s = sum(tot.values()) or 1
    return {k: round(v / s * 100) for k, v in tot.items()}


# Sessions whose notes contain this marker have known HR-capture errors (e.g. the
# watch was left on shore so the per-second HR stream is unreliable). They're still
# real sessions — kept in the DB and correctly flagged — but excluded from HR-zone
# math, which would otherwise be garbage. Tag with add_session_note.
NOISY_HR_MARK = "[noisy-hr]"


def _compare_race_vs_training(sport="sailing"):
    # exclude sessions with a known bad HR capture (NULL notes are kept)
    ok = f"(notes IS NULL OR notes NOT LIKE '%{NOISY_HR_MARK}%')"
    with _conn() as c:
        race = c.execute(f"SELECT hr_zones_json, avg_hr FROM sessions WHERE sport=? AND is_race=1 AND {ok}", (sport,)).fetchall()
        trn = c.execute(f"SELECT hr_zones_json, avg_hr FROM sessions WHERE sport=? AND is_race=0 AND {ok}", (sport,)).fetchall()
    if not race:
        return {"error": f"No reliable-HR race sessions for sport='{sport}'. Flag one with flag_race."}
    if not trn:
        return {"error": f"No training sessions for sport='{sport}' to compare against."}
    race_hr = round(sum(r["avg_hr"] for r in race) / len(race), 1)
    trn_hr = round(sum(r["avg_hr"] for r in trn) / len(trn), 1)
    return {
        "sport": sport,
        "n_races": len(race), "n_training": len(trn),
        "race_hr_zone_pct": _zone_pct(race),
        "training_hr_zone_pct": _zone_pct(trn),
        "avg_hr_racing": race_hr,
        "avg_hr_training": trn_hr,
        "avg_hr_gap_bpm": round(race_hr - trn_hr, 1),
        "interpretation_hint": ("These are WHOLE-SESSION averages. A regatta file is mostly waiting "
                                "(tow-out, between-race) plus lower-intensity downwind, so a race's "
                                "whole-session HR UNDER-states its true intensity — a negative gap here "
                                "does NOT mean training is harder than racing. Call session_hr_timeline "
                                "on a race to read intensity from the actual race blocks before judging "
                                "whether training replicates race demands."),
    }


def _hr_timeline(identifier, bin_min=5, hot_hr=None, min_block_min=30, gap_min=5):
    """Bucket a session's HR over time and auto-detect sustained elevated blocks.

    Built for the sailing problem: a regatta file is mostly waiting (tow-out, warmup,
    between-race wind-watching), so its whole-file average understates race intensity.
    A race shows up as HR held elevated for ~40-60 min; breaks between races drop HR
    for ~8-30 min. We find contiguous minutes with mean HR >= hot_hr, bridging short
    dips (<= gap_min, e.g. a light patch downwind), and keep blocks >= min_block_min.
    HR-based on purpose: it still works when GPS/speed are bad (watch left on shore)."""
    with _conn() as c:
        s = c.execute("SELECT id, source_file, duration_s, is_race, max_hr FROM sessions "
                      "WHERE id=? OR source_file=?", (identifier, identifier)).fetchone()
        if not s:
            return {"error": f"No session matching '{identifier}'"}
        recs = c.execute("SELECT t_offset_s, hr FROM records WHERE session_id=? AND hr IS NOT NULL "
                         "ORDER BY t_offset_s", (s["id"],)).fetchall()
    if not recs:
        return {"error": "No HR detail records for this session."}

    if hot_hr is None:
        hot_hr = round(0.65 * _cfg()["hr_max"])  # ~Z3; tune if block count != known races

    # mean HR per minute (records are ~5s apart)
    per_min = defaultdict(list)
    for r in recs:
        per_min[int(r["t_offset_s"] // 60)].append(r["hr"])
    minute_hr = {m: sum(v) / len(v) for m, v in per_min.items()}
    last_min = max(minute_hr)

    # group contiguous "hot" minutes, bridging gaps <= gap_min
    blocks, cur = [], None
    for m in range(last_min + 1):
        if minute_hr.get(m, 0) >= hot_hr:
            if cur and m - cur["end"] <= gap_min:
                cur["end"] = m
            else:
                if cur:
                    blocks.append(cur)
                cur = {"start": m, "end": m}
    if cur:
        blocks.append(cur)

    def stats(b):
        hrs = [minute_hr[m] for m in range(b["start"], b["end"] + 1) if m in minute_hr]
        return {"start_min": b["start"], "end_min": b["end"] + 1,
                "duration_min": b["end"] - b["start"] + 1,
                "avg_hr": round(sum(hrs) / len(hrs)), "peak_hr": round(max(hrs))}

    # Keep long-enough blocks that also show real HR variation. A genuine race surges
    # and recovers (upwind vs downwind), so peak sits well above the block average; a
    # near-flat block is a stale/dropped-sensor artifact, not a race.
    races = [s for b in blocks if (b["end"] - b["start"] + 1) >= min_block_min
             for s in [stats(b)] if s["peak_hr"] - s["avg_hr"] >= 6]

    # coarse timeline for the caller to "see the shape"
    binned = defaultdict(list)
    for m, hr in minute_hr.items():
        binned[m // bin_min].append(hr)
    timeline = [{"t_min": b * bin_min, "avg_hr": round(sum(v) / len(v))}
                for b, v in sorted(binned.items())]

    dur_min = round((s["duration_s"] or (last_min + 1) * 60) / 60)
    total_race = sum(r["duration_min"] for r in races)
    return {
        "session": s["source_file"], "is_race": s["is_race"],
        "session_duration_min": dur_min, "hot_hr_threshold": hot_hr,
        "n_candidate_races": len(races),
        "candidate_races": races,
        "total_racing_min": total_race,
        "pct_time_actually_racing": round(total_race / dur_min * 100) if dur_min else None,
        "timeline_avg_hr_per_bin": timeline,
        "note": ("Each candidate race = HR sustained >= hot_hr for >= min_block_min with real "
                 "variation (flat blocks are dropped as sensor artifacts). If the count doesn't "
                 "match the known number of races, re-call with a different hot_hr. Read race "
                 "intensity from these blocks, NOT the session average. GPS-zigzag + "
                 "speed-smoothness segmentation is future work."),
    }


def _training_load(days=28, sport=None):
    # start_time is stored as "YYYY-MM-DD HH:MM:SS", which sorts/compares
    # lexically, so a same-format cutoff string is a valid lower bound.
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    q = "SELECT sport, COUNT(*) n, ROUND(SUM(duration_s)/3600.0,1) hours, ROUND(AVG(avg_hr),0) avg_hr FROM sessions"
    cond, args = ["start_time >= ?"], [cutoff]
    if sport:
        cond.append("sport=?"); args.append(sport)
    q += " WHERE " + " AND ".join(cond)
    q += " GROUP BY sport ORDER BY hours DESC"
    with _conn() as c:
        return {"window_days": days, "since": cutoff[:10], "by_sport": [dict(r) for r in c.execute(q, args)]}


def _cycling_efficiency():
    with _conn() as c:
        rows = c.execute("SELECT source_file, start_time, normalized_power, efficiency_factor, decoupling_pct "
                         "FROM sessions WHERE sport='cycling' AND efficiency_factor IS NOT NULL "
                         "ORDER BY start_time").fetchall()
    return {"note": "Higher EF over time at similar HR = improving aerobic fitness; lower decoupling = better durability.",
            "sessions": [dict(r) for r in rows]}


def _add_note(identifier, note):
    with _conn() as c:
        cur = c.execute("UPDATE sessions SET notes=? WHERE id=? OR source_file=?", (note, identifier, identifier))
        c.commit()
        return {"updated": cur.rowcount, "note": note}


def _set_race(identifier, is_race=True):
    val = 1 if is_race else 0
    with _conn() as c:
        cur = c.execute("UPDATE sessions SET is_race=? WHERE id=? OR source_file=?", (val, identifier, identifier))
        c.commit()
        if cur.rowcount == 0:
            return {"updated": 0, "error": f"No session matching '{identifier}'"}
        return {"updated": cur.rowcount, "is_race": val}


def _thresholds():
    cfg = _cfg()
    return {"hr_max": cfg["hr_max"], "hr_threshold": cfg["hr_threshold"],
            "ftp_watts": cfg["ftp_watts"], "hr_zone_bounds_pct": cfg["hr_zone_bounds_pct"]}


# ---------- MCP tool wrappers ----------

@mcp.tool()
def list_recent_sessions(limit: int = 10, sport: Optional[str] = None) -> str:
    """List recent sessions (most recent first). Optional sport filter: cycling | sailing | strength."""
    return json.dumps(_list_recent(limit, sport), indent=2, default=str)


@mcp.tool()
def get_session(identifier: str) -> str:
    """Full detail for one session, by numeric id or source filename."""
    return json.dumps(_get_session(identifier), indent=2, default=str)


@mcp.tool()
def compare_race_vs_training(sport: str = "sailing") -> str:
    """Compare competition (regatta) HR demands against training for a sport. The core sailing-readiness check."""
    return json.dumps(_compare_race_vs_training(sport), indent=2, default=str)


@mcp.tool()
def session_hr_timeline(identifier: str, bin_min: int = 5, hot_hr: Optional[int] = None,
                        min_block_min: int = 30, gap_min: int = 5) -> str:
    """Segment a session's HR over time and auto-detect the actual races inside it.

    A regatta file is mostly waiting (tow-out, warmup, between-race), so its average
    HR understates race intensity. This finds the sustained elevated-HR blocks (the
    races) and reports how much of the day was real racing. Tune hot_hr if the detected
    block count doesn't match the known number of races. Works even when GPS/speed are
    unreliable (HR-based)."""
    return json.dumps(_hr_timeline(identifier, bin_min, hot_hr, min_block_min, gap_min),
                      indent=2, default=str)


@mcp.tool()
def training_load(days: int = 28, sport: Optional[str] = None) -> str:
    """Training volume (hours, session count, avg HR) grouped by sport."""
    return json.dumps(_training_load(days, sport), indent=2, default=str)


@mcp.tool()
def cycling_efficiency_trend() -> str:
    """Cycling efficiency factor and aerobic decoupling over time (needs power-equipped rides)."""
    return json.dumps(_cycling_efficiency(), indent=2, default=str)


@mcp.tool()
def add_session_note(identifier: str, note: str) -> str:
    """Attach context to a session (RPE, conditions, how it felt) so the coach remembers it."""
    return json.dumps(_add_note(identifier, note), indent=2, default=str)


@mcp.tool()
def flag_race(identifier: str, is_race: bool = True) -> str:
    """Mark a session (by id or filename) as a regatta/race, or clear it with is_race=false.
    Real Garmin files are named by activity id, not 'regatta', so use this to make a
    sailing session count as competition for compare_race_vs_training."""
    return json.dumps(_set_race(identifier, is_race), indent=2, default=str)


@mcp.tool()
def get_thresholds() -> str:
    """Chapman's configured HR/power thresholds and zone definitions."""
    return json.dumps(_thresholds(), indent=2, default=str)


if __name__ == "__main__":
    mcp.run()
