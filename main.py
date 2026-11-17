"""GTA VI launch-day Twitch CCU forecaster: rolling-unlock comparables.

The house baseline assumes every hour draws what hour 1 drew. GTA VI does not
unlock that way: it unlocks at midnight local time, country by country, so hour 1
of the UTC day (00:00-01:00Z) holds only the UK, central Europe and New Zealand,
while the US east coast unlocks at hour 6 and the west coast at hour 9. A launch
day therefore rises after hour 1 before it falls, and the only honest place to
read that shape is in launches that unlocked the same way.

So the model fits a log-reciprocal curve of hour h to hour 1 taken from
comparables whose `unlock` note describes a midnight-local or rolling unlock. Each
comparable's log-ratio is weighted by how close its own hour-1 print sits to this
case's hour-1 print in log space: a launch drawing 20k viewers on its first hour
tells you more about another small draw than about a launch drawing 400k. The five
quantiles per hour are then empirical weighted quantiles of those log-ratios,
rescaled by this case's hour-1 print, so no normal-shape assumption is baked in.

Standard library only. Frozen: it reads no network, no clock, no random source.
"""

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The house baseline's spread, used only as a fallback when no comparable fits.
Z = [-1.645, -0.674, 0, 0.674, 1.645]
SIGMA = 0.15
# Width, in natural-log units of hour-1 viewers, of the weight a comparable's
# scale earns. Tuned by leave-one-out on the kit's own comparables, never on the
# practice answers.
SCALE_BANDWIDTH = 1.0
# A comparable needs at least this many scored hours of its release day.
MIN_HOURS = 22
# Below this many usable comparables the curve is too thin to trust.
MIN_COMPARABLES = 3


def round2(x: float):
    """x rounded to 2 decimals, half up, as JavaScript's Math.round(x * 100) / 100."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if value.is_integer() else value


def release_profile(comparable):
    """Hour-of-day -> viewers, for the comparable's own release day only."""
    day = str(comparable.get("day_start", ""))[:10]
    if not day:
        return {}
    by_hour = {}
    for row in comparable.get("hourly") or []:
        stamp = str(row.get("from", ""))
        if stamp[:10] != day:
            continue
        viewers = row.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            by_hour[int(stamp[11:13])] = float(viewers)
    return by_hour


def unlocked_like_the_case(comparable):
    """True when the note says the launch unlocked at midnight local time, rolling."""
    note = str(comparable.get("unlock") or "").lower()
    return "midnight local" in note or "rolling" in note


def weighted_quantile(pairs, level):
    """Empirical weighted quantile of (value, weight) pairs, interpolated between points.

    With a dozen comparables the outer levels would land exactly on the largest or
    smallest observed ratio and collapse onto the level beside them. So each tail is
    extended by one synthetic point carrying the gap of the two outermost points and
    a small weight: the quantile then reads a plausible spread rather than a plateau.
    """
    if not pairs:
        return 0.0
    ordered = sorted(pairs)
    if len(ordered) >= 2:
        low_gap = abs(ordered[0][0] - ordered[1][0])
        high_gap = abs(ordered[-1][0] - ordered[-2][0])
        total_weight = sum(weight for _, weight in ordered)
        synthetic = max(total_weight / (len(ordered) * 10.0), 1e-9)
        ordered = ([(ordered[0][0] - low_gap, synthetic)] + ordered
                   + [(ordered[-1][0] + high_gap, synthetic)])
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    target = level * total
    seen = 0.0
    for index, (value, weight) in enumerate(ordered):
        nxt = seen + weight
        if nxt >= target and weight > 0:
            if index + 1 < len(ordered):
                low_value, high_value = value, ordered[index + 1][0]
                fraction = (target - seen) / weight
                return low_value + (high_value - low_value) * fraction
            return value
        seen = nxt
    return ordered[-1][0]


def collect_ratios(case, p1):
    """Weighted log-ratios of hour h to hour 1, pooled over comparable launches."""
    pooled = {}
    game = str((case.get("game") or {}).get("name") or "").strip().lower()
    for comparable in case.get("comparables") or []:
        if not unlocked_like_the_case(comparable):
            continue
        if str(comparable.get("name") or "").strip().lower() == game:
            continue
        profile = release_profile(comparable)
        base = profile.get(1)
        if not base or base <= 0 or len(profile) < MIN_HOURS:
            continue
        weight = math.exp(-((math.log(p1) - math.log(base)) / SCALE_BANDWIDTH) ** 2)
        for hour, viewers in profile.items():
            if hour < 2 or viewers <= 0:
                continue
            pooled.setdefault(hour, []).append((math.log(viewers / base), weight))
    return pooled


def fallback_quantiles(p1, hour):
    """The house baseline, for when the comparable set is too thin."""
    return [round2(p1 * math.exp(z * SIGMA * math.sqrt(hour - 1))) for z in Z]


def forecast_hour(p1, hour, pooled):
    """The five quantiles of one hour's count."""
    pairs = pooled.get(hour)
    if not pairs or len(pairs) < MIN_COMPARABLES:
        return fallback_quantiles(p1, hour)
    centre = math.log(p1)
    values = [math.exp(centre + weighted_quantile(pairs, level)) for level in LEVELS]
    quantiles = []
    previous = 0.0
    for value in values:
        # The spec asks for finite, positive, non-decreasing, at most 1e9.
        value = min(max(value, previous if previous > 0 else 0.01), 1e9)
        quantiles.append(round2(value))
        previous = value
    return quantiles


def forecast_case(case, name):
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, not {LEVELS}")
    first = next((row for row in case.get("known") or [] if row.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first.get("viewers") or 1))
    pooled = collect_ratios(case, p1)
    rows = []
    for row in case.get("forecast") or []:
        hour = int(row["hour"])
        rows.append({"hour": hour, "q": forecast_hour(p1, hour, pooled)})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        case_id = case.get("id") or path.stem
        forecast = forecast_case(case, path.name)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{case_id}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
