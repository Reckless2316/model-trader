"""Hyperliquid live executor.

Places real limit orders with exchange-side SL and TP trigger orders so
exits fire even if the bot is offline. Targets testnet by default. Takes
an API wallet private key — never use your main wallet's key here.

The executor is stateful against a JSON journal that mirrors PaperTrader's
format plus exchange-specific fields (entry_oid, sl_oid, tp_oid, fill_time).
Call `check_exits()` periodically to reconcile the journal against
`info.user_state()` and `info.user_fills()`.

Usage:
    from model_trader.executor import HyperliquidExecutor

    ex = HyperliquidExecutor(
        journal_path="trades.json",
        wallet_address="0x...",
        api_private_key="0x...",   # from env var, not hardcoded
        testnet=True,
    )
    ex.execute({"status": "TAKE", "symbol": "BTC", "direction": "long",
                "entry": 60000, "stop": 59500, "target": 61000})
    ex.check_exits()
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HyperliquidExecutor:
    """Places limit entries + exchange-side SL/TP triggers on Hyperliquid.

    Args:
        journal_path: Where to persist trades as JSON.
        wallet_address: Main wallet address (holds positions and margin).
        api_private_key: API wallet private key — signs orders. Generate
            at https://app.hyperliquid-testnet.xyz/API (or mainnet) with
            trade permission only. Do NOT use your main wallet's key.
        testnet: Route to Hyperliquid's testnet API.
        per_trade_pct: Risk per trade as % of account value (default 1.0).
        max_leverage: Cap position size so notional <= balance * this.
    """

    def __init__(
        self,
        journal_path: str | Path,
        wallet_address: str,
        api_private_key: str,
        testnet: bool = True,
        per_trade_pct: float = 1.0,
        max_leverage: float = 25.0,
    ):
        from hyperliquid.info import Info
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
        from eth_account import Account

        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        # Empty spot_meta skips the SDK's eager spot bootstrapping (broken
        # on testnet). Discover builder-deployed perp dexes and register
        # them all so colon-prefixed symbols like "xyz:GOLD" resolve.
        empty_spot = {"universe": [], "tokens": []}
        probe = Info(base_url, skip_ws=True, spot_meta=empty_spot)
        dex_names = [""] + [d["name"] for d in probe.perp_dexs() if d]

        self.info = Info(base_url, skip_ws=True, spot_meta=empty_spot, perp_dexs=dex_names)
        account = Account.from_key(api_private_key)
        self.exchange = Exchange(
            account, base_url, account_address=wallet_address,
            spot_meta=empty_spot, perp_dexs=dex_names,
        )

        self.journal_path = Path(journal_path)
        self.wallet_address = wallet_address
        self.testnet = testnet
        self.per_trade_pct = per_trade_pct
        self.max_leverage = max_leverage
        self.dex_names = dex_names

    # ---------- Persistence ----------

    def _load(self) -> list[dict]:
        if self.journal_path.exists():
            with open(self.journal_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self, trades: list[dict]) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_path, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2, default=str)

    def get_open_trades(self) -> list[dict]:
        return [t for t in self._load() if t.get("status") in ("OPEN", "PENDING")]

    def get_all_trades(self) -> list[dict]:
        return self._load()

    def get_balance(self, coin: str | None = None) -> float:
        """Margin available for trading.

        Hyperliquid holds margin per perp dex. A trade on 'xyz:GOLD' draws
        from the 'xyz' dex account, not the default perp account. Pass the
        coin (or the dex name directly) so the right account is queried.
        Omit both for the default dex.
        """
        dex = self._dex_for_coin(coin) if coin else ""
        try:
            state = self.info.user_state(self.wallet_address, dex=dex) if dex \
                else self.info.user_state(self.wallet_address)
        except TypeError:
            # SDK without dex kwarg — hit the raw endpoint
            import requests
            payload = {"type": "clearinghouseState", "user": self.wallet_address}
            if dex:
                payload["dex"] = dex
            state = requests.post(self.info.base_url + "/info", json=payload).json()
        return float(state.get("marginSummary", {}).get("accountValue", 0) or 0)

    @staticmethod
    def _dex_for_coin(coin: str) -> str:
        """Return the perp dex name for a coin. Builder perps are prefixed
        like 'xyz:GOLD'; the default dex is ''."""
        if ":" in coin:
            return coin.split(":", 1)[0]
        return ""

    # ---------- Rounding ----------

    def _sz_decimals(self, coin: str) -> int:
        asset = self.info.coin_to_asset.get(coin)
        if asset is None:
            raise ValueError(
                f"Asset '{coin}' not listed on Hyperliquid "
                f"({'testnet' if self.testnet else 'mainnet'})"
            )
        return int(self.info.asset_to_sz_decimals[asset])

    def _round_size(self, coin: str, size: float) -> float:
        decimals = self._sz_decimals(coin)
        factor = 10 ** decimals
        return math.floor(size * factor) / factor

    def _round_price(self, coin: str, price: float) -> float:
        # Hyperliquid perp price rules: max 5 significant figures,
        # max (6 - szDecimals) decimal places.
        if price == 0:
            return 0.0
        decimals = self._sz_decimals(coin)
        max_decimals = max(0, 6 - decimals)
        exp = math.floor(math.log10(abs(price)))
        sig_decimals = 4 - exp
        dec = min(max_decimals, max(0, sig_decimals))
        return round(price, dec)

    # ---------- Entry ----------

    def execute(self, setup: dict) -> dict | None:
        """Open a trade from a TAKE setup dict. Returns the journal entry or None.

        Expected keys: status, symbol, direction, entry, stop, target.
        Any other keys are preserved in `extras`.
        """
        if setup.get("status") != "TAKE":
            return None

        entry = setup.get("entry")
        stop = setup.get("stop")
        target = setup.get("target")
        direction = setup.get("direction")
        coin = setup.get("symbol")

        if entry is None or stop is None or target is None or not direction or not coin:
            return None

        stop_dist = abs(entry - stop)
        if stop_dist == 0:
            return None

        balance = self.get_balance(coin)
        if balance <= 0:
            raise RuntimeError(
                f"No margin in the '{self._dex_for_coin(coin) or 'default'}' "
                f"dex account. Transfer USDC into it before trading {coin}."
            )
        risk = balance * (self.per_trade_pct / 100)
        size = risk / stop_dist

        notional = size * entry
        max_notional = balance * self.max_leverage
        if notional > max_notional:
            size = max_notional / entry
            risk = size * stop_dist

        size = self._round_size(coin, size)
        if size <= 0:
            return None

        entry_px = self._round_price(coin, entry)
        sl_px = self._round_price(coin, stop)
        tp_px = self._round_price(coin, target)
        is_buy = direction == "long"

        orders = [
            {
                "coin": coin, "is_buy": is_buy, "sz": size, "limit_px": entry_px,
                "order_type": {"limit": {"tif": "Gtc"}}, "reduce_only": False,
            },
            {
                "coin": coin, "is_buy": not is_buy, "sz": size, "limit_px": tp_px,
                "order_type": {"trigger": {"isMarket": True, "triggerPx": tp_px, "tpsl": "tp"}},
                "reduce_only": True,
            },
            {
                "coin": coin, "is_buy": not is_buy, "sz": size, "limit_px": sl_px,
                "order_type": {"trigger": {"isMarket": True, "triggerPx": sl_px, "tpsl": "sl"}},
                "reduce_only": True,
            },
        ]

        resp = self.exchange.bulk_orders(orders, grouping="normalTpsl")
        if resp.get("status") != "ok":
            raise RuntimeError(f"Hyperliquid rejected bulk order: {resp}")

        statuses = resp["response"]["data"]["statuses"]
        entry_oid = _oid(statuses[0])
        tp_oid = _oid(statuses[1])
        sl_oid = _oid(statuses[2])

        target_dist = abs(target - entry)
        rr = target_dist / stop_dist

        extras = {k: v for k, v in setup.items()
                  if k not in ("status", "symbol", "direction", "entry", "stop", "target")}

        trade = {
            "id": str(uuid.uuid4())[:8],
            "symbol": coin,
            "direction": direction,
            "entry_price": entry_px,
            "stop_loss": sl_px,
            "take_profit": tp_px,
            "position_size": size,
            "risk_amount": risk,
            "rr_ratio": round(rr, 2),
            "entry_oid": entry_oid,
            "sl_oid": sl_oid,
            "tp_oid": tp_oid,
            "status": "OPEN" if "filled" in statuses[0] else "PENDING",
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "fill_time": None,
            "exit_time": None,
            "exit_price": None,
            "pnl": None,
            "r_multiple": None,
            "outcome": None,
            "notes": "",
            "extras": extras,
        }

        if trade["status"] == "OPEN":
            filled_px = statuses[0].get("filled", {}).get("avgPx")
            if filled_px:
                trade["entry_price"] = float(filled_px)
            trade["fill_time"] = trade["entry_time"]

        trades = self._load()
        trades.append(trade)
        self._save(trades)
        return trade

    # ---------- Exit reconciliation ----------

    def check_exits(self) -> list[dict]:
        """Reconcile journal against exchange state.

        Marks journaled trades as OPEN when their entry fills, CANCELLED
        when their entry is cancelled before filling, and CLOSED when no
        position remains. Returns the list of newly-closed trades.
        """
        trades = self._load()
        # Only reconcile trades we own (those with an exchange entry_oid).
        # Paper-trader entries in the same journal are left untouched.
        live_trades = [t for t in trades
                       if t.get("status") in ("PENDING", "OPEN")
                       and t.get("entry_oid") is not None]
        if not live_trades:
            return []

        # Union open orders and positions across every registered dex —
        # builder perps (xyz, flx, etc.) have separate margin accounts and
        # the SDK's default dex="" only returns the native perp account.
        resting_oids: set[int] = set()
        positions: set[str] = set()
        for dex in self.dex_names:
            try:
                orders = self.info.open_orders(self.wallet_address, dex=dex)
            except TypeError:
                orders = self.info.open_orders(self.wallet_address)
            resting_oids.update(o["oid"] for o in (orders or []))

            try:
                state = self.info.user_state(self.wallet_address, dex=dex)
            except TypeError:
                state = self.info.user_state(self.wallet_address)
            for pos in state.get("assetPositions", []):
                p = pos.get("position") or {}
                if p.get("coin") and float(p.get("szi", 0)) != 0:
                    positions.add(p["coin"])

        fills = self.info.user_fills(self.wallet_address) or []

        newly_closed: list[dict] = []
        changed = False

        for t in live_trades:
            coin = t["symbol"]
            entry_oid = t.get("entry_oid")
            sl_oid = t.get("sl_oid")
            tp_oid = t.get("tp_oid")

            if t["status"] == "PENDING":
                if entry_oid in resting_oids:
                    continue
                entry_fill = _find_fill(fills, entry_oid)
                if entry_fill:
                    t["status"] = "OPEN"
                    t["fill_time"] = _ms_to_iso(entry_fill["time"])
                    t["entry_price"] = float(entry_fill["px"])
                    changed = True
                else:
                    t["status"] = "CANCELLED"
                    t["exit_time"] = datetime.now(timezone.utc).isoformat()
                    t["notes"] = "ENTRY_CANCELLED"
                    changed = True
                    for oid in (sl_oid, tp_oid):
                        if oid in resting_oids:
                            try:
                                self.exchange.cancel(coin, oid)
                            except Exception:
                                pass
                    continue

            if t["status"] == "OPEN":
                if coin in positions:
                    continue
                sl_fill = _find_fill(fills, sl_oid)
                tp_fill = _find_fill(fills, tp_oid)
                if sl_fill:
                    exit_fill, reason = sl_fill, "SL_HIT"
                elif tp_fill:
                    exit_fill, reason = tp_fill, "TP_HIT"
                else:
                    exit_fill = _latest_close_fill(fills, coin)
                    reason = "MANUAL"

                if exit_fill:
                    exit_px = float(exit_fill["px"])
                    exit_time = _ms_to_iso(exit_fill["time"])
                else:
                    exit_px = float(t["entry_price"])
                    exit_time = datetime.now(timezone.utc).isoformat()

                _apply_close(t, reason, exit_px, exit_time)
                newly_closed.append(t)
                changed = True

                sibling = tp_oid if reason == "SL_HIT" else sl_oid
                if sibling in resting_oids:
                    try:
                        self.exchange.cancel(coin, sibling)
                    except Exception:
                        pass

        if changed:
            self._save(trades)
        return newly_closed


# ---------- helpers ----------

def _oid(status: dict) -> int | None:
    if "resting" in status:
        return status["resting"]["oid"]
    if "filled" in status:
        return status["filled"]["oid"]
    return None


def _find_fill(fills: list[dict], oid: int | None) -> dict | None:
    if oid is None:
        return None
    for f in fills:
        if f.get("oid") == oid:
            return f
    return None


def _latest_close_fill(fills: list[dict], coin: str) -> dict | None:
    for f in fills:
        if f.get("coin") == coin and "Close" in f.get("dir", ""):
            return f
    return None


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _apply_close(trade: dict, reason: str, exit_price: float, exit_time: str) -> None:
    trade["status"] = "CLOSED"
    trade["exit_time"] = exit_time
    trade["exit_price"] = exit_price

    if trade["direction"] == "long":
        trade["pnl"] = (exit_price - trade["entry_price"]) * trade["position_size"]
    else:
        trade["pnl"] = (trade["entry_price"] - exit_price) * trade["position_size"]

    stop_dist = abs(trade["entry_price"] - trade["stop_loss"])
    if stop_dist > 0:
        trade["r_multiple"] = round(
            trade["pnl"] / (trade["position_size"] * stop_dist), 2
        )
    else:
        trade["r_multiple"] = 0

    if trade["pnl"] > 0:
        trade["outcome"] = "WIN"
    elif trade["pnl"] < 0:
        trade["outcome"] = "LOSS"
    else:
        trade["outcome"] = "BE"

    trade["notes"] = reason
