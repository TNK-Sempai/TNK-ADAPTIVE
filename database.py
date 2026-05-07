# ═══════════════════════════════════════════════════════════
#  database.py — SQLite : trades + paramètres adaptatifs
# ═══════════════════════════════════════════════════════════

import sqlite3
import json
from config import (
    DEFAULT_RSI_PERIOD, DEFAULT_RSI_OVERSOLD, DEFAULT_RSI_OVERBOUGHT,
    DEFAULT_MA_FAST, DEFAULT_MA_SLOW, DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT
)

DB_PATH = 'bot.db'

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        # ── État du portfolio ────────────────────────────────
        conn.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')

        # ── Positions ouvertes persistées ────────────────────
        conn.execute('''
            CREATE TABLE IF NOT EXISTS open_positions (
                symbol       TEXT PRIMARY KEY,
                data         TEXT NOT NULL   -- JSON de la position complète
            )
        ''')

        # ── Trades ──────────────────────────────────────────
        conn.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT    NOT NULL,
                type         TEXT    NOT NULL,
                entry_price  REAL    NOT NULL,
                exit_price   REAL    NOT NULL,
                size_usdt    REAL    NOT NULL,
                pnl          REAL    NOT NULL,
                pnl_pct      REAL    NOT NULL,
                entry_time   REAL    NOT NULL,
                exit_time    REAL    NOT NULL,
                reason       TEXT    NOT NULL,
                win          INTEGER NOT NULL,
                -- snapshot des params utilisés pour ce trade
                params_snap  TEXT
            )
        ''')

        # ── Paramètres adaptatifs par symbole ───────────────
        conn.execute('''
            CREATE TABLE IF NOT EXISTS symbol_params (
                symbol           TEXT PRIMARY KEY,
                rsi_period       INTEGER NOT NULL,
                rsi_oversold     REAL    NOT NULL,
                rsi_overbought   REAL    NOT NULL,
                ma_fast          INTEGER NOT NULL,
                ma_slow          INTEGER NOT NULL,
                stop_loss_pct    REAL    NOT NULL,
                take_profit_pct  REAL    NOT NULL,
                trades_since_adapt INTEGER DEFAULT 0,
                total_adaptations  INTEGER DEFAULT 0,
                last_adapt_reason  TEXT    DEFAULT '',
                updated_at         REAL    DEFAULT 0
            )
        ''')

        # ── Journal des adaptations ──────────────────────────
        conn.execute('''
            CREATE TABLE IF NOT EXISTS adapt_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol     TEXT NOT NULL,
                timestamp  REAL NOT NULL,
                win_rate   REAL NOT NULL,
                avg_pnl    REAL NOT NULL,
                sl_hit_pct REAL NOT NULL,
                changes    TEXT NOT NULL   -- JSON des changements
            )
        ''')

        # ── Cooldown post-SL ─────────────────────────────────
        conn.execute('''
            CREATE TABLE IF NOT EXISTS cooldown (
                symbol  TEXT PRIMARY KEY,
                until   REAL NOT NULL
            )
        ''')
        conn.commit()

# ── Params par symbole ─────────────────────────────────────

def get_params(symbol: str) -> dict:
    """Retourne les params adaptatifs du symbole (ou défauts si inconnu)."""
    with get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM symbol_params WHERE symbol = ?', (symbol,)
        ).fetchone()
        if row:
            return dict(row)
        # Premier contact avec ce symbole → défauts
        return {
            'symbol':          symbol,
            'rsi_period':      DEFAULT_RSI_PERIOD,
            'rsi_oversold':    DEFAULT_RSI_OVERSOLD,
            'rsi_overbought':  DEFAULT_RSI_OVERBOUGHT,
            'ma_fast':         DEFAULT_MA_FAST,
            'ma_slow':         DEFAULT_MA_SLOW,
            'stop_loss_pct':   DEFAULT_STOP_LOSS_PCT,
            'take_profit_pct': DEFAULT_TAKE_PROFIT_PCT,
            'trades_since_adapt': 0,
            'total_adaptations':  0,
            'last_adapt_reason':  'initial defaults',
        }

def save_params(p: dict):
    import time
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO symbol_params
                (symbol, rsi_period, rsi_oversold, rsi_overbought,
                 ma_fast, ma_slow, stop_loss_pct, take_profit_pct,
                 trades_since_adapt, total_adaptations, last_adapt_reason, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                rsi_period       = excluded.rsi_period,
                rsi_oversold     = excluded.rsi_oversold,
                rsi_overbought   = excluded.rsi_overbought,
                ma_fast          = excluded.ma_fast,
                ma_slow          = excluded.ma_slow,
                stop_loss_pct    = excluded.stop_loss_pct,
                take_profit_pct  = excluded.take_profit_pct,
                trades_since_adapt = excluded.trades_since_adapt,
                total_adaptations  = excluded.total_adaptations,
                last_adapt_reason  = excluded.last_adapt_reason,
                updated_at         = excluded.updated_at
        ''', (
            p['symbol'], p['rsi_period'], p['rsi_oversold'], p['rsi_overbought'],
            p['ma_fast'], p['ma_slow'], p['stop_loss_pct'], p['take_profit_pct'],
            p['trades_since_adapt'], p['total_adaptations'],
            p.get('last_adapt_reason', ''), time.time()
        ))
        conn.commit()

def increment_trades_since_adapt(symbol: str):
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO symbol_params (symbol, rsi_period, rsi_oversold, rsi_overbought,
                ma_fast, ma_slow, stop_loss_pct, take_profit_pct, trades_since_adapt)
            VALUES (?,?,?,?,?,?,?,?,1)
            ON CONFLICT(symbol) DO UPDATE SET trades_since_adapt = trades_since_adapt + 1
        ''', (
            symbol, DEFAULT_RSI_PERIOD, DEFAULT_RSI_OVERSOLD, DEFAULT_RSI_OVERBOUGHT,
            DEFAULT_MA_FAST, DEFAULT_MA_SLOW, DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT
        ))
        conn.commit()

# ── Trades ─────────────────────────────────────────────────

def save_trade(trade: dict):
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO trades
            (symbol, type, entry_price, exit_price, size_usdt, pnl, pnl_pct,
             entry_time, exit_time, reason, win, params_snap)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            trade['symbol'], trade['type'], trade['entry_price'], trade['exit_price'],
            trade['size_usdt'], trade['pnl'], trade['pnl_pct'],
            trade['entry_time'], trade['exit_time'], trade['reason'],
            int(trade['win']), json.dumps(trade.get('params_snap', {}))
        ))
        conn.commit()

def get_recent_trades(symbol: str, limit: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM trades WHERE symbol = ? ORDER BY exit_time DESC LIMIT ?',
            (symbol, limit)
        ).fetchall()
        return [dict(r) for r in rows]

def get_all_trades(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM trades ORDER BY exit_time DESC LIMIT ?', (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

# ── Adapt log ──────────────────────────────────────────────

def log_adaptation(symbol: str, win_rate: float, avg_pnl: float,
                   sl_hit_pct: float, changes: dict):
    import time
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO adapt_log (symbol, timestamp, win_rate, avg_pnl, sl_hit_pct, changes)
            VALUES (?,?,?,?,?,?)
        ''', (symbol, time.time(), win_rate, avg_pnl, sl_hit_pct, json.dumps(changes)))
        conn.commit()

def get_adapt_log(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM adapt_log ORDER BY timestamp DESC LIMIT ?', (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_all_symbol_params() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM symbol_params ORDER BY symbol').fetchall()
        return [dict(r) for r in rows]

# ── Portfolio state ────────────────────────────────────────

def save_portfolio_state(balance: float, peak_equity: float):
    """Sauvegarde la balance et le peak equity après chaque changement."""
    with get_conn() as conn:
        for key, val in [('balance', balance), ('peak_equity', peak_equity)]:
            conn.execute(
                'INSERT INTO portfolio_state (key, value) VALUES (?,?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                (key, str(val))
            )
        conn.commit()

def load_portfolio_state(initial_balance: float) -> tuple[float, float]:
    """
    Charge la balance et le peak equity depuis la DB.
    Retourne (balance, peak_equity) ou les valeurs initiales si première fois.
    """
    with get_conn() as conn:
        rows = conn.execute('SELECT key, value FROM portfolio_state').fetchall()
        state = {r['key']: float(r['value']) for r in rows}
        balance     = state.get('balance',     initial_balance)
        peak_equity = state.get('peak_equity', initial_balance)
        return balance, peak_equity

def save_open_positions(positions: dict):
    """Écrase toutes les positions ouvertes en DB."""
    with get_conn() as conn:
        conn.execute('DELETE FROM open_positions')
        for symbol, pos in positions.items():
            conn.execute(
                'INSERT INTO open_positions (symbol, data) VALUES (?,?)',
                (symbol, json.dumps(pos))
            )
        conn.commit()

def load_open_positions() -> dict:
    """Recharge les positions ouvertes depuis la DB."""
    with get_conn() as conn:
        rows = conn.execute('SELECT symbol, data FROM open_positions').fetchall()
        return {r['symbol']: json.loads(r['data']) for r in rows}

def set_cooldown(symbol: str, seconds: int = 3600):
    import time
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO cooldown (symbol, until) VALUES (?,?) '
            'ON CONFLICT(symbol) DO UPDATE SET until = excluded.until',
            (symbol, time.time() + seconds)
        )
        conn.commit()

def is_on_cooldown(symbol: str) -> bool:
    import time
    with get_conn() as conn:
        row = conn.execute(
            'SELECT until FROM cooldown WHERE symbol = ?', (symbol,)
        ).fetchone()
        return row is not None and time.time() < row['until']

def get_global_stats() -> dict:
    with get_conn() as conn:
        row = conn.execute('''
            SELECT COUNT(*) as total, SUM(win) as wins, SUM(pnl) as total_pnl,
                   COUNT(DISTINCT symbol) as symbols_traded
            FROM trades
        ''').fetchone()
        d = dict(row)
        d['win_rate'] = round(d['wins'] / d['total'] * 100, 2) if d['total'] else 0
        return d
