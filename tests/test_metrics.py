"""Unit tests for the pure metric functions in ingest.py.

These are deterministic: constant power makes NP equal that power, a clean
HR-vs-power split makes decoupling exact, etc. No FIT file or DB required.
"""
import math
import ingest


def _recs(power=None, hr=None, n=120):
    """Build n per-second records with optional constant power/hr."""
    return [{"t": float(i), "power": power, "hr": hr,
             "cadence": None, "speed": None, "lat": None, "lon": None}
            for i in range(n)]


# ---------- HR time-in-zone ----------

BOUNDS = {"z1_upper": 0.60, "z2_upper": 0.70, "z3_upper": 0.80, "z4_upper": 0.90}


def test_hr_zones_one_sample_per_zone():
    # hr_max=200 → zone edges at 120/140/160/180 bpm
    recs = [{"hr": h} for h in (100, 130, 150, 170, 190)]
    z = ingest.hr_zones(recs, hr_max=200, bounds=BOUNDS)
    assert z == {"z1": 1, "z2": 1, "z3": 1, "z4": 1, "z5": 1}


def test_hr_zones_boundary_is_exclusive_upper():
    # frac == z1_upper (0.60 → 120 bpm) should fall OUT of z1 (uses strict <)
    z = ingest.hr_zones([{"hr": 120}], hr_max=200, bounds=BOUNDS)
    assert z["z1"] == 0 and z["z2"] == 1


def test_hr_zones_ignores_missing_hr():
    z = ingest.hr_zones([{"hr": None}, {"hr": 0}, {"hr": 150}], hr_max=200, bounds=BOUNDS)
    assert sum(z.values()) == 1  # only the 150 bpm sample counts


# ---------- normalized power ----------

def test_normalized_power_constant_equals_value():
    assert ingest.normalized_power(_recs(power=200)) == 200.0


def test_normalized_power_needs_30_samples():
    assert ingest.normalized_power(_recs(power=200, n=29)) is None


def test_normalized_power_weights_sustained_spikes_above_mean():
    # 60s at 100 then 60s at 300 averages 200, but NP exceeds it: the 4th-power
    # weighting penalises variable efforts sustained beyond the 30s rolling window.
    recs = [{"power": 100, "hr": None} for _ in range(60)] + \
           [{"power": 300, "hr": None} for _ in range(60)]
    assert ingest.normalized_power(recs) > 200


# ---------- aerobic decoupling ----------

def test_decoupling_zero_when_stable():
    assert ingest.decoupling(_recs(power=200, hr=150)) == 0.0


def test_decoupling_positive_when_hr_drifts_up():
    # 1st half ratio 200/100=2.0, 2nd half 200/125=1.6 → (2.0-1.6)/2.0 = 20%
    first = [{"power": 200, "hr": 100} for _ in range(60)]
    second = [{"power": 200, "hr": 125} for _ in range(60)]
    assert ingest.decoupling(first + second) == 20.0


def test_decoupling_needs_60_pairs():
    assert ingest.decoupling(_recs(power=200, hr=150, n=59)) is None


# ---------- helpers ----------

def test_avg_and_mx_skip_none():
    recs = [{"hr": 100}, {"hr": None}, {"hr": 200}]
    assert ingest.avg(recs, "hr") == 150.0
    assert ingest.mx(recs, "hr") == 200


def test_avg_empty_is_none():
    assert ingest.avg([{"hr": None}], "hr") is None


def test_semicircles_conversion():
    assert ingest._semicircles(None) is None
    assert math.isclose(ingest._semicircles(2**31), 180.0)
    assert math.isclose(ingest._semicircles(-(2**31)), -180.0)
