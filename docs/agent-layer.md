# The Agent Layer

The optional Claude-powered discretion step that sits between your gates and
the paper trader. The agent's job is to apply the judgment that pass/fail
rules can't capture — to look at a setup the gates already approved and ask
"would I actually take this?"

It is veto-only and fail-open. If the API errors, the key is missing, or the
philosophy file is missing, the bot keeps trading on gate decisions alone.

## When to use it

- **Use it** when your trader's edge depends heavily on context that's hard
  to formalize: "I don't take this setup right after a major news event,"
  "I avoid these patterns when the broader market is choppy," "I size up
  when I see X confluence."
- **Don't use it** to compensate for weak gates. If the agent is rejecting
  60% of your scanner's setups, the scanner is the problem.
- **Don't use it as the strategy.** Asking Claude "should I trade BTC right
  now?" with no gate filtering produces noise. The agent works because the
  gates have already done 95% of the filtering.

A reasonable mental model: the gates are the analyst, the agent is the PM.

## How it works

```
scanner -> TAKE -> filters -> [agent.evaluate(setup, recent_trades)] -> trade
                                          |
                                          v
                                   {decision: TAKE/SKIP/WAIT,
                                    confidence: ...,
                                    reasoning: "..."}
```

`agent.evaluate()` sends the setup details + recent trade history to Claude
with the philosophy document as the system prompt. It returns one of three
decisions:

- **TAKE** — proceed to execution
- **SKIP** — don't take this one
- **WAIT** — defer (the live monitor treats this as skip; it's the same
  outcome but with different reasoning)

The decision and reasoning are logged to `agent_journal.json` so you can
audit later.

## The philosophy document

`philosophy.md` is the system prompt. Its quality is the entire ballgame.

The scaffold gives you a template at `traders/<name>/philosophy.md` (copied
from `model_trader/agent/philosophy_template.md`). The structure is:

```
# [Trader name] - Trader Identity & Philosophy

## Who I am
First-person background and what gives them edge.

## Core philosophy
5-10 bulleted principles, with direct quotes where possible.

## The setup(s) I trade
Detailed description of every distinct setup.

## How I identify [their key concept]
The one thing they emphasize most.

## Entry / Stop loss / Take profit
Mechanical rules.

## The "am I actually taking this?" checklist
5-10 questions the agent should ask itself.

## Anti-patterns - what I DO NOT do
Explicit list.

## Psychology / mindset
How they stay profitable emotionally.

## My voice
How they talk. Example phrases.
```

The `pipeline.extract_strategy` CLI generates a first draft (`philosophy_draft.md`)
in this shape. **Always edit it by hand** before using — Claude's draft will be
serviceable but generic. The parts that need your edits:

- Strip out generic platitudes ("manage risk", "be patient")
- Add the specific phrases the trader actually uses
- Sharpen the anti-patterns into things you'd actually catch
- The checklist questions are the most important — make them specific to
  the trader's actual decision points

Once edited, save it as `philosophy.md` (overwriting the template). Set
`agent_enabled: true` in `config.yaml` and run.

## Cost

Each agent call is a single Claude Opus 4.6 request with adaptive thinking
and `effort: low`. The philosophy document is sent with `cache_control` so
subsequent calls hit the prompt cache. Typical cost per call: a few cents.

If your scanner produces 5-20 `TAKE` setups per day, you're looking at well
under a dollar per day. If it produces 200, your gates need work.

## Tuning the agent

If the agent rejects too much, look at `agent_journal.json` — the
`reasoning` field tells you which clause of the philosophy is firing. You
have a few levers:

- Soften the language in the philosophy ("I'm cautious about X" vs "I never
  take X")
- Remove anti-patterns that the trader didn't actually mean as absolutes
- Move marginal calls into the gate layer (where you have full control)
  rather than relying on the agent to catch them

If the agent rubber-stamps everything, the philosophy is too vague. Add
specific checklist questions and concrete anti-patterns.

## Failure modes

- **API key missing.** Agent returns TAKE with reasoning "Agent unavailable".
  Bot keeps trading on gate decisions.
- **Network/API error.** Same: TAKE with the error message in reasoning.
- **Malformed JSON in response.** The agent code falls back to a heuristic
  parse (look for SKIP/WAIT/TAKE substrings). Decisions are still logged.
- **Philosophy file missing.** Same fail-open behavior. The error shows up
  in `reasoning`.

The principle: an outage in the agent layer should never block trading.
The gates are the safety-critical part. The agent is decoration.
