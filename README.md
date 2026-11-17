# GTA VI launch-day Twitch CCU forecaster

Entry for [`gta6-twitch-ccu-forecast-01`](https://make.fun/c/gta6-twitch-ccu-forecast-01): forecast how many people watch Grand Theft Auto VI live on Twitch in each hour of its release day, 2026-11-19 (UTC), after the first.

## The problem with persistence

The house baseline says every hour draws what hour 1 drew, with a spread widening like a random walk's. That is honest but wrong for a launch that unlocks country by country. GTA VI unlocks at midnight local time: New Zealand at 2026-11-18T11:00Z, central Europe at 23:00Z, the UK at 00:00Z, the US east coast at 05:00Z and the west coast at 08:00Z. Hour 1 of the UTC day therefore holds the UK and Europe but not the United States, and the day **rises** through hours 6 and 9 before it falls. A series that stays flat at hour 1's print cannot see that.

## What this model does

For each hour `h` of 2..24 it takes the log-ratio of hour `h` to hour 1 from every comparable launch whose `unlock` note says midnight local or rolling — the same unlock shape as GTA VI. Ratios are weighted by how close the comparable's own hour-1 print sits to this case's hour-1 print in log space, with a bandwidth of 1.0: a launch drawing 20k viewers in its first hour says more about another small draw than about a launch drawing 400k. The five quantiles per hour are empirical weighted quantiles of those pooled log-ratios, rescaled by this case's hour-1 print, so no normal-shape assumption is baked in and no practice answer is memorised.

When fewer than three comparables fit an hour, the hour falls back to the house baseline's formula.

## How it was tuned

By leave-one-out over the kit's own comparables — never on the practice answers, which the kit does not ship. Evaluated on launches with the same rolling unlock shape as GTA VI:

| model | pinball loss |
| --- | --- |
| house baseline (persistence, σ = 0.15) | 0.387 |
| median log-ratio, all comparables | 0.207 |
| median log-ratio, rolling comparables only | 0.188 |
| **rolling comparables, scale-weighted quantiles** | **0.149** |

## Run it

```
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only: it reads no network, no clock, no random source, and two runs write the same bytes.

## Output

`<id>.out`, exactly 23 rows for hours 2..24, each with five non-decreasing quantiles at levels `[0.05, 0.25, 0.5, 0.75, 0.95]`:

```json
{"hours":[{"hour":2,"q":[10221.09,10221.09,19229.57,19931.62,21981.84]}]}
```

## License

MIT.
