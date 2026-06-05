#!/usr/bin/env python3
"""
make_sample_data.py - Generate a small, realistic SYNTHETIC dataset so the repo is
reproducible without exposing real health data, and so every code path is exercised
(cycling-with-power, sailing training, a regatta flagged is_race, and strength).

This is FAKE data for demonstration/testing only. Real use: put your own Garmin
'Original' FIT exports in data/raw/ and run ingest.py.

    python make_sample_data.py        # wipes and rebuilds sailing_coach.db from synthetic sessions
"""
import os, random, datetime, math
import ingest  # reuse the exact same metric + insert logic

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))


def synth(n_sec, hr_base, hr_amp, hr_drift=0, power_base=None, power_amp=0, gps=False, step=1):
    """Build a per-second record list with plausible HR (and optional power/GPS)."""
    recs = []
    lat, lon = 43.18, -88.43  # Lake Geneva-ish
    for t in range(0, n_sec, step):
        prog = t / n_sec
        hr = hr_base + hr_drift * prog + hr_amp * math.sin(t / 90.0) + random.uniform(-4, 4)
        rec = {"t": float(t), "hr": round(hr), "power": None, "cadence": None,
               "speed": None, "lat": None, "lon": None}
        if power_base is not None:
            rec["power"] = max(0, round(power_base + power_amp * math.sin(t / 60.0) + random.uniform(-15, 15)))
            rec["cadence"] = round(88 + random.uniform(-6, 6))
        if gps:
            lat += random.uniform(-0.0002, 0.0002)
            lon += random.uniform(-0.0002, 0.0002)
            rec["lat"], rec["lon"] = round(lat, 6), round(lon, 6)
            rec["speed"] = round(random.uniform(2.5, 6.0), 1)
        recs.append(rec)
    return recs


def main():
    db_path = ingest.DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = ingest.db()
    cfg = ingest.load_config()
    today = datetime.date.today()

    def st(days_ago):
        return {"start_time": datetime.datetime.combine(today - datetime.timedelta(days=days_ago),
                                                        datetime.time(9, 0))}

    sessions = [
        # name, sport, sub, is_race, records
        ("sample_endurance_ride.fit", "cycling", "road", 0,
         synth(7200, 138, 8, hr_drift=12, power_base=205, power_amp=30, gps=True)),       # Z2 endurance w/ power + drift
        ("sample_vo2_intervals_ride.fit", "cycling", "road", 0,
         synth(3600, 158, 22, power_base=255, power_amp=90, gps=True)),                   # hard intervals
        ("sample_sail_training.fit", "sailing", "generic", 0,
         synth(9000, 128, 14, gps=True)),                                                # on-water training, HR+GPS
        ("sample_REGATTA_day1.fit", "sailing", "generic", 1,
         synth(10800, 152, 18, gps=True)),                                               # racing: higher, sustained
        ("sample_strength.fit", "strength", "generic", 0,
         synth(3000, 112, 20, step=1)),                                                  # gym, rough HR only
    ]

    print("Generating synthetic sample sessions...")
    for name, sport, sub, is_race, recs in sessions:
        days = {"sample_endurance_ride.fit": 6, "sample_vo2_intervals_ride.fit": 4,
                "sample_sail_training.fit": 3, "sample_REGATTA_day1.fit": 9,
                "sample_strength.fit": 2}[name]
        summary = st(days)
        row = ingest.insert_session(conn, name, sport, sub, is_race, summary, recs, cfg)
        tag = " [RACE]" if is_race else ""
        print(f"  {name:32s} {sport:9s} avgHR={row['avg_hr']:>3} "
              f"NP={row['normalized_power']} EF={row['efficiency_factor']} "
              f"decouple={row['decoupling_pct']}{tag}")
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    print(f"Done. {n} synthetic sessions in {os.path.basename(db_path)}.")


if __name__ == "__main__":
    main()
