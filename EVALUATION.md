# Evaluation

How I validated that this is a *useful sailing coach*, not just code that runs. Four kinds of
evidence: metric ground-truth, the core-claim test on real data, a failure analysis, and
expert-in-the-loop confirmation (I'm the athlete).

All numbers below are from my real Garmin data: **7 power-equipped cycling rides + 9 sailing
sessions (5 regattas, 4 training).**

---

## 1. Metric ground-truth — automated tests (`pytest`, 28 passing)
The metric math is checked deterministically, independent of any FIT file or MCP client:
- **Normalized power:** constant 200 W ⇒ NP = 200.0; a sustained high/low split ⇒ NP > mean
  (4th-power weighting), exactly as defined.
- **Aerobic decoupling:** a clean first-half/second-half HR split ⇒ the exact expected % (e.g.
  ratios 2.0→1.6 ⇒ 20.0%).
- **HR time-in-zone:** one sample per zone lands in the right zone; boundaries are exclusive-upper.
- **Query layer:** the date-window filter, race/training split, and data-quality exclusion all
  tested against a seeded throwaway DB.

## 2. Core-claim test — "you can't read sailing readiness from session-level HR"
**Claim:** a regatta file is mostly waiting, so its whole-session HR *understates* race intensity —
and a generic endurance tool would miss this.

**Step 1 — the naïve view (`compare_race_vs_training`, real data):**

| | avg HR | Z3+ share | Z4 share |
|---|---|---|---|
| Regattas (whole-session) | **145** | 43% | 19% |
| Training | **154** | 58% | 33% |

Read naïvely this says *"training is already harder than racing — you're fine."* For sailing,
that conclusion is wrong.

**Step 2 — the sailing-aware view (`session_hr_timeline`, real regatta 2025-11-29):**
the detector auto-segmented the day into its actual races:

| race block | duration | avg HR | peak HR |
|---|---|---|---|
| 41–79 min | 38 min | 176 | 190 |
| 110–155 min | 45 min | 154 | 179 |
| 226–270 min | 44 min | 166 | 182 |

Only **45% of the 4h45m day was racing**; the rest was tow-out, warmup, and between-race
drifting. The **race-block HR (154–176, peak 190) is far above the whole-session average (141)**.

**Conclusion:** the dilution is real and large. Race intensity lives in Z3–Z4 sustained for
~40–45 min; the session average hides it. The coaching brain (`SAILING_COACH.md` §4) instructs
the coach to segment races before judging readiness, and `compare_race_vs_training` now warns
about exactly this trap and points to the timeline tool.

## 3. Failure analysis — the detector is only as good as the data
On a regatta I know cold (European Championship, Sweden — a windy day with **3 races**), the
timeline detector returned **0 races**. Investigation of the raw FIT:
- per-second HR: **median 63 bpm, max 140, only 2 of 7,713 records ≥ 140** — clearly not a hard
  9-hour racing day.
- Cause: I started the watch and **left it on shore**, carrying only the HR strap. The per-second
  stream the watch logged is wrist/ambient garbage; the true on-water HR never made it into the
  time series.

This is an honest limitation, not a bug to hide: **HR-only race detection fails when the HR
capture fails.** The fix is to cross-validate with the GPS track (a race is an unmistakable
upwind zig-zag) and speed (smooth and non-zero during a race) — see README "Future work."
Meanwhile the system **tags such files `[noisy-hr]` and excludes them from HR comparisons** so
they can't silently corrupt the analysis.

## 4. Expert-in-the-loop
I validated the reads against my own judgment as the athlete:
- Confirmed the regatta race counts and the race/waiting structure the timeline produced.
- Corrected the coach where generic endurance logic was wrong for sailing (multi-day durability
  over single-peak, weight-targeted strength, isometric hiking, light-air vs heavy-air fatigue) —
  captured in `SAILING_COACH.md` §6.
- Caught a real config error along the way: my `hr_max` was set to 195 but my true max is 208,
  which had been inflating every session into Z4/Z5. Fixed and re-ingested.
