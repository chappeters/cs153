# Evaluation

How I validated that this is a *useful sailing coach*, not just code that runs. Four kinds of
evidence: metric ground-truth, the core-claim test on real data, an iteration/debugging story
with expert-in-the-loop feedback, and remaining honest limitations.

All numbers are from my real Garmin data: **7 power-equipped cycling rides + 9 sailing sessions
(5 regattas, 4 training).**

---

## 1. Metric ground-truth — automated tests (`pytest`, 29 passing)
The math is checked deterministically, independent of any FIT file or MCP client:
- **Normalized power:** constant 200 W ⇒ NP = 200.0; a sustained high/low split ⇒ NP > mean.
- **Aerobic decoupling:** a clean first/second-half HR split ⇒ the exact expected % (2.0→1.6 ⇒ 20%).
- **HR time-in-zone:** samples land in the right zone; boundaries exclusive-upper.
- **Race detector:** detects varying elevated blocks, rejects flat (artifact) blocks and easy days.
- **Query layer:** date-window filter, race/training split, data-quality exclusion.

## 2. Core-claim test — "you can't read sailing readiness from session-level HR"
**Claim:** a regatta file is mostly waiting, so its whole-session HR *understates* race intensity —
and a generic endurance tool would miss this.

**The naïve view (`compare_race_vs_training`, real data):**

| | avg HR | Z3+ share |
|---|---|---|
| Regattas (whole-session) | **138** | 31% |
| Training | **154** | 58% |

Read literally this says *"training is way harder than racing — you're over-prepared."* For
sailing that's wrong, and dangerously so before a regatta block.

**The sailing-aware view (`session_hr_timeline`):** segmenting the actual races out of the file
tells the truth. On my **European Championship in Sweden** — a 9.4-hour file, which I know had
**exactly 3 races** — the detector auto-found exactly 3:

| race block | duration | avg HR | peak HR |
|---|---|---|---|
| 126–182 min | 56 min | 156 | 188 |
| 237–298 min | 61 min | **185** | **202** |
| 315–385 min | 70 min | 169 | 193 |

Only **33% of the day was racing**; the other two-thirds (~110 bpm — tow-out, waiting, drifting)
is what dragged the whole-session average down to 138. The **race blocks (156–185, peak 202 = Z5)**
are the real demand. The detector reproduces this across regattas (e.g. another clean day,
2025-11-29, segments into 3 races of 38/45/44 min at 176/154/166 bpm).

**Conclusion:** the dilution is real and large. The coaching brain (`SAILING_COACH.md` §4) tells
the coach to segment races before judging readiness, and `compare_race_vs_training` now warns
about the trap and points to the timeline tool.

## 3. Iteration + expert-in-the-loop (the debugging story)
This is the strongest evidence the system is grounded in *my* reality, not generic assumptions.

The race detector initially found **0 races on my three long regattas** — the per-second HR in
those files maxed out around 132–140 bpm across multi-hour racing days, which is impossible for
real racing. My first read was "corrupt HR / watch left on shore."

**As the athlete I knew that was wrong** — my chest strap recorded the entire time, so the HR
*had* to be accurate. That expert correction sent me back into the raw FIT, where I found the
file carries **two HR streams**: the `record` messages held the watch's *optical* HR (the low
one), while my **chest-strap HR lived in separate `hr` messages** (`filtered_bpm`) — whose mean
(145) and max (205) exactly matched the session summary. My ingest was only reading `record`.

I fixed the parser to read and time-align the `hr` messages, re-ingested, and **every regatta now
segments correctly**, including the 9-hour Sweden day (3 races, peak 202). A real bug, caught by
expert feedback, traced to the data, and fixed — with the result validated against my memory of
the event.

## 4. Remaining honest limitations
- **HR-only detection.** Race-finding keys on sustained, varying HR. The fix above made it robust
  on all my files, but the principled next step is to fuse the **GPS track** (a race is an
  unmistakable upwind zig-zag) and **speed** (smooth, non-zero during a race) — see README
  "Future work." A `[noisy-hr]` tag + exclusion still exists for any genuinely unusable file.
- **GPS/speed unreliable on the Sweden file** (the watch sat on shore for those): its distance
  reads 4.9 km for a full day. HR is fine (strap), but GPS-based features can't use that file.
- **Sparse-sensor tails.** Very long files can have a flat, stale HR tail; the detector now drops
  flat blocks (a real race varies) so they aren't mistaken for races.
