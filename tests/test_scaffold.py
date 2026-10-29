"""Scaffold generator writes importable, well-formed templates."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class ScaffoldTests(unittest.TestCase):
    def test_scaffold_creates_valid_project(self):
        with tempfile.TemporaryDirectory() as td:
            env = {**os.environ, "PYTHONPATH": str(ROOT)}
            (Path(td) / "model_trader/agent").mkdir(parents=True)
            (Path(td) / "model_trader/agent/philosophy_template.md").write_text("# philosophy\n")
            out = subprocess.run([sys.executable, "-m", "pipeline.scaffold_trader", "demo"], cwd=td, env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            project = Path(td) / "traders/demo"
            for name in ("scanner.py", "main.py", "backtest.py"):
                ast.parse((project / name).read_text(), name)
            config = yaml.safe_load((project / "config.yaml").read_text())
            self.assertTrue(config["paper_trading"])
            self.assertEqual((project / "philosophy.md").read_text(), "# philosophy\n")
            again = subprocess.run([sys.executable, "-m", "pipeline.scaffold_trader", "demo"], cwd=td, env=env, capture_output=True, text=True)
            self.assertEqual(again.returncode, 1)


if __name__ == "__main__":
    unittest.main()
