# model-trader

Turn a trader's content into an executable screener and paper trader.

A framework for building algorithmic trading bots from the recorded thinking of
real traders. You feed in the trader's transcripts (YouTube videos, articles,
tweets), distill their strategy into a set of pass/fail gates, and run the
result as a live screener that paper trades on Hyperliquid. Optionally, layer
an LLM "agent" on top that reviews each setup against a philosophy document
written in the trader's voice.

```
content  ->  strategy doc  ->  scanner (gates)  ->  paper trader
                          \->  philosophy doc  ->  agent (optional veto)
```

## Why this exists

Most trading is judgment, not rules. But the *structure* of a trader's
judgment — which patterns they look for, what invalidates a setup, when they
sit on their hands — can usually be expressed as a short pipeline of pass/fail
checks. This repo is a scaffold for doing that translation: from someone's
recorded thinking into code that takes the same setups they would, on the same
symbols, with the same risk model.

It is not a strategy. It is the harness around one.

## What's in the box

- **`model_trader/`** — the framework
  - `data/` — `DataAdapter` ABC + `HyperliquidAdapter` (works with no API key)
  - `detectors/` — reusable pattern detectors (FVG, swings, CISD, SMT, displacement, failure swings)
  - `gates/` — `ScannerBase` and the `SetupResult` / `SetupStatus` types
  - `paper_trader/` — JSON-journaled paper trader with leverage cap, duplicate
    filter, structural invalidated-level filter, and metrics
  - `monitor/` — live monitor loop (scan -> filter -> execute -> dashboard)
  - `backtest/` — historical runner that walks a scanner through past candles
  - `agent/` — optional Claude-powered discretion layer + philosophy template

- **`pipeline/`** — one-shot CLIs you run before going live
  - `fetch_youtube_transcripts.py` — pull captions from YouTube videos
  - `extract_strategy.py` — use Claude to distill transcripts into a strategy doc + agent philosophy draft
  - `scaffold_trader.py` — generate a new `traders/<name>/` project from templates

- **`docs/`** — the manual (start with [docs/pipeline.md](docs/pipeline.md))

- **`traders/`** — gitignored. Your trader projects live here.

## Quickstart

```bash
git clone <this-repo> model-trader
cd model-trader
pip install -r requirements.txt

# 1. Scaffold a new trader project
python -m pipeline.scaffold_trader my_trader

# 2. Pull transcripts from a few of their videos
python -m pipeline.fetch_youtube_transcripts traders/my_trader/transcripts VIDEO_ID_1 VIDEO_ID_2

# 3. Use Claude to extract a strategy doc + philosophy draft
export ANTHROPIC_API_KEY=sk-ant-...
python -m pipeline.extract_strategy traders/my_trader/transcripts traders/my_trader

# 4. Read traders/my_trader/strategy.md, then implement the gates in
#    traders/my_trader/scanner.py — see docs/designing-gates.md

# 5. Run the live monitor
cd traders/my_trader
python main.py
```

Paper trading is on by default. No real money is at risk unless you write code
to put it there.

## Reading order

If you're a human (or an agent) trying to use this repo from cold:

1. [`docs/pipeline.md`](docs/pipeline.md) — the end-to-end flow
2. [`docs/architecture.md`](docs/architecture.md) — how the pieces fit together
3. [`docs/designing-gates.md`](docs/designing-gates.md) — the hard part: turning prose into pass/fail checks
4. [`docs/backtest.md`](docs/backtest.md) — how to validate your gates against history
5. [`docs/agent-layer.md`](docs/agent-layer.md) — when and how to use the optional LLM layer
6. [`docs/adding-data-sources.md`](docs/adding-data-sources.md) — swapping Hyperliquid for something else

## Requirements

- Python 3.11+
- `requests`, `pyyaml` (always)
- `yt-dlp` (for the transcript pipeline)
- `anthropic` + `ANTHROPIC_API_KEY` (for `extract_strategy.py` and the optional agent)

## License

MIT. See `LICENSE`.
