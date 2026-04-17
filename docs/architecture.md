# Architecture

How the runtime pieces fit together. Read [`pipeline.md`](pipeline.md) first if
you haven't — that document covers the workflow; this one covers the code.

## Layered view

```
                +--------------------------------------+
                |          run_monitor (loop)          |
                +--+------------+------------+---------+
                   |            |            |
            +------v---+   +----v-----+  +---v----------+
            |  Scanner |   |  Filters |  |  PaperTrader |
            +------+---+   +----+-----+  +---+----------+
                   |            |            |
                   |            +-----+      |
                   |                  |      |
                   v                  v      v
                +--+------+      +----+------+--+
                | Detectors|      |  Journal     |
                +--+------+       |  (trades.json)|
                   |              +--------------+
                   v
              +----+------+
              | DataAdapter|
              +-----------+
```

- **DataAdapter** is the bottom of the stack. Everything else asks it for
  candles. Swap implementations to change exchanges.
- **Detectors** are pure functions over candle lists. No state, no I/O.
- **Scanner** is your code. It composes detectors into gates and produces a
  `SetupResult`.
- **PaperTrader** owns position state and the JSON journal.
- **Filters** sit between the scanner and the trader. They reject `TAKE`
  setups that look like duplicates or repeats of recently-blown levels.
- **run_monitor** is the loop that ties it all together and renders the
  dashboard. Optionally consults an **Agent** (Claude) before executing.

Each layer depends only on the ones below it, so you can use any piece in
isolation: a scanner without a trader (just to log signals), a paper trader
without the monitor (drive it from a notebook), a backtest runner that swaps
the live loop for a historical walk.

## The data model

There are three core types you'll see everywhere:

```python
# A single OHLC candle. TypedDict — just a dict at runtime.
Candle = {"timestamp": int_ms, "open": float, "high": float,
          "low": float, "close": float, "volume": float}

# What a scanner produces.
@dataclass
class SetupResult:
    symbol: str
    status: SetupStatus = NO_SETUP   # TAKE / WAIT / SKIP / NO_SETUP
    direction: str | None = None     # "long" or "short"
    reason: str = ""                 # human-readable why
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    gates_passed: list[str] = []
    extras: dict = {}                # anything else you want to log
    timestamp: str = <iso8601>

# What the paper trader records.
@dataclass
class Trade:
    id: str; symbol: str; direction: str
    entry_time: str; entry: float; stop: float; target: float
    size: float; risk: float
    exit_time: str | None; exit: float | None; pnl: float | None
    r_multiple: float | None
    reason: str   # "TP hit" / "SL hit" / "manual"
    extras: dict
```

The four `SetupStatus` values mean:

- **`NO_SETUP`** — no candidate; default. Don't render in the dashboard.
- **`SKIP`** — actively rejected (a gate failed). Render with the reason.
- **`WAIT`** — setup is forming but not actionable yet. Render with what
  you're waiting for.
- **`TAKE`** — execute now. `entry`, `stop`, `target`, `direction` must all
  be set.

Only `TAKE` results reach the paper trader. The others are for the dashboard
and your debugging.

## The scan-and-execute loop

Once per `scan_interval` seconds, `run_monitor` does this:

```
1. paper_trader.check_exits()              # close any TP/SL hits using 1m candles
2. results = scanner.scan_all()            # call evaluate(symbol) for each symbol
3. render_dashboard(results, journal)
4. for r in results where r.status == TAKE:
       if open_trade_on(r.symbol):     skip
       if is_duplicate_setup(r):       skip   # same entry/sl/tp recently
       if is_invalidated_level(r):     skip   # similar setup just got stopped
       if agent and agent.veto(r):     skip   # optional Claude veto
       paper_trader.open_trade(r)
5. sleep(scan_interval or fast_interval if a trade is open)
```

The two filters (`is_duplicate_setup`, `is_invalidated_level`) live in
`model_trader.paper_trader.filters` and exist because of two failure modes that
showed up empirically: scanners that re-trigger on the same bar produce
duplicate trades; scanners that re-trigger after getting stopped at a level
will keep blowing up on that same level until the level structurally
invalidates.

## Backtesting

The backtest runner replaces step 2-5 of the loop with a historical walk:

```
fetch full history once per symbol
for ts in step every N minutes:
    for symbol in symbols:
        hist = candles_truncated_at(ts)
        result = scanner.evaluate_at(symbol, hist, corr_hist, ts)
        if result.status == TAKE: open paper trade
        check open trades against next candles
```

Your scanner needs to implement `evaluate_at()` (mirror of `evaluate()` but
reading from passed-in history instead of calling the data adapter). See
[`backtest.md`](backtest.md).

## Where state lives

- **`traders/<name>/trades.json`** — paper trader journal. The source of truth
  for everything that's been executed.
- **`traders/<name>/agent_journal.json`** — agent decisions, when the agent
  layer is enabled.
- **`traders/<name>/transcripts/`** — input to the extraction pipeline.
- Everything else is recomputed per scan. There is no in-memory cache that
  would be lost on restart.

`traders/` is gitignored. Trader projects are local to your machine.

## What the framework does NOT do

- **Order routing.** This is a paper trader. To go live with real money you'd
  write a `LiveTrader` class that parallels `PaperTrader` and calls a real
  exchange API. None of the existing code is in your way, but none of it
  helps either.
- **Backtest data caching.** Each backtest fetches fresh history from the
  data adapter. For Hyperliquid this is fine (free, fast); for other adapters
  you may want to add a disk cache.
- **Risk management beyond per-trade sizing.** No daily loss limits, no
  max-drawdown halt. Add these in your `main.py` if you need them.
- **Multi-account.** One process, one journal.
