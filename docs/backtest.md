# Backtesting

Validate your gates against history before going live with paper money. The
backtest replays past candles through your scanner one bar at a time and
simulates trades with the same SL/TP logic the live paper trader uses.

## What you need to implement

Your scanner already has `evaluate(symbol)` for live trading — it calls the
data adapter to fetch fresh candles. The backtest needs a parallel method
that reads from a passed-in history dict instead:

```python
def evaluate_at(self, symbol: str, hist: dict, corr_hist: dict, ts: int) -> SetupResult:
    """Backtest variant of evaluate(). Same gate logic, different data source."""
    ...
```

Arguments:

- `symbol` — the symbol being evaluated
- `hist` — `{timeframe: list[Candle]}` for `symbol`. Already truncated to
  candles at-or-before `ts` by the runner — you can use the lists as-is.
- `corr_hist` — same shape, for the correlation symbol if any (used for SMT)
- `ts` — current timestamp in milliseconds

The method must return a `SetupResult` with the same semantics as `evaluate()`.

## The translation

Most of your gates are already in `evaluate()`. The mechanical changes:

```python
# In evaluate():
candles_1h = self.data.fetch_candles(symbol, "1h", limit=200)
candles_5m = self.data.fetch_candles(symbol, "5m", limit=200)

# In evaluate_at():
candles_1h = hist.get("1h", [])
candles_5m = hist.get("5m", [])
```

The detector calls (`detect_swings`, `detect_fvg`, etc.) are identical because
they're pure functions over candle lists.

For SMT divergence which uses a correlated symbol:

```python
# In evaluate():
corr_candles = self.data.fetch_candles(self.corr_symbol(symbol), "5m", limit=100)

# In evaluate_at():
corr_candles = corr_hist.get("5m", [])
```

The cleanest pattern is to factor your gate logic into a private helper that
takes the data dicts as arguments, then call it from both `evaluate` and
`evaluate_at`:

```python
def _run_gates(self, symbol, data, corr_data) -> SetupResult:
    # all gate logic here
    ...

def evaluate(self, symbol):
    data = self.fetch_data(symbol)
    corr_data = self.fetch_correlation(symbol, [...])
    return self._run_gates(symbol, data, corr_data)

def evaluate_at(self, symbol, hist, corr_hist, ts):
    return self._run_gates(symbol, hist, corr_hist)
```

This way you write the gates once.

## Running it

```bash
cd traders/my_trader
python backtest.py
```

The default `backtest.py` template runs 7 days of history. Edit the `days=`
argument to change.

Output looks like:

```
  BTC: 12 trades (W=8 L=4)
  ETH: 9 trades (W=5 L=4)
  SOL: 6 trades (W=3 L=3)

Total: 27 trades
W/L: 16/11 (59.3% WR)
Total R: 5.2
Avg R: 0.19
Profit factor: 1.45
```

## How the runner simulates trades

For each symbol:

1. Fetch full history for every timeframe in the config
2. Walk `step_timeframe` (default 5m) bar by bar starting at index 200
3. If a trade is open: check the current bar's high/low against SL/TP
4. If no trade open and not in cooldown: call `evaluate_at(...)`
5. If `TAKE`: open a trade at the result's entry/stop/target
6. After a trade closes: skip `cooldown_bars` (default 6) before evaluating again

The cooldown is a coarse anti-thrash mechanism — the live system uses smarter
filters (`is_duplicate_setup`, `is_invalidated_level`) that depend on the
journal. The backtest just uses the simple bar-count.

Trades are won/lost based on whether the bar's high/low touches TP/SL. If
both happen in the same bar, the simulator favors the loss (conservative
assumption — you can't know which side filled first intra-bar).

## Reading the results

A few things to look at, in order of importance:

1. **Trade count.** Under ~10 total over 7 days and you can't draw any
   conclusion. Over ~200 and your gates might be too loose. Aim for a
   handful per day across all symbols.

2. **Per-symbol breakdown.** If one symbol contributes 80% of trades or 80%
   of profit, your gates are probably overfit to that symbol's character.
   You either trade only that symbol, or you generalize the gate.

3. **Win rate × avg R.** Neither alone tells you anything. A 30% WR with
   3R targets is great; a 70% WR with 0.3R targets is mediocre. Profit
   factor (gross win / gross loss) folds both into one number.

4. **Failure modes.** Look at the lossing trades — are they clustered in
   time? On one symbol? Same direction? That's where to focus iteration.

## Common pitfalls

- **Lookahead bias.** If `evaluate_at` peeks at candles after `ts`, your
  results are fake. The runner already truncates `hist` for you, but if
  you do anything like `data["1m"][i+1]` you'll leak. Default to working
  with `data["1m"][-1]` (the most recent allowed candle) and slicing
  backward from there.

- **Overfitting.** If you change the gates, re-run the backtest, see better
  numbers, and call it progress — you're probably just memorizing the
  noise. The test of a real improvement is that it survives on data the
  scanner has never seen (a different week, a different symbol set).

- **Trusting tiny samples.** A backtest with 12 trades is one good week
  away from being a backtest with 6 winners. Get to 50+ closed trades
  before treating any number as signal.
