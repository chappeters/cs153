# Sailing Coach 🏊‍♂️⛵

A personal AI training analyst for an Olympic ILCA (Laser) sailing campaign. It ingests
my own Garmin training/racing files into a local database and exposes them to Claude as
live, queryable tools (via MCP), so I can ask my data anything — and get coaching that
understands sailing, not just generic endurance sport.

**CS 153 — The One-Person Frontier Lab. Track: Automation / Agent Systems.**

## Why I built it
Every AI fitness coach on the market models runners, cyclists, and triathletes. None of
them understands an ILCA campaign: hiking is sustained isometric leg load, on-water HR is
intermittent and condition-driven, and cross-training (cycling, strength) only matters to
the extent it makes me faster on the water. The bottleneck: my data is rich but scattered,
and a generic coach gives advice that's wrong for my sport. So I built the data layer that
lets Claude become a *sailing-specific* coach with persistent access to my real training.

## What it does
- Parses Garmin **FIT** (and TCX fallback) files into a SQLite database, computing
  per-session metrics: duration, HR zones, normalized power, efficiency factor, and
  aerobic decoupling (for power-equipped rides). Reads Garmin Connect's **`.zip`
  "Export Original"** archives directly — no manual unzipping.
- Auto-flags **regatta/race** files (by name), or flag any session after the fact with
  the `flag_race` tool, so the coach can compare competition demands to training.
- Exposes the database to Claude through an **MCP server** with 8 query tools.
- A coaching "brain" (`coaching/SAILING_COACH.md`) encodes the sailing-specific knowledge.

### The centerpiece: reading a regatta the way a sailor does
Two tools work together to make the point that a generic endurance tool can't:

**1. `compare_race_vs_training`** compares my HR distribution during regattas vs. training.
On my real data the *whole-session* numbers are almost a trap: racing averages **145 bpm**
(43% in Z3+) while training averages **154 bpm** (58% in Z3+). Read naïvely, that says
*"your training is already harder than racing."*

**2. `session_hr_timeline`** shows why that's wrong. A regatta file is **mostly waiting** —
a 5-hour on-water day might be only ~3 × ~45-min races, padded with tow-out, warmup, and
between-race drifting. The tool auto-detects the sustained elevated-HR blocks (the actual
races). On a real regatta (2025-11-29) it found **3 races of 38/45/44 min** — only **45% of
the day** — averaging **154–176 bpm, peak 190**, far above the whole-file average of 141.

So race *intensity* is much higher than the session average implies; you can't judge sailing
readiness from session-level HR — you have to **segment the races out**. That insight, and the
coaching brain that knows to apply it, is the whole project. (See [`EVALUATION.md`](EVALUATION.md).)

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Option A: try it immediately with synthetic sample data
python make_sample_data.py

# Option B: use my real data — drop Garmin "Export Original" files in data/raw/
# (raw .fit/.tcx OR the .zip Garmin gives you — both work), then:
python ingest.py
```
Set real thresholds in `config.json` (max HR, threshold HR, FTP).

## Usage
Register the MCP server with Claude Code:
```bash
claude mcp add sailing-coach -- python /absolute/path/to/server.py
```
Then ask Claude things like:
- "Compare my racing heart rate to my training — is my training hard enough?"
- "Find the actual races inside my Sweden regatta file and tell me how hard they were."
- "How's my cycling efficiency trending?"
- "What was my training load this month by sport?"

## Architecture
```
Garmin watch → FIT/TCX export → ingest.py → SQLite (sessions + records)
                                                  │
                                          server.py (MCP) ── tools ──► Claude
                                                  ▲
                                   coaching/SAILING_COACH.md (the brain)
```

## MCP tools (9)
`list_recent_sessions` · `get_session` · `compare_race_vs_training` · `session_hr_timeline` ·
`training_load` · `cycling_efficiency_trend` · `add_session_note` · `flag_race` · `get_thresholds`

## Tests
The MCP query layer and the metric math are decoupled from any MCP client, so they're
directly unit-testable:
```bash
pip install -r requirements-dev.txt
pytest                 # 28 tests: metric correctness + query behaviour
```
Metric tests are deterministic (constant power ⇒ NP equals that power; a clean HR/power
split ⇒ exact decoupling); server tests run against a seeded throwaway SQLite DB.

## Evaluation
Full writeup with the real numbers in [`EVALUATION.md`](EVALUATION.md). In short:
- **Expert ground-truth (nailed it):** on a real regatta I knew well, `session_hr_timeline`
  auto-found **3 race blocks** matching the actual races — and showed race-block HR
  (154–176 bpm) far above the diluted whole-session average (141), confirming the core thesis.
- **Failure analysis (honest limitation):** on another regatta where I'd left the watch on
  shore, the detector returned **0 races** — the per-second HR stream was corrupt. The tool is
  only as good as its data; HR-only detection fails here, which motivates GPS/speed
  cross-validation (future work). The system tags such files `[noisy-hr]` and excludes them
  from HR math.
- **Metric ground-truth:** NP / efficiency factor / decoupling validated by the 28-test suite.

## Privacy
`data/raw/` and `sailing_coach.db` are gitignored by default — no personal health data is
committed. The synthetic sample (`make_sample_data.py`) makes the repo fully reproducible
without it.

## AI usage disclosure
Built in focused AI-assisted sessions, which is the point of the course ("how far can one
person scale themselves"). Architecture, planning, and the Python (ingest, MCP server,
metrics, the HR-timeline race detector, and the test suite) were written with **Claude
(Opus 4.8)** via chat and **Claude Code** — including iterating directly on my real Garmin
data (fixing zip ingest, correcting my HR-zone config, discovering the watch-on-shore data
bug). The sailing domain knowledge, thresholds, and coaching judgment in
`coaching/SAILING_COACH.md` are mine, captured via a structured interview.

## Citations & acknowledgements
- [`fitparse`](https://github.com/dtcooper/python-fitparse) — FIT file parsing (MIT). Sample FIT from its test suite.
- [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect) — referenced for the (future) live-sync path.
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — `FastMCP` server framework.
- Tool taxonomy inspired by existing open-source Garmin MCP servers (e.g. [eddmann/garmin-connect-mcp](https://github.com/eddmann/garmin-connect-mcp)); the schema, metrics, sailing focus, and race-vs-training analysis here are my own.

## Future work
- **Race segmentation from GPS, not just HR.** `session_hr_timeline` is HR-only today, which
  fails when the HR stream is bad (see Evaluation). A race is unmistakable in the GPS track —
  sustained zig-zag upwind for ~a mile, then a downwind leg — and in speed (smooth and never
  near-zero during a race, vs. spiky while drifting; minus the tow-out/-in confound). Fusing
  GPS + speed + HR would make race detection robust.
- **Feed the detected race blocks into `compare_race_vs_training`**, so the comparison uses
  true race intensity instead of the diluted whole-session average.
- Light-air vs. heavy-air tagging (mental/postural vs. hiking load) per the coaching brain.
- Live auto-sync (Garmin's March 2026 auth changes make this non-trivial; planned via
  `python-garminconnect` on a scheduled job on a DigitalOcean box).
- An autonomous "morning brief" using the Anthropic API to summarize new sessions daily.
- Maneuver detection from sailing GPS (tacks/gybes) and wind-condition context.
