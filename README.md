# GTA VI Trophy Rarity Forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/jolly-heron-77-5419/gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/jolly-heron-77-5419/gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts, for every trophy of Grand Theft Auto VI on PlayStation 5, the
percent of the players Exophase tracks who will have earned it at
2026-11-26 00:00 UTC — one week after launch — as five quantiles per trophy
(5%, 25%, 50%, 75%, 95%). Scored by pinball loss on the logit scale.

Owner: **jolly-heron-77-5419**

## The model

Exophase's tracked-player base is not a fixed panel. On launch night the
page sat unchanged at 638 players tracked, then one refresh took it to
3,868 and every rate but the one at 100% fell: the new players swept in had
earned far less than the hardcore early adopters. Two forces therefore move
every rate between the checkpoint and the target, pulling in opposite
directions:

- **Dilution** — the tracked base keeps growing through launch week, and
  each new joiner is on average less progressed than the players already
  tracked, dragging rates down (hardest for late-story and grind trophies).
- **Progression** — the players already tracked keep playing, so earners
  keep accumulating (strongest for early-story trophies and easy feats).

Persistence assumes the two cancel exactly. This program models them
separately, from the case's own history:

1. **Tracked-base growth.** The history's distinct reads (consecutive
   identical reads are one Exophase refresh) give the refresh interval and
   the typical per-refresh multiplier of `players_tracked`. Extrapolating
   those over the horizon, with each successive refresh damped, gives
   `N_target`.
2. **Structural median per trophy.** Earners at the target = current
   earners + new joiners' earns (new joiners hold the trophy at a
   class-specific fraction `c` of the current rate) + current players who
   earn it in the meantime (a class-specific fraction `g` of the
   not-yet-earners, scaled by horizon). Dividing by `N_target` gives the
   median. `c` and `g` are set per trophy from what it asks for (story
   chapter, grind size, one-off feat); see the `TROPHIES` table in
   `main.py`.
3. **Cohort trend blend.** A least-squares line of the *cohort* logit rate
   (a read's earners as a share of the last read's tracked base, so
   dilution is stripped out) on `ln(1 + hours since release)`, shrunk
   toward flat, is blended into the median in logit space (65% structural
   / 35% trend) when the history has enough distinct reads. A raw-rate
   trend would double-count early-adopter progression and can saturate
   near 100%, so it is deliberately not used.
4. **Honest spreads.** The logit spread combines a random-walk term
   (`0.5 * sqrt(days)`), a dilution-uncertainty term
   (`0.55 * ln(N_target / N_last)`), and a per-class term (rare grind
   trophies are less predictable than early-story ones), floored at 0.35
   and capped at 2.2 logit units.

The class parameters were sanity-checked against the public Exophase page
as it stood on 2026-11-20 (~40 hours after launch): Chapter 1 at 11.98%,
Chapter 2 at 1.71%, the opening mission at 100%, the platinum at 0.01% —
early-story trophies rising from a low base while most of the list still
sits near the 0.01% floor, exactly the dilution-plus-progression regime
the model is built for.

## Running it

Standard library only, no network, deterministic (no randomness, no
wall-clock use). Reads every `*.in` file in `$MAKEFUN_INPUT_DIR`
(default `/input`) and writes one `*.out` file per case to
`$MAKEFUN_OUTPUT_DIR` (default `/output`):

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Output format per case: `{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}, ...]}`,
one row per trophy, quantiles non-decreasing, each in [0, 100].

## Verification

- Run on the kit's practice cases (`p00`, `p01`): valid output
  (55 trophies × 5 quantiles), deterministic across two runs (byte-identical),
  ~0.06 s per run.
- Scored against a proxy practice answer (earners held constant through
  the documented first refresh, 638 → 3,868 players tracked): pinball loss
  ~1.56 vs ~1.69 for the house persistence baseline; the advantage holds
  across a range of assumed earner growth (1×–3×).
- Scored on synthetic final-like cases (4.5-day horizon, refreshes every
  4 h, growing tracked base): on the variant anchored to the real
  2026-11-20 Exophase snapshot, loss ~0.39 vs ~2.55 for the persistence
  baseline (90% coverage 1.00).
- Edge cases verified: single-read history, `null` rates, missing
  `release_date`, 2-trophy case, 30-minute horizon — all produce valid
  output.

## Entry

Built for the make.fun competition
[gta6-trophy-rarity-forecast-01](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
($250, entries close 2026-11-21 19:30 CST).

---

Built with [make.fun](https://make.fun/r/app9czp7) — referral code `app9czp7`.
