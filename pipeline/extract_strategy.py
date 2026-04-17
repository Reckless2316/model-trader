"""Use Claude to analyze transcripts and extract a structured strategy summary.

This is a one-shot extraction — not part of the live trading loop. Run it once
per trader to get a strategy document you can use as the basis for your
scanner's gate logic and the agent's philosophy document.

Usage:
    python -m pipeline.extract_strategy <transcripts_dir> <output_dir>

Writes:
    <output_dir>/strategy.md        - structured strategy breakdown
    <output_dir>/philosophy_draft.md - first draft of agent philosophy

Requires: pip install anthropic (and ANTHROPIC_API_KEY env var)
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("This script requires the anthropic package. Run: pip install anthropic")
    sys.exit(1)


MODEL = "claude-opus-4-6"


STRATEGY_PROMPT = """You are analyzing a trader's content (video transcripts) to extract their
complete trading strategy. Your job is to produce a structured strategy
document that someone could use to build an algorithmic screener.

Read all the transcripts below, then produce a markdown document with these
sections:

## Core Identity
Who is this trader? What's their background, experience, edge?

## Ranked Priorities
List the trader's priorities in order of emphasis. What do they talk about
most? What do they consider non-negotiable vs. nice-to-have?

## The Setup(s)
Describe every distinct setup they trade. For each:
- What triggers it?
- What timeframes are involved?
- What are the exact entry/stop/TP rules?
- When does it NOT apply?

## Key Concepts
Every term they use that would need to be understood to implement this
algorithmically. Define each one (FVG, CISD, failure swing, draw on
liquidity, etc.) with their specific definition, not the generic one.

## Gates (for an algorithmic screener)
Map their strategy to a sequence of pass/fail gates. Format:

Gate 1: [name]
  - What to check: [specific condition]
  - Pass if: [...]
  - Fail if: [...]
Gate 2: ...

## What They DO NOT Do
Explicit anti-patterns. Things they warn against or avoid.

## Risk Management
Position sizing, stop placement philosophy, max risk per trade, daily loss
limits, etc. Quote them if possible.

## Unique Vocabulary / Voice
How do they talk? What phrases are characteristic? This helps build the
"persona" for the agent layer.

Be thorough. Quote directly when it captures something important. If the
transcripts contradict each other, note the contradiction and which version
seems more recent / considered.
"""


PHILOSOPHY_PROMPT = """Based on the strategy document you just produced, now write a concise
philosophy document (2,000-4,000 words) in the trader's voice. This will be
used as a system prompt for an AI agent that reviews trade setups.

Structure it following this template:

# [Trader name] - Trader Identity & Philosophy

## Who I am
[First-person paragraph capturing background and edge]

## Core philosophy
[5-10 bulleted principles, with direct quotes where possible]

## The setup(s) I trade
[Detailed description of every setup]

## How I identify [their key concept]
[The one thing they emphasize most, and their specific approach to it]

## Entry mechanics
[Exact sequence of events]

## Stop loss
[Invalidation-based rules]

## Take profit
[Default + when to hold/exit early]

## The "am I actually taking this?" checklist
[5-10 questions, in their voice]

## Anti-patterns - what I DO NOT do
[Explicit list]

## Psychology / mindset
[How they stay profitable emotionally]

## My voice
[How they talk about setups, with example phrases]

Write in FIRST PERSON as the trader. Be direct, specific. Capture their
actual voice and phrasing. End with the TAKE/SKIP/WAIT decision framework.
"""


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m pipeline.extract_strategy <transcripts_dir> <output_dir>")
        sys.exit(1)

    transcripts_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load all .txt transcripts
    txt_files = sorted(transcripts_dir.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files found in {transcripts_dir}")
        sys.exit(1)

    print(f"Loading {len(txt_files)} transcripts...")
    transcripts = []
    for f in txt_files:
        transcripts.append(f"=== {f.stem} ===\n{f.read_text(encoding='utf-8')}")
    corpus = "\n\n".join(transcripts)
    print(f"Total: {len(corpus):,} chars\n")

    client = anthropic.Anthropic()

    # --- Pass 1: Strategy extraction ---
    print("Pass 1: extracting strategy structure...")
    strategy_response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{
            "role": "user",
            "content": f"{STRATEGY_PROMPT}\n\n## Transcripts\n\n{corpus}",
        }],
    )
    strategy_text = next(
        (b.text for b in strategy_response.content if getattr(b, "type", None) == "text"),
        "",
    )

    strategy_path = output_dir / "strategy.md"
    strategy_path.write_text(strategy_text, encoding="utf-8")
    print(f"  -> {strategy_path} ({len(strategy_text):,} chars)")

    # --- Pass 2: Philosophy document for agent ---
    print("\nPass 2: generating agent philosophy...")
    philosophy_response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[
            {
                "role": "user",
                "content": f"{STRATEGY_PROMPT}\n\n## Transcripts\n\n{corpus}",
            },
            {"role": "assistant", "content": strategy_text},
            {"role": "user", "content": PHILOSOPHY_PROMPT},
        ],
    )
    philosophy_text = next(
        (b.text for b in philosophy_response.content if getattr(b, "type", None) == "text"),
        "",
    )

    philosophy_path = output_dir / "philosophy_draft.md"
    philosophy_path.write_text(philosophy_text, encoding="utf-8")
    print(f"  -> {philosophy_path} ({len(philosophy_text):,} chars)")

    print("\nDone. Review both docs and refine as needed before using.")


if __name__ == "__main__":
    main()
