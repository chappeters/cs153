#!/usr/bin/env python3
"""
setup_demo.py - Re-apply Chapman's real-data demo state after a fresh `python ingest.py`.

Garmin files are named by activity id, so race flags can't be inferred from filenames.
This records which of *my* real sessions were regattas, and which had a known HR-capture
error (watch left on shore -> unreliable per-second HR), so the demo is reproducible.

    python ingest.py        # build the DB from data/raw/
    python setup_demo.py     # flag races + tag noisy-HR files

(Staff reproducing with `make_sample_data.py` don't need this — the synthetic regatta is
already flagged there.)
"""
import server

# real regattas (by source filename) and which of them have unreliable HR capture
REGATTAS = ["22351981225_ACTIVITY.fit", "21125411916_ACTIVITY.fit", "19505168762_ACTIVITY.fit",
            "22386562476_ACTIVITY.fit", "20070575880_ACTIVITY.fit"]
NOISY_HR = ["22351981225_ACTIVITY.fit", "22386562476_ACTIVITY.fit", "20070575880_ACTIVITY.fit"]

if __name__ == "__main__":
    flagged = 0
    for sf in REGATTAS:
        if server._set_race(sf, True).get("updated"):
            flagged += 1
    tagged = 0
    for sf in NOISY_HR:
        if server._add_note(sf, "Regatta. HR-capture error (watch left on shore) -> per-second "
                                "HR unreliable; excluded from HR comparison. [noisy-hr]").get("updated"):
            tagged += 1
    print(f"Flagged {flagged} regattas; tagged {tagged} files [noisy-hr].")
    print("compare_race_vs_training will now use the reliable-HR regattas only.")
