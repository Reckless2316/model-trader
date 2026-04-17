# Designing Gates

This is the hardest part of the pipeline and the one that can't be automated.
You have a strategy document (prose) and you need a sequence of pass/fail
checks (code). This document is about how to make that translation well.

## What a gate is

A **gate** is one self-contained pass/fail check. It asks one question against
the market state. If the answer is "no", the setup is rejected and the rest of
the gates don't run. If "yes", the setup proceeds to the next gate.

The whole scanner is just an ordered chain of gates. The last gate sets the
entry/stop/target and flips the result to `TAKE`. Everything before it is
filtering.

A gate should:

- Check exactly one thing.
- Have a clear name (`HTF_BIAS`, `RETRACE_INTO_FVG`, `CISD_CONFIRM`).
- Set a specific `result.reason` when it fails ("No HTF FVG within 50 bars",
  not "Filter rejected").
- Take ~5-30 lines. If it's longer, you're probably checking two things.

## The mental move: prose -> gates

When you read the strategy doc, look for sentences shaped like this:

- "I only take this when X is true."           -> `if not X: skip`
- "The first thing I look for is Y."           -> early gate that checks Y
- "I avoid Z."                                 -> reject gate for Z
- "I wait for confirmation from W."            -> WAIT-status gate that
                                                  flips to TAKE when W happens

Most strategies have a handful of these. The art is in not adding gates the
trader didn't actually use ("I figure they probably also want X") and not
omitting ones they did ("eh, that one's vague, skip it").

## Ordering: cheap and selective first

Gates run in order. A scan that fails at gate 1 doesn't run gate 2. So:

1. **Cheapest first.** A check on a single field of a single candle beats one
   that scans 200 bars.
2. **Most selective first.** A check that rejects 95% of setups beats one
   that rejects 20%.

When these conflict, lean toward selectivity. Saving an HTTP call beats
saving a numpy slice; rejecting 100x more candidates beats either.

A typical order:

```
GATE 1: Basic data sanity      (do we have the candles? cheap, common reject)
GATE 2: HTF context            (1h or 4h structure — usually rejects 80%+)
GATE 3: LTF trigger            (5m or 15m pattern — the actual setup)
GATE 4: Entry timing           (1m or 5m confirmation candle)
GATE 5: Stop / target / take   (compute levels, set TAKE)
```

## The "every gate logs" rule

```python
result.gates_passed.append("HTF_BIAS")    # on success
result.reason = "No HTF FVG within 50 bars"  # on failure
return result
```

Both branches matter. The dashboard renders `gates_passed` so you can see
how far each symbol got. The journal records `reason` so you can later ask
"why did we skip 200 setups today?" and have an answer.

## Patterns

### Gate that just inspects state

```python
# GATE 1: Have enough data
if len(data["1h"]) < 50:
    result.reason = "Insufficient 1h history"
    return result
result.gates_passed.append("DATA_OK")
```

### Gate that uses a detector

```python
# GATE 2: HTF failure swing exists
swings = detect_swings(data["1h"][-50:])
fail_swings = detect_failure_swings(swings)
if not fail_swings:
    result.reason = "No HTF failure swing"
    return result
target_swing = fail_swings[-1]
result.gates_passed.append("HTF_DRAW")
```

### Gate that branches by direction

```python
# GATE 3: LTF FVG aligned with HTF bias
direction = "long" if target_swing["type"] == "low" else "short"
fvgs = detect_fvg(data["5m"][-100:], direction=direction)
if not fvgs:
    result.reason = f"No {direction} FVG on 5m"
    return result
result.gates_passed.append("LTF_FVG")
```

### Final gate: set entry/stop/target

```python
# GATE N: Compute levels and TAKE
entry = data["1m"][-1]["close"]
nearest_swing = find_nearest_swing(data["5m"], direction)
stop = nearest_swing["price"]
risk = abs(entry - stop)
target = entry + risk if direction == "long" else entry - risk  # 1R

result.entry = entry
result.stop = stop
result.target = target
result.direction = direction
result.status = SetupStatus.TAKE
result.reason = "All gates passed"
return result
```

## When to use WAIT vs SKIP

- **`SKIP`** means "no, this setup is dead, move on."
- **`WAIT`** means "the setup is forming, check again next scan."

Use `WAIT` for the case where the trader is sitting on their hands waiting
for one specific event — e.g., a CISD candle that hasn't printed yet, or a
retrace that hasn't reached the entry zone. The dashboard shows `WAIT`
setups distinctly so you can watch them mature.

Most failed gates produce `SKIP`. `WAIT` is for the last 1-2 gates only.

## Common mistakes

- **Scoring instead of gating.** "Setup gets +1 if HTF bias, +1 if SMT, +1
  if displacement..." This sounds smart and underperforms in practice.
  Pass/fail is more honest about what you actually trust.

- **Combining gates.** "If (HTF bias AND retrace AND CISD) then TAKE" —
  works, but you can't see in the dashboard which condition failed. Split
  them.

- **Letting unset levels through.** A `TAKE` result with `entry=None` will
  crash the paper trader. The final gate is responsible for setting all
  four of `entry`, `stop`, `target`, `direction`.

- **Reading too much into a few trades.** A 60% WR over 8 trades is noise.
  Get to 50+ before tuning.

- **Tweaking gates to fit backtest results.** If you keep loosening a gate
  until the backtest looks good, you've overfit. Better: state your gate's
  rule before running the backtest, run it, and accept the result.

## Sanity checks before going live

- Run the backtest. Does the scanner produce trades? Are most gate-fail
  reasons what you'd expect?
- Run the live monitor for an hour during active hours. Does the dashboard
  show symbols progressing through gates? Or is everything stuck at gate 1?
- Trigger one execution by hand (set thresholds permissively). Does
  `trades.json` get a properly-formed entry?
- Restore the real thresholds.

If all three pass, you're ready to run overnight.
