#!/usr/bin/env python3
"""
setup_demo.py - Re-apply Chapman's real-data demo state after a fresh `python ingest.py`.

Garmin files are named by activity id, so race flags can't be inferred from filenames.
This records which of *my* real sessions were regattas (and the event name for ones I
want to query by name), so the demo is reproducible.

    python ingest.py        # build the DB from data/raw/
    python setup_demo.py     # flag races + label known events

(Staff reproducing with `make_sample_data.py` don't need this — the synthetic regatta is
already flagged there.)
"""
import server

# real regattas, by source filename
REGATTAS = ["22351981225_ACTIVITY.fit", "21125411916_ACTIVITY.fit", "19505168762_ACTIVITY.fit",
            "22386562476_ACTIVITY.fit", "20070575880_ACTIVITY.fit"]

# event labels so the coach can resolve a natural-language reference to a session
EVENTS = {"20070575880_ACTIVITY.fit": "European Championship, Sweden (Aug 2025) - 3 races."}

if __name__ == "__main__":
    flagged = sum(1 for sf in REGATTAS if server._set_race(sf, True).get("updated"))
    labelled = sum(1 for sf, note in EVENTS.items() if server._add_note(sf, note).get("updated"))
    print(f"Flagged {flagged} regattas; labelled {labelled} event(s).")
    print("compare_race_vs_training now uses all flagged regattas (chest-strap HR).")
