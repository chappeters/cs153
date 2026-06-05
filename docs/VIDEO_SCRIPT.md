# 3–5 min Demo Video Script (Q1–Q4)

Target ~4 min. You talk; the screen shows the repo + a live Claude Code chat against your real
data. Beats marked **[DEMO]** are live; the rest is voiceover.

---

## Q1 — Why did you build this? (~45s)
> "I'm running an Olympic ILCA — Laser — sailing campaign toward LA 2028. Every AI fitness coach
> on the market models runners, cyclists, and triathletes. None of them understand sailing: hiking
> is a sustained isometric leg hold, on-water heart rate is intermittent and totally
> condition-driven, and cross-training only matters to the extent it makes me faster on the water.
> My training data is rich but scattered across Garmin files, and a generic coach gives advice
> that's actively wrong for my sport. So I built the data layer that turns Claude into a coach that
> understands *sailing*."

## Q2 — How does it work? (~90s)  *(Automation / Agent Systems track)*
Show the architecture line in the README, then:
> "Four pieces. I export my Garmin activities — they come as zip files — and `ingest.py` parses the
> FIT data into a SQLite database, computing per-session metrics: HR time-in-zone, normalized power,
> efficiency factor, aerobic decoupling. An MCP server exposes that database to Claude as **9 live
> query tools**. And a coaching 'brain' — `SAILING_COACH.md` — encodes the sailing-specific judgment
> that makes the reads correct."

**[DEMO]** In Claude Code, ask:
> "What's my training load this month by sport, and how's my cycling efficiency trending?"

Then the centerpiece:
> "Now the sailing-specific part. First the naïve view —"

**[DEMO]** "Compare my racing heart rate to my training."
- Point at the numbers: *racing whole-session avg **145 bpm**, training **154**. Read literally,
  that says my training is already harder than racing.* "For sailing, that's a trap."

**[DEMO]** "Find the actual races inside my 2025-11-29 regatta and tell me how hard they were."
- *The `session_hr_timeline` tool auto-detects **3 races, 38/45/44 min**, averaging **154–176 bpm,
  peak 190** — only **45% of the day** was racing; the rest is tow-out, warmup, drifting between
  races.* "So race intensity is way above the session average — you literally cannot read sailing
  readiness off session-level HR. A generic endurance tool never would. That's the whole project."

## Q3 — Use cases & impact (~45s)
> "Day to day, this is my training analyst — it tells me whether my cross-training actually
> replicates race demands heading into North Americans and the San Pedro OCR this July. More
> broadly: the pattern — a personal data layer plus a domain 'brain' exposed to Claude over MCP —
> generalizes to any athlete in a sport the big platforms ignore, or really any domain where
> generic AI advice is wrong because it lacks your context. One person can now build the
> specialized coach that no company would build for a niche of one."

## Q4 — What I'd add next (~40s)
> "The honest limitation —" **[DEMO/show EVALUATION.md]** "on one regatta I'd left my watch on
> shore, so the HR stream was corrupt and the race detector found nothing. The fix is to segment
> races from the GPS track and speed, not HR alone — a race is an unmistakable upwind zig-zag.
> After that: feed the detected race blocks back into the comparison so it uses true race
> intensity, add live Garmin auto-sync on a scheduled job, and an autonomous daily 'morning brief.'"

## Close (~15s)
> "Built in focused sessions with Claude and Claude Code — including iterating live on my real
> data, which is how we caught a wrong max-HR in my config and that watch-on-shore data bug. The
> sailing judgment is mine; the build velocity is the AI. Repo and README are linked below."

---
### Pre-record checklist
- [ ] `python make_sample_data.py` OR confirm real DB is built (`python ingest.py`).
- [ ] Real regattas flagged (ids 8,13,14,15,16); corrupt ones tagged `[noisy-hr]`.
- [ ] MCP server registered: `claude mcp add sailing-coach -- python /abs/path/server.py`.
- [ ] `pytest` green on screen (28 passing) for the Evaluation beat.
- [ ] README, EVALUATION.md, SAILING_COACH.md open in tabs to show.
