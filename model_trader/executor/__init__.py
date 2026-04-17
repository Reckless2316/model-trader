"""Live execution engines.

Implementations that place real orders on real exchanges. Import the one
you need — the top-level `__init__` does not import them eagerly so that
`model_trader` itself has no hard dependency on exchange SDKs.
"""

__all__ = ["HyperliquidExecutor"]


def __getattr__(name):
    if name == "HyperliquidExecutor":
        from .hyperliquid import HyperliquidExecutor
        return HyperliquidExecutor
    raise AttributeError(name)
