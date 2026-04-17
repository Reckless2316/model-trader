# The Pipeline

End-to-end: from a trader's recorded thinking to a paper-trading bot that takes
their setups. This is the document to read first.

## The five stages

```
1. INGEST       Fetch transcripts/articles/tweets from the trader.
2. EXTRACT      Use Claude to distill a structured strategy document.
3. SCAFFOLD     Generate a fresh traders/<name>/ project.
4. IMPLEMENT    Translate the strategy into a sequence of gates.
5. VALIDATE     Backtest, then run live (paper) and watch.
```

Stages 1-3 are one-shot CLIs in `pipeline/`. Stage 4 is where you (or an agent)
actually write code. Stage 5 is the runtime in `model_trader/`.

---

## 1. Ingest

The framework ships with a YouTube transcript fetcher because that's where most
trader content lives. For other sources (tweets, Substack, blog posts), drop
plain `.txt` files into `traders/<name>/transcripts/` directly — the next stage
just reads every `.txt` it finds.

```bash
python -m pipeline.fetch_youtube_transcripts traders/my_trader/transcripts \
    VIDEO_ID_1 VIDEO_ID_2 VIDEO_ID_3
```

Pick 3-10 videos that are representative of the trader's style. More is not
always better — if half the videos are off-topic interviews, the extraction
step will produce a muddier strategy doc.

The fetcher uses `yt-dlp` to pull auto-generated captions, strips the VTT
formatting, deduplicates the timing-repeats, and writes one clean `.txt` per
video.

## 2. Extract

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m pipeline.extract_strategy traders/my_trader/transcripts traders/my_trader
```

This runs Claude Opus 4.6 in two passes against the full transcript corpus:

- **Pass 1 -> `strategy.md`** — a structured breakdown: core identity, ranked
  priorities, every distinct setup, key concepts, a draft list of gates,
  anti-patterns, risk management, and characteristic vocabulary. This is your
  reference document while implementing the scanner.

- **Pass 2 -> `philosophy_draft.md`** — a 2-4k word document written in the
  trader's voice, structured as a system prompt for the optional agent layer.
  You'll edit this by hand before using it.

**Read both documents before writing any code.** If the strategy doc is vague
in places (it usually is — traders contradict themselves, or leave the most
important parts unsaid), that vagueness is going to show up as ambiguity in
your gate definitions. Better to notice it now and resolve it deliberately
than to discover it three days into a backtest.

## 3. Scaffold

```bash
python -m pipeline.scaffold_trader my_trader
```

Creates `traders/my_trader/` with:

- `scanner.py` — a `Scanner(ScannerBase)` skeleton with TODO gate slots
- `config.yaml` — symbols, timeframes, correlations, paper trading settings
- `main.py` — entry point that wires the scanner into the live monitor
- `backtest.py` — entry point that runs the scanner against historical data
- `philosophy.md` — copy of the agent template (only used if `agent_enabled: true`)
- `transcripts/` — empty, ready for stage 1

If you ran stage 1 first, the transcripts directory will already have content;
the scaffold step will not overwrite it. (In fact the scaffold step refuses to
run if `traders/<name>/` already exists, to avoid clobbering work.)

## 4. Implement

This is the only stage that can't be automated. You read `strategy.md`, you
identify the sequence of conditions that must all be true for the trader to
enter, and you encode each one as a gate that fails fast.

The full guide is in [`designing-gates.md`](designing-gates.md). The TL;DR:

- **One gate per pass/fail check.** If a single function evaluates two
  independent conditions, split it.
- **Order gates by selectivity.** Cheap, high-rejection checks first. You want
  the median symbol-scan to fail at gate 1.
- **Each gate has a single responsibility and a clear `result.reason`** when
  it fails. The reason string is what shows up in the live dashboard and the
  trade journal — you will read it thousands of times.
- **The last gate sets entry / stop / target / direction** and flips the
  status to `SetupStatus.TAKE`. Until then the result is `NO_SETUP`.

The detectors in `model_trader.detectors` cover the common ICT-style patterns
(FVG, swings, failure swings, CISD, SMT divergence, displacement). Most gates
are 5-15 lines: call a detector, check the result, append to `gates_passed` or
set `result.reason` and return.

## 5. Validate

### Backtest first

```bash
cd traders/my_trader
python backtest.py
```

This requires you to have implemented `evaluate_at()` in addition to
`evaluate()` — see [`backtest.md`](backtest.md). The runner walks chronologically
through the last N days of data and calls your scanner with progressively
larger slices of history.

Look at:

- **Trade count** — too few (under ~1/day across your symbols) and you can't
  draw conclusions; too many (>10/day) and you're probably letting noise
  through
- **Win rate and average R** — neither alone is meaningful; together they tell
  you whether the strategy is positive expectancy
- **Per-symbol breakdown** — if 90% of profit comes from one symbol, your
  gates are probably overfit to that symbol's character

If the backtest looks broken, do not ship it. Tighten or loosen one gate at a
time and re-run. Don't make 5 changes at once or you won't know which one
mattered.

### Then go live (paper)

```bash
python main.py
```

The live monitor will:

1. Check open trades against current 1m candles (SL/TP)
2. Scan all configured symbols
3. Print a dashboard
4. For each `TAKE` setup: skip if already open on this symbol, skip if
   duplicate of a recent trade, skip if a structurally-similar setup just
   got stopped out, optionally consult the agent, then execute
5. Sleep `scan_interval` seconds (faster when a trade is open, to catch exits)

All trades land in `trades.json` in the trader's directory. That file is the
ground truth — `traders/<name>/trades.json` is gitignored, so it's local to
your machine.

Run it overnight. Look at the journal in the morning. Iterate.

---

## What success looks like

A working trader project, after a few rounds of iteration, ends up with:

- A `scanner.py` of maybe 100-300 lines: 3-8 gates, each tightly scoped
- A `strategy.md` you've annotated with notes on which rules turned out to
  matter and which were just vibes
- A `trades.json` with enough samples (50+) to actually evaluate
- An optional `philosophy.md` that the agent uses to veto setups your gates
  would otherwise take

You don't need the agent layer to ship. Most of the edge is in the gates.
