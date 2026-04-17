"""Gate framework.

A "scanner" evaluates a symbol through a sequence of pass/fail gates and
produces a SetupResult with status TAKE / SKIP / WAIT / NO_SETUP.

Subclass ScannerBase and implement evaluate() to define a trader's strategy.
"""

from .base import ScannerBase, SetupResult, SetupStatus

__all__ = ["ScannerBase", "SetupResult", "SetupStatus"]
