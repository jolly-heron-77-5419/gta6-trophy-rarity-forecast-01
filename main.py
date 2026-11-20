"""GTA VI trophy rarity forecast: a structural dilution + progression forecaster.

Forecasts, for every trophy of Grand Theft Auto VI on PS5, its earn rate on
Exophase at the case's target, as five quantiles (0.05, 0.25, 0.5, 0.75, 0.95).

Why this shape, and what the house baselines miss
--------------------------------------------------
Exophase's tracked-player base is not a fixed panel. On launch night the page
sat unchanged at 638 players tracked, then one refresh took it to 3,868 and
every rate but the one at 100% fell: the new players the refresh swept in had
earned far less than the hardcore early adopters the first read tracked. Two
forces therefore move every rate between the checkpoint and the target, and
they pull in opposite directions:

  * dilution: the tracked base keeps growing through launch week, and each
    new joiner is, on average, less progressed than the players already
    tracked, so rates are dragged down -- hardest for late-story and grind
    trophies a casual new joiner almost never holds;
  * progression: the players already tracked keep playing, so earners keep
    accumulating -- strongest for early-story trophies and easy one-off feats.

A persistence forecast (the house baseline) assumes the two cancel exactly.
A log-time trend fit (the house curve baseline) assumes the past net drift
continues unchanged. This program models the two forces separately, from the
case's own history, and combines them:

  1. Tracked-base growth. The history's distinct reads (consecutive identical
     reads are one Exophase refresh) give the refresh interval and the typical
     per-refresh multiplier of players_tracked. Extrapolating those over the
     horizon, with each successive refresh damped, gives N_target.
  2. Per trophy, a structural median. Earners at the target are the current
     earners, plus the new joiners' earns (new joiners hold the trophy at a
     class-specific fraction `c` of the current rate), plus the current
     players who earn it in the meantime (a class-specific fraction `g` of
     the not-yet-earners, scaled by horizon). Dividing by N_target gives the
     median rate. `c` and `g` are set per trophy from what the trophy asks
     for (story chapter, grind, one-off feat) and were chosen before seeing
     any answer; the table is in TROPHIES below.
  3. A trend blend. A least-squares line of the *cohort* logit rate on
     ln(1 + hours since release) over the distinct reads -- the cohort rate
     is a read's earners as a share of the last read's tracked base, so the
     dilution from the growing base is stripped out and the trend
     extrapolates only progression -- shrunk toward flat, is blended into
     the median in logit space (65% structural / 35% trend) when the history
     has enough distinct reads to fit one. This lets the case's own drift
     correct the structural prior instead of fighting it. A raw-rate trend
     would double-count the early-adopter progression and can saturate near
     100%, so it is deliberately not used.
  4. Honest spreads. The logit spread combines a random-walk term
     (0.5 * sqrt(days), the house baseline's), a dilution-uncertainty term
     (0.55 * ln(N_target / N_last): the further the base grows, the less
     certain the dilution), and a per-class term (rare grind trophies are
     less predictable than early-story ones). Spreads are floored at 0.35
     and capped at 2.2 logit units.

The program is deterministic (no randomness, no wall-clock use, no network),
reads every *.in file in $MAKEFUN_INPUT_DIR (else /input) and writes one
*.out file per case to $MAKEFUN_OUTPUT_DIR (else /output). Standard library
only; runs under `python3 main.py` (Python 3.13 in the grader).
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file would import. (This entry is a single file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# --- per-trophy class parameters -------------------------------------------
# id -> (joiner_factor c, progression g over ~4.5 days, spread_extra)
#   c: the fraction of the current earn rate a newly tracked player holds.
#      Near 1 for the opening mission everyone finishes; near 0 for the
#      platinum / 100% / heavy grinds almost no new joiner holds.
#   g: the fraction of current non-earners (among players already tracked)
#      who earn the trophy over about 4.5 days. High for Chapter 1, which
#      most active players finish in week one; ~0 for the platinum, which
#      needs ~300 hours and cannot be earned by a meaningful share of
#      players in the first week.
#   spread_extra: extra logit spread for the trophy's class (grinds and
#      rare trophies are less predictable than early-story ones).
# Values are set from the trophy's requirement (story chapter, grind size,
# one-off feat), cross-checked against the public trophy guides for GTA VI
# (55 trophies: 1 platinum, 2 gold, 6 silver, 46 bronze; story is 5 chapters
# plus a final mission; platinum needs 100% completion and 250 stunts).
TROPHIES = {
    1: (0.02, 0.002, 0.70),   # Platinum: earn every other trophy
    2: (0.98, 0.00, 0.20),    # Opening mission (Gone Fishing)
    3: (0.55, 0.55, 0.30),    # Chapter 1
    4: (0.40, 0.45, 0.30),    # Chapter 2
    5: (0.30, 0.35, 0.35),    # Chapter 3
    6: (0.22, 0.25, 0.35),    # Chapter 4
    7: (0.15, 0.12, 0.45),    # Final mission (gold)
    8: (0.25, 0.20, 0.40),    # Breakfast Run
    9: (0.22, 0.18, 0.40),    # The Cartel Heist
    10: (0.22, 0.18, 0.40),   # Child's Play
    11: (0.20, 0.15, 0.40),   # Headliners
    12: (0.20, 0.15, 0.40),   # VCIA Takedown
    13: (0.18, 0.12, 0.45),   # Operation Savage Glory
    14: (0.02, 0.002, 0.70),  # 100% Completion (gold)
    15: (0.03, 0.005, 0.65),  # 250 Stunts (silver)
    16: (0.50, 0.35, 0.35),   # Try each activity type once
    17: (0.03, 0.005, 0.65),  # Gold in all Shooting Range challenges
    18: (0.10, 0.02, 0.55),   # Top Fun Drone Race at every location
    19: (0.15, 0.10, 0.50),   # Win 20 different races
    20: (0.30, 0.20, 0.40),   # Beat Cal in a fishing challenge
    21: (0.50, 0.30, 0.35),   # Complete an arcade game
    22: (0.20, 0.15, 0.45),   # Final mission for Andy
    23: (0.20, 0.15, 0.45),   # Final mission for Kenton
    24: (0.20, 0.15, 0.45),   # Final mission for Billy
    25: (0.10, 0.03, 0.55),   # 8 stranger mission strands (silver)
    26: (0.20, 0.15, 0.45),   # Final mission for Randy
    27: (0.20, 0.15, 0.45),   # Final mission for Tyrone
    28: (0.12, 0.08, 0.50),   # Meditate at every spot
    29: (0.25, 0.15, 0.45),   # Hunt a unique animal for Bret
    30: (0.05, 0.005, 0.60),  # 3 Collectible Card sets (silver)
    31: (0.08, 0.02, 0.55),   # WAiNK It at 100 locations (silver)
    32: (0.10, 0.03, 0.55),   # Complete 50 Challenges
    33: (0.35, 0.25, 0.40),   # Lose a 4-star Wanted Level with partner
    34: (0.35, 0.25, 0.40),   # Rob 3 shops back-to-back with partner
    35: (0.45, 0.30, 0.35),   # Discover 100 vehicles
    36: (0.40, 0.25, 0.40),   # 5 enemies in one Combat Focus
    37: (0.30, 0.20, 0.40),   # Unscheduled departure at VCIA
    38: (0.30, 0.20, 0.45),   # Kinda hot in these Rhinos
    39: (0.25, 0.15, 0.45),   # Rob a jewelry store undetected
    40: (0.15, 0.10, 0.50),   # Rob 5 Bank Vaults (silver)
    41: (0.30, 0.20, 0.40),   # Rob an Armored Truck
    42: (0.30, 0.25, 0.40),   # Explore all of Leonida
    43: (0.20, 0.15, 0.45),   # Rob an Illegal Operation of each gang
    44: (0.40, 0.25, 0.40),   # Cocktail on Ocean Beach
    45: (0.35, 0.20, 0.40),   # Smash out of a vehicle showroom
    46: (0.35, 0.20, 0.40),   # Bowling alley follow-through
    47: (0.12, 0.03, 0.50),   # Max Strength for Jason and Lucia
    48: (0.35, 0.25, 0.40),   # Choices made
    49: (0.30, 0.20, 0.45),   # Second time's the charm
    50: (0.25, 0.15, 0.50),   # What the hell just happened?
    51: (0.30, 0.20, 0.45),   # Melee drive-by bowling
    52: (0.20, 0.15, 0.45),   # Launder $250,000 of Marked Bills
    53: (0.40, 0.30, 0.35),   # Spend $100,000 across shops
    54: (0.20, 0.12, 0.45),   # Purchase all garage properties
    55: (0.40, 0.25, 0.40),   # Register 10 vehicles (Scooter Bros)
}

# Fallback (c, g, spread_extra) for a trophy id not in the table above,
# by tier: endgame tiers are near-unreachable in week one, bronze one-offs
# are the most joiner-friendly.
TIER_DEFAULTS = {
    "platinum": (0.02, 0.002, 0.70),
    "gold": (0.10, 0.08, 0.55),
    "silver": (0.08, 0.06, 0.55),
    "bronze": (0.30, 0.20, 0.40),
}

# Fallback last rate (percent) when a trophy has no observed rate at all.
TIER_PRIOR_RATE = {"platinum": 0.5, "gold": 1.0, "silver": 0.8, "bronze": 1.0}

# Reference horizon for the progression fractions g above (days).
G_REFERENCE_DAYS = 4.5
# Damping of the per-refresh tracked-base multiplier (each later refresh
# grows the base less than the one before: the launch surge decays).
REFRESH_DAMPING = 0.75
# Bounds on the extrapolated tracked-base multiplier over the horizon.
N_MULT_MIN, N_MULT_MAX = 1.0, 8.0
# Default refresh behaviour when the history shows no refresh at all
# (a flat page): Exophase refreshes every few hours in launch week.
DEFAULT_REFRESH_HOURS, DEFAULT_REFRESH_MULT = 5.0, 2.5
# Spread bounds (logit units) and the random-walk / dilution coefficients.
SPREAD_MIN, SPREAD_MAX = 0.35, 2.2
SIGMA_RW, SIGMA_DILUTION = 0.5, 0.55
# Blend weights: structural model vs. fitted log-time trend, in logit space.
W_STRUCTURAL, W_TREND = 0.65, 0.35


def clamp_pct(x: float) -> float:
    return min(99.99, max(0.01, x))


def logit(pct: float) -> float:
    p = clamp_pct(pct) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit(lg: float) -> float:
    if lg >= 0:
        return 100.0 / (1.0 + math.exp(-lg))
    e = math.exp(lg)
    return 100.0 * e / (1.0 + e)


def round4(x: float):
    """Round to 4 decimals, half up (as JavaScript's Math.round does)."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value == int(value) else value


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else 0.5 * (ys[n // 2 - 1] + ys[n // 2])


def distinct_snapshots(case):
    """Collapse consecutive identical reads into one snapshot each.

    Exophase only changes its counts on a refresh, so a run of identical
    reads is one observation, not many. Returns [(time, players, rates)].
    """
    snaps = []
    for read in case.get("history", []):
        key = (read.get("players_tracked"), tuple(read.get("rates") or []))
        if snaps and snaps[-1][1] == key[0] and snaps[-1][2] == key[1]:
            continue
        snaps.append((parse_time(read["at"]), key[0], key[1]))
    return snaps


def forecast_n_multiplier(snaps, horizon_hours: float) -> float:
    """Expected players_tracked multiplier between the last read and target.

    From the distinct snapshots: the median gap between refreshes and the
    median per-refresh growth of players_tracked. Growth per refresh is
    damped geometrically (the launch surge decays) and the total multiplier
    is capped, so a long horizon cannot extrapolate to an absurd base.
    """
    if len(snaps) < 2 or horizon_hours <= 0:
        interval, mult = DEFAULT_REFRESH_HOURS, DEFAULT_REFRESH_MULT
    else:
        gaps = [
            (snaps[i + 1][0] - snaps[i][0]).total_seconds() / 3600.0
            for i in range(len(snaps) - 1)
        ]
        gaps = [g for g in gaps if g > 0]
        interval = median(gaps) if gaps else DEFAULT_REFRESH_HOURS
        ratios = []
        for i in range(len(snaps) - 1):
            n0, n1 = snaps[i][1], snaps[i + 1][1]
            if n0 and n1 and n1 > n0:
                ratios.append(n1 / n0)
        mult = median(ratios) if ratios else DEFAULT_REFRESH_MULT
        interval = min(max(interval, 0.5), 48.0)
        mult = min(max(mult, 1.0), 6.0)
    expected_refreshes = horizon_hours / interval
    total = 1.0
    whole = int(expected_refreshes)
    for k in range(whole):
        total *= 1.0 + (mult - 1.0) * (REFRESH_DAMPING ** k)
    frac = expected_refreshes - whole
    if frac > 0:
        total *= 1.0 + (mult - 1.0) * (REFRESH_DAMPING ** whole) * frac
    return min(max(total, N_MULT_MIN), N_MULT_MAX)


def trend_logit(snaps, idx: int, release: datetime, x_target: float, x_last: float,
                n_last: float, n_mult: float):
    """Shrunk least-squares trend of the *cohort* logit rate on ln(1 + hours).

    The cohort rate at a read is its earners as a share of the last read's
    tracked base, u = rate * N(t) / N_last: it strips out the dilution from
    the tracked base growing, so the trend extrapolates only progression
    (earners accumulating), not the composition change the structural model
    already accounts for. Blending a raw-rate trend instead would count the
    early-adopter progression twice and can saturate near 100%.

    Returns the trend-implied rate at the target (percent), or None when the
    history has too few distinct reads to fit. The slope is shrunk toward
    flat by n / (n + 2) and the total move from the last read is capped at
    1.0 logit unit.
    """
    pts = []
    for (t, n, rates) in snaps:
        r = rates[idx] if idx < len(rates) else None
        if r is None or not n or not n_last:
            continue
        pts.append((t, r * n / n_last))
    if len(pts) < 3:
        return None
    xs = [math.log1p((t - release).total_seconds() / 3600.0) for (t, _u) in pts]
    ys = [logit(u) for (_t, u) in pts]
    if max(xs) - min(xs) < 1e-9:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den < 1e-12:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    slope *= len(pts) / (len(pts) + 2.0)
    move = slope * (x_target - x_last)
    move = min(max(move, -1.0), 1.0)
    u_target = inv_logit(ys[-1] + move)
    return clamp_pct(u_target / n_mult) if n_mult else None


def forecast_case(case: dict, name: str) -> dict:
    trophies = case["trophies"]
    history = case.get("history", [])
    if not history:
        raise ValueError(f"{name} has no history")
    horizon_minutes = float(case["horizon_minutes"])
    horizon_days = horizon_minutes / 1440.0
    horizon_hours = horizon_minutes / 60.0

    release_raw = (case.get("game") or {}).get("release_date") or "2026-11-19"
    try:
        release = parse_time(release_raw) if "T" in release_raw else datetime(
            *map(int, release_raw.split("-")), tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        release = parse_time(history[0]["at"])

    snaps = distinct_snapshots(case)
    last_time, last_n, last_rates = snaps[-1]
    n_last = last_n or 0
    n_mult = forecast_n_multiplier(snaps, horizon_hours)
    n_target = n_last * n_mult if n_last else 0

    # Progression fractions scale with horizon: g is quoted for ~4.5 days,
    # and earning saturates (1 - exp(-h / 3 days)), normalised at 4.5 days.
    g_scale = (1.0 - math.exp(-horizon_days / 3.0)) / (
        1.0 - math.exp(-G_REFERENCE_DAYS / 3.0)
    ) if horizon_days > 0 else 0.0
    g_scale = min(max(g_scale, 0.0), 1.5)

    x_target = math.log1p((parse_time(case["target"]) - release).total_seconds() / 3600.0)
    x_last = math.log1p((last_time - release).total_seconds() / 3600.0)

    rows = []
    for i, trophy in enumerate(trophies):
        tid = trophy["id"]
        tier = (trophy.get("tier") or "bronze").lower()
        # Last observed rate for this trophy (walk back over nulls).
        r_last = None
        for (_t, _n, rates) in reversed(snaps):
            if i < len(rates) and rates[i] is not None:
                r_last = float(rates[i])
                break
        if r_last is None:
            r_last = TIER_PRIOR_RATE.get(tier, 1.0)
        c, g, s_extra = TROPHIES.get(tid, TIER_DEFAULTS.get(tier, (0.30, 0.20, 0.40)))

        # --- structural median: dilution + progression -------------------
        if n_last and n_target:
            earners = r_last / 100.0 * n_last
            new_joiners = n_target - n_last
            earners += new_joiners * c * r_last / 100.0
            earners += (n_last - earners) * g * g_scale if n_last > earners else 0.0
            r_struct = 100.0 * earners / n_target
        else:
            r_struct = r_last
        r_struct = clamp_pct(r_struct)

        # --- blend with the fitted trend ---------------------------------
        lg_med = logit(r_struct)
        r_trend = trend_logit(snaps, i, release, x_target, x_last, n_last, n_mult)
        if r_trend is not None:
            lg_med = W_STRUCTURAL * lg_med + W_TREND * logit(r_trend)

        # A trophy already at 100% stays (nearly) there: every tracked
        # player finished the opening mission, and new joiners do too.
        if r_last >= 99.99:
            lg_med = max(lg_med, logit(99.5))

        # --- spread -------------------------------------------------------
        spread = math.sqrt(
            (SIGMA_RW ** 2) * horizon_days
            + (SIGMA_DILUTION * math.log(n_mult)) ** 2
            + s_extra ** 2
        )
        spread = min(max(spread, SPREAD_MIN), SPREAD_MAX)

        qs = []
        prev = None
        for z in Z:
            q = round4(clamp_pct(inv_logit(lg_med + z * spread)))
            if prev is not None and q < prev:
                q = prev
            qs.append(q)
            prev = q
        rows.append({"id": tid, "q": qs})
    return {"trophies": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        out = json.dumps(forecast, separators=(",", ":")) + "\n"
        if len(out.encode("utf-8")) > 65536:
            raise ValueError(f"{path.name}: forecast exceeds 65536 bytes")
        (OUTPUT_DIR / f"{path.stem}.out").write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
