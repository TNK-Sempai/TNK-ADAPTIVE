# ═══════════════════════════════════════════════════════════
#  market_data.py — OHLCV par symbole + indicateurs
# ═══════════════════════════════════════════════════════════

import pandas as pd
import logging
from symbol_manager import exchange
from config import TIMEFRAME, OHLCV_LIMIT, ATR_PERIOD, MIN_ATR_PCT, MA200_FILTER

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

def calculate_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.DataFrame:
    """Ajoute la colonne 'atr' (Average True Range sur N périodes)."""
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low']  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(period).mean()
    return df

def calculate_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Calcule RSI + MAs + ATR avec les paramètres adaptatifs du symbole."""
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

    # ATR
    df = calculate_atr(df)

    # MA200 (filtre tendance)
    df['ma200'] = df['close'].rolling(200).mean()

    return df

def get_signal(df: pd.DataFrame, p: dict) -> str | None:
    """
    Signal basé sur les paramètres adaptatifs du symbole.
    LONG  : RSI < oversold  ET  MA fast > MA slow
    SHORT : RSI > overbought ET  MA fast < MA slow
    Filtré si ATR% < MIN_ATR_PCT (marché trop calme).
    """
    if len(df) < p['ma_slow'] + 2:
        return None

    cur = df.iloc[-1]
    rsi     = cur['rsi']
    ma_fast = cur['ma_fast']
    ma_slow = cur['ma_slow']
    atr     = cur.get('atr', float('nan'))

    if pd.isna(rsi) or pd.isna(ma_fast) or pd.isna(ma_slow):
        return None

    # Filtre volatilité : on n'entre pas si le marché bouge trop peu
    if pd.isna(atr) or cur['close'] == 0:
        return None
    atr_pct = atr / cur['close'] * 100
    if atr_pct < MIN_ATR_PCT:
        return None

    # Signal brut (sans filtre tendance)
    signal = None
    if rsi < p['rsi_oversold'] and ma_fast > ma_slow:
        signal = 'long'
    elif rsi > p['rsi_overbought'] and ma_fast < ma_slow:
        signal = 'short'

    if signal is None:
        return None

    # Filtre tendance MA200 : on ne trade que dans le sens du trend
    if MA200_FILTER:
        ma200 = cur.get('ma200')
        if pd.notna(ma200):
            if signal == 'long'  and cur['close'] < ma200:
                return None
            if signal == 'short' and cur['close'] > ma200:
                return None

    return signal

def should_exit(direction: str, df: pd.DataFrame, p: dict) -> bool:
    return False
