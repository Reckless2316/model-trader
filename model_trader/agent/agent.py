"""Claude-based discretion layer.

Pass a philosophy markdown file describing the trader's identity, rules, and
voice. The agent uses that as its system prompt and reviews each TAKE signal
from the scanner, returning TAKE/SKIP/WAIT with reasoning.

Fail-open: if the API call errors or no key is set, defaults to TAKE (defers
to the gate decision). This means the bot keeps working even if Claude is
unavailable — the agent is purely an optional enhancement.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import anthropic
except ImportError:  # optional dependency
    anthropic = None


DEFAULT_MODEL = "claude-opus-4-6"


class TraderAgent:
    """Wraps a Claude API call with the trader's philosophy as system prompt.

    Args:
        philosophy_path: Path to the markdown document describing this trader.
        journal_path: Where to log agent decisions (JSON).
        model: Claude model ID. Default: claude-opus-4-6.
    """

    def __init__(
        self,
        philosophy_path: str | Path,
        journal_path: str | Path,
        model: str = DEFAULT_MODEL,
    ):
        if anthropic is None:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        self.philosophy_path = Path(philosophy_path)
        self.journal_path = Path(journal_path)
        self.model = model
        self._client: anthropic.Anthropic | None = None
        self._system_prompt: str | None = None

    def is_available(self) -> bool:
        """True if an API key is configured."""
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def _get_client(self) -> "anthropic.Anthropic":
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _load_philosophy(self) -> str:
        if self._system_prompt is not None:
            return self._system_prompt

        if not self.philosophy_path.exists():
            raise FileNotFoundError(
                f"Philosophy file not found: {self.philosophy_path}\n"
                "Copy model_trader/agent/philosophy_template.md and fill it in."
            )

        philosophy = self.philosophy_path.read_text(encoding="utf-8")

        self._system_prompt = f"""You are embodying the identity and philosophy below. You are reviewing a
trading setup that has already passed a mechanical gate system. Your job is to
apply the discretion that rules alone can't capture - would you actually take
this trade?

{philosophy}

---

## Your current task

You will receive a setup summary + recent trading context. Decide:

- **TAKE** - Dumb obvious, matches how you trade. Execute.
- **SKIP** - Something feels off, forced, or iffy. Pass.
- **WAIT** - You'd want more confirmation before pulling the trigger.

Respond in your voice - direct, specific, no hedging. 2-3 sentences maximum.
Reference what you actually see in the setup (the draw, the structure, the
level history). Don't speak in abstractions.

Output as JSON:
{{
  "decision": "TAKE" | "SKIP" | "WAIT",
  "confidence": "dumb_obvious" | "decent" | "iffy",
  "reasoning": "your 2-3 sentence take"
}}
"""
        return self._system_prompt

    def _format_setup(self, setup) -> str:
        """Summarize a SetupResult for the agent."""
        # Accept either a SetupResult object or a dict
        if hasattr(setup, "to_dict"):
            s = setup.to_dict()
        else:
            s = setup

        lines = [
            f"Symbol: {s['symbol']}",
            f"Direction: {s['direction']}",
            f"Entry: {s.get('entry')}",
            f"Stop: {s.get('stop')}",
            f"Target: {s.get('target')}",
        ]
        if s.get("entry") and s.get("stop"):
            stop_dist = abs(s["entry"] - s["stop"])
            lines.append(f"Stop distance: {stop_dist:.4f} ({stop_dist / s['entry'] * 100:.3f}%)")
        lines.append(f"Gates passed: {', '.join(s.get('gates_passed', []))}")
        for k, v in s.get("extras", {}).items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    def _format_recent_trades(self, trades: list[dict], limit: int = 10) -> str:
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        recent = sorted(closed, key=lambda t: t.get("entry_time", ""))[-limit:]
        if not recent:
            return "No prior closed trades."

        wins = sum(1 for t in recent if t.get("outcome") == "WIN")
        losses = sum(1 for t in recent if t.get("outcome") == "LOSS")
        lines = [f"Last {len(recent)} trades: {wins}W / {losses}L"]
        for t in recent[-5:]:
            lines.append(
                f"  {t.get('entry_time', '?')[:16]} "
                f"{t['symbol']} {t['direction']} -> {t.get('outcome', '?')}"
            )
        return "\n".join(lines)

    def evaluate(self, setup, recent_trades: list[dict]) -> dict:
        """Ask the agent whether to take this setup. Fail-open on errors."""
        try:
            client = self._get_client()
            system = self._load_philosophy()
        except Exception as e:
            return {
                "decision": "TAKE",
                "confidence": "decent",
                "reasoning": f"Agent unavailable: {e}",
            }

        user_content = (
            f"The gate system flagged this setup as TAKE. Review it.\n\n"
            f"## Setup\n{self._format_setup(setup)}\n\n"
            f"## Recent context\n{self._format_recent_trades(recent_trades)}\n\n"
            f"Would you take it?"
        )

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as e:
            return {
                "decision": "TAKE",
                "confidence": "decent",
                "reasoning": f"Agent error: {e}",
            }

        # Extract text (may include thinking blocks)
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text = block.text
                break

        # Parse JSON from response
        decision = self._parse_decision(text)
        self._log_decision(setup, decision)
        return decision

    def _parse_decision(self, text: str) -> dict:
        """Extract JSON from the response, fall back to heuristic parse."""
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if parsed.get("decision") in ("TAKE", "SKIP", "WAIT"):
                    return {
                        "decision": parsed["decision"],
                        "confidence": parsed.get("confidence", "decent"),
                        "reasoning": parsed.get("reasoning", "")[:500],
                    }
        except Exception:
            pass

        # Heuristic fallback
        upper = text.upper()[:200]
        if "SKIP" in upper:
            dec = "SKIP"
        elif "WAIT" in upper:
            dec = "WAIT"
        else:
            dec = "TAKE"
        return {
            "decision": dec,
            "confidence": "decent",
            "reasoning": text[:300] or "No response text",
        }

    def _log_decision(self, setup, decision: dict) -> None:
        if hasattr(setup, "to_dict"):
            s = setup.to_dict()
        else:
            s = setup

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": s["symbol"],
            "direction": s.get("direction"),
            "entry": s.get("entry"),
            "stop": s.get("stop"),
            "target": s.get("target"),
            "gates_passed": s.get("gates_passed", []),
            "decision": decision["decision"],
            "confidence": decision["confidence"],
            "reasoning": decision["reasoning"],
        }

        journal: list[dict] = []
        if self.journal_path.exists():
            try:
                with open(self.journal_path, encoding="utf-8") as f:
                    journal = json.load(f)
            except Exception:
                journal = []

        journal.append(entry)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_path, "w", encoding="utf-8") as f:
            json.dump(journal, f, indent=2, default=str)
