# ═══════════════════════════════════════════════════════════
#  market_data.py — OHLCV par symbole + indicateurs
# ═══════════════════════════════════════════════════════════

import pandas as pd
import logging
from symbol_manager import exchange
from config import TIMEFRAME, OHLCV_LIMIT

log = logging.getLogger('market')

def fetch_ohlcv(symbol: str) -> pd.DataFrame | None:
    try:
        raw = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=OHLCV_LIMIT)
        if not raw or len(raw) < 30:
            return None
        df = pd.DataFrame(raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')
        return df
    except Exception as e:
        log.warning(f'[{symbol}] OHLCV error: {e}')
        return None

def calculate_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Calcule RSI + MAs avec les paramètres adaptatifs du symbole."""
    # RSI
    rsi_period = p['rsi_period']
    delta = df['close'].diff()
    gain  = delta.clip(lower=0).rolling(rsi_period).mean()
    loss  = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs    = gain / loss.replace(0, 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))

    # MAs
    df[f'ma_fast'] = df['close'].rolling(p['ma_fast']).mean()
    df[f'ma_slow'] = df['close'].rolling(p['ma_slow']).mean()

    return df

def get_signal(df: pd.DataFrame, p: dict) -> str | None:
    """
    Signal basé sur les paramètres adaptatifs du symbole.
    LONG  : RSI < oversold  ET  MA fast > MA slow
    SHORT : RSI > overbought ET  MA fast < MA slow
    """
    if len(df) < p['ma_slow'] + 2:
        return None

    cur = df.iloc[-1]
    rsi     = cur['rsi']
    ma_fast = cur['ma_fast']
    ma_slow = cur['ma_slow']

    if pd.isna(rsi) or pd.isna(ma_fast) or pd.isna(ma_slow):
        return None

    if rsi < p['rsi_oversold'] and ma_fast > ma_slow:
        return 'long'

    if rsi > p['rsi_overbought'] and ma_fast < ma_slow:
        return 'short'

    return None

def should_exit(direction: str, df: pd.DataFrame, p: dict) -> bool:
    return False
