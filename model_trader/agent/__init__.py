"""Optional AI agent layer — adds a discretion filter on top of mechanical gates.

The agent takes a philosophy markdown doc (describing how a specific trader
thinks) and uses Claude to review TAKE signals before execution. It can veto
trades that pass the gates but don't match the trader's actual style.

See `philosophy_template.md` for the structure of the document you need to
supply. The pipeline script `extract_strategy.py` can help generate one from
transcripts.
"""

from .agent import TraderAgent

__all__ = ["TraderAgent"]
