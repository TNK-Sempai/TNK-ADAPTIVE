# ═══════════════════════════════════════════════════════════
#  paper_broker.py — Broker multi-paires avec argent fictif
#  Portfolio entièrement persisté en SQLite (survit aux redémarrages)
# ═══════════════════════════════════════════════════════════

import time
import threading
import logging
from config import (
    INITIAL_BALANCE, TRADE_SIZE_PCT, MAX_OPEN_POSITIONS,
    TRAILING_ACTIVATION_PCT, TRAILING_DISTANCE_PCT,
)
from database import (
    save_portfolio_state, load_portfolio_state,
    save_open_positions, load_open_positions,
    get_all_trades,
)

log = logging.getLogger('broker')

class PaperBroker:

    def __init__(self):
        self._lock = threading.Lock()

        # ── Chargement depuis la DB ────────────────────────
        self.balance, self.peak_equity = load_portfolio_state(INITIAL_BALANCE)
        self.positions = load_open_positions()

        # Historique en RAM reconstruit depuis la DB
        self.trades = get_all_trades(limit=99999)

        if self.positions:
            log.info(f'  🔄 {len(self.positions)} position(s) restaurée(s) depuis la DB')
        log.info(f'  💰 Balance restaurée : {self.balance:.2f} USDT')

    def _persist(self):
        """Sauvegarde l'état complet après chaque modification."""
        save_portfolio_state(self.balance, self.peak_equity)
        save_open_positions(self.positions)

    # ── Ouvrir ────────────────────────────────────────────────
    def open_position(self, symbol: str, direction: str, price: float, params: dict) -> dict | None:
        with self._lock:
            if symbol in self.positions:
                return None  # Déjà en position sur ce symbole
            if len(self.positions) >= MAX_OPEN_POSITIONS:
                return None  # Trop de positions ouvertes
            if self.balance <= 0:
                return None

            usdt_size    = self.balance * TRADE_SIZE_PCT
            token_size   = usdt_size / price
            sl_pct       = params['stop_loss_pct']
            tp_pct       = params['take_profit_pct']

            if direction == 'long':
                sl = price * (1 - sl_pct)
                tp = price * (1 + tp_pct)
            else:
                sl = price * (1 + sl_pct)
                tp = price * (1 - tp_pct)

            pos = {
                'symbol':          symbol,
                'type':            direction,
                'entry_price':     price,
                'size_tokens':     token_size,
                'size_usdt':       usdt_size,
                'stop_loss':       sl,
                'take_profit':     tp,
                'entry_time':      time.time(),
                'trailing_active': False,
                'best_price':      price,
                'params_snap': {k: params[k] for k in
                    ['rsi_oversold', 'rsi_overbought', 'stop_loss_pct', 'take_profit_pct']},
            }
            self.positions[symbol] = pos
            self.balance -= usdt_size
            self._persist()
            return pos

    # ── Fermer ────────────────────────────────────────────────
    def close_position(self, symbol: str, price: float, reason: str = 'signal') -> dict | None:
        with self._lock:
            pos = self.positions.pop(symbol, None)
            if pos is None:
                return None

            if pos['type'] == 'long':
                pnl = (price - pos['entry_price']) / pos['entry_price'] * pos['size_usdt']
            else:
                pnl = (pos['entry_price'] - price) / pos['entry_price'] * pos['size_usdt']

            pnl_pct = pnl / pos['size_usdt'] * 100
            self.balance += pos['size_usdt'] + pnl

            trade = {
                'symbol':      symbol,
                'type':        pos['type'],
                'entry_price': pos['entry_price'],
                'exit_price':  price,
                'size_usdt':   pos['size_usdt'],
                'pnl':         round(pnl, 6),
                'pnl_pct':     round(pnl_pct, 4),
                'entry_time':  pos['entry_time'],
                'exit_time':   time.time(),
                'reason':      reason,
                'win':         pnl > 0,
                'params_snap': pos['params_snap'],
            }
            self.trades.append(trade)

            equity = self._equity_locked()
            if equity > self.peak_equity:
                self.peak_equity = equity

            self._persist()
            return trade

    # ── DCA / augmenter la mise ───────────────────────────────
    def add_to_position(self, symbol: str, price: float, extra_usdt: float) -> dict | None:
        with self._lock:
            pos = self.positions.get(symbol)
            if not pos:
                return None
            if self.balance < extra_usdt:
                extra_usdt = self.balance
            if extra_usdt <= 0:
                return None

            total_usdt   = pos['size_usdt']   + extra_usdt
            total_tokens = pos['size_tokens'] + extra_usdt / price
            avg_price    = total_usdt / total_tokens

            pos['size_usdt']   = total_usdt
            pos['size_tokens'] = total_tokens
            pos['entry_price'] = avg_price

            sl_pct = pos['params_snap'].get('stop_loss_pct',   0.03)
            tp_pct = pos['params_snap'].get('take_profit_pct', 0.06)
            if pos['type'] == 'long':
                pos['stop_loss']   = avg_price * (1 - sl_pct)
                pos['take_profit'] = avg_price * (1 + tp_pct)
            else:
                pos['stop_loss']   = avg_price * (1 + sl_pct)
                pos['take_profit'] = avg_price * (1 - tp_pct)

            # Réinitialise le trailing stop sur le nouveau prix moyen
            pos['trailing_active'] = False
            pos['best_price']      = price

            self.balance -= extra_usdt
            self._persist()
            return pos

    # ── Trailing stop ─────────────────────────────────────────
    def update_trailing(self, symbol: str, current_price: float):
        with self._lock:
            pos = self.positions.get(symbol)
            if not pos:
                return

            # Compatibility: positions restored from DB without trailing fields
            if 'trailing_active' not in pos:
                pos['trailing_active'] = False
                pos['best_price'] = pos['entry_price']

            direction = pos['type']
            entry = pos['entry_price']

            # Track the most favourable price seen
            if direction == 'long':
                if current_price > pos['best_price']:
                    pos['best_price'] = current_price
            else:
                if current_price < pos['best_price']:
                    pos['best_price'] = current_price

            # Activate once profit exceeds threshold
            if direction == 'long':
                profit_pct = (current_price - entry) / entry
            else:
                profit_pct = (entry - current_price) / entry

            if profit_pct >= TRAILING_ACTIVATION_PCT:
                pos['trailing_active'] = True

            # Move the SL only when trailing is active, and only in the winning direction
            if pos['trailing_active']:
                sl_changed = False
                if direction == 'long':
                    trailing_sl = pos['best_price'] * (1 - TRAILING_DISTANCE_PCT)
                    if trailing_sl > pos['stop_loss']:
                        pos['stop_loss'] = trailing_sl
                        sl_changed = True
                else:
                    trailing_sl = pos['best_price'] * (1 + TRAILING_DISTANCE_PCT)
                    if trailing_sl < pos['stop_loss']:
                        pos['stop_loss'] = trailing_sl
                        sl_changed = True

                if sl_changed:
                    self._persist()

    # ── SL / TP check ────────────────────────────────────────
    def check_sl_tp(self, symbol: str, price: float) -> dict | None:
        self.update_trailing(symbol, price)

        pos = self.positions.get(symbol)
        if not pos:
            return None

        hit = None
        if pos['type'] == 'long':
            if price <= pos['stop_loss']:   hit = 'stop_loss'
            elif price >= pos['take_profit']: hit = 'take_profit'
        else:
            if price >= pos['stop_loss']:   hit = 'stop_loss'
            elif price <= pos['take_profit']: hit = 'take_profit'

        if hit:
            return self.close_position(symbol, price, hit)
        return None

    # ── PnL non réalisé ──────────────────────────────────────
    def unrealized_pnl(self, prices: dict) -> float:
        total = 0.0
        for sym, pos in self.positions.items():
            price = prices.get(sym)
            if price is None:
                continue
            if pos['type'] == 'long':
                total += (price - pos['entry_price']) / pos['entry_price'] * pos['size_usdt']
            else:
                total += (pos['entry_price'] - price) / pos['entry_price'] * pos['size_usdt']
        return total

    def _equity_locked(self) -> float:
        locked = sum(p['size_usdt'] for p in self.positions.values())
        return self.balance + locked

    # ── Stats globales ────────────────────────────────────────
    def get_stats(self, prices: dict) -> dict:
        upnl     = self.unrealized_pnl(prices)
        locked   = sum(p['size_usdt'] for p in self.positions.values())
        equity   = self.balance + locked + upnl
        # Utiliser les trades chargés depuis la DB (historique complet)
        pnl_real = sum(t['pnl'] for t in self.trades)
        wins     = sum(1 for t in self.trades if t['win'])
        total    = len(self.trades)
        dd       = max(0, (self.peak_equity - equity) / self.peak_equity * 100) if self.peak_equity else 0

        return {
            'initial_balance':   INITIAL_BALANCE,
            'cash':              round(self.balance, 2),
            'equity':            round(equity, 2),
            'total_pnl':         round(pnl_real, 4),
            'unrealized_pnl':    round(upnl, 4),
            'return_pct':        round((equity - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 4),
            'win_rate':          round(wins / total * 100, 2) if total else 0,
            'total_trades':      total,
            'wins':              wins,
            'losses':            total - wins,
            'open_positions':    len(self.positions),
            'max_drawdown_pct':  round(dd, 4),
        }

    def get_positions_snapshot(self, prices: dict) -> list[dict]:
        result = []
        for sym, pos in self.positions.items():
            price = prices.get(sym, pos['entry_price'])
            if pos['type'] == 'long':
                upnl = (price - pos['entry_price']) / pos['entry_price'] * pos['size_usdt']
            else:
                upnl = (pos['entry_price'] - price) / pos['entry_price'] * pos['size_usdt']
            result.append({
                **pos,
                'current_price':   price,
                'unrealized_pnl':  round(upnl, 6),
                'trailing_active': pos.get('trailing_active', False),
                'best_price':      pos.get('best_price', pos['entry_price']),
            })
        return result
