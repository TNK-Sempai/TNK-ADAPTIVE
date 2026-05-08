# ═══════════════════════════════════════════════════════════
#  ws_manager.py — WebSocket Bybit V5 (klines temps réel)
#  Singleton : une connexion linear + une connexion spot.
#  Pré-charge l'historique ccxt au démarrage pour warmup immédiat.
# ═══════════════════════════════════════════════════════════

import threading
import logging
from typing import Callable

from config import WS_PING_INTERVAL

log = logging.getLogger('websocket')

# Mapping SIGNAL_TIMEFRAME → timeframe ccxt
_TF_MAP = {
    '1': '1m', '3': '3m', '5': '5m', '15': '15m',
    '30': '30m', '60': '1h', '240': '4h', '1440': '1d',
}


class WebSocketManager:

    def __init__(self, symbols: list[str], timeframe: str = '15'):
        self._timeframe  = timeframe
        self._prices: dict[str, float]      = {}
        self._candles: dict[str, list[dict]] = {}
        self._callbacks: list[Callable]      = []
        self._lock    = threading.Lock()
        self._running = False
        self._ws_linear = None
        self._ws_spot   = None

        linear_syms = [s for s in symbols if ':' in s]
        spot_syms   = [s for s in symbols if ':' not in s]

        # Reverse maps : BTCUSDT → BTC/USDT:USDT (ou BTC/USDT)
        self._linear_map: dict[str, str] = {self._to_bybit(s): s for s in linear_syms}
        self._spot_map:   dict[str, str] = {self._to_bybit(s): s for s in spot_syms}

        # 1. Pré-charge l'historique ccxt (bloquant, rapide)
        self._preload(symbols)

        # 2. Lance les connexions WS en background
        self._running = True
        if linear_syms:
            threading.Thread(
                target=self._connect, args=(linear_syms, 'linear'),
                daemon=True, name='ws-linear',
            ).start()
        if spot_syms:
            threading.Thread(
                target=self._connect, args=(spot_syms, 'spot'),
                daemon=True, name='ws-spot',
            ).start()

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _to_bybit(symbol: str) -> str:
        """BTC/USDT:USDT → BTCUSDT"""
        return symbol.split(':')[0].replace('/', '')

    # ── Pré-chargement historique ─────────────────────────────
    def _preload(self, symbols: list[str]):
        """Charge 220 bougies ccxt pour chaque symbole avant le démarrage WS."""
        from symbol_manager import exchange
        tf = _TF_MAP.get(self._timeframe, '15m')
        loaded = 0
        for sym in symbols:
            try:
                raw = exchange.fetch_ohlcv(sym, tf, limit=220)
                if not raw or len(raw) < 30:
                    continue
                candles = [
                    {
                        'timestamp': c[0],
                        'open':  float(c[1]),
                        'high':  float(c[2]),
                        'low':   float(c[3]),
                        'close': float(c[4]),
                        'volume': float(c[5]),
                    }
                    for c in raw
                ]
                with self._lock:
                    self._candles[sym] = candles
                    self._prices[sym]  = candles[-1]['close']
                loaded += 1
            except Exception as e:
                log.debug(f'[WS] Preload {sym}: {e}')
        log.info(f'[WS] Preload terminé : {loaded}/{len(symbols)} symboles')

    # ── Connexion WebSocket ────────────────────────────────────
    def _connect(self, symbols: list[str], channel_type: str):
        try:
            from pybit.unified_trading import WebSocket
            ws = WebSocket(
                testnet=False,
                channel_type=channel_type,
                ping_interval=WS_PING_INTERVAL,
            )
            if channel_type == 'linear':
                self._ws_linear = ws
            else:
                self._ws_spot = ws

            rev_map    = self._linear_map if channel_type == 'linear' else self._spot_map
            dispatcher = lambda msg: self._on_message(msg, rev_map)

            for sym in symbols:
                ws.kline_stream(
                    interval=int(self._timeframe),
                    symbol=self._to_bybit(sym),
                    callback=dispatcher,
                )
            log.info(f'[WS] {channel_type}: {len(symbols)} symboles connectés')

        except Exception as e:
            log.error(f'[WS] Erreur connexion {channel_type}: {e}')

    # ── Handler messages ──────────────────────────────────────
    def _on_message(self, msg: dict, rev_map: dict[str, str]):
        try:
            topic = msg.get('topic', '')          # "kline.15.BTCUSDT"
            parts = topic.split('.')
            if len(parts) < 3:
                return

            bybit_sym = parts[2]
            symbol    = rev_map.get(bybit_sym)
            if not symbol:
                return

            data_list = msg.get('data', [])
            if not data_list:
                return
            data  = data_list[0]
            close = float(data['close'])

            # Mise à jour prix temps réel (messages non-confirmés inclus)
            with self._lock:
                self._prices[symbol] = close

            if not data.get('confirm', False):
                return  # bougie non fermée — prix mis à jour, pas de signal

            candle = {
                'timestamp': int(data['start']),
                'open':      float(data['open']),
                'high':      float(data['high']),
                'low':       float(data['low']),
                'close':     close,
                'volume':    float(data['volume']),
            }

            with self._lock:
                candles = self._candles.setdefault(symbol, [])
                candles.append(candle)
                if len(candles) > 220:
                    candles.pop(0)
                snapshot = list(candles)

            log.debug(f'[WS] {symbol} — bougie {self._timeframe}m fermée → signal check')

            for cb in self._callbacks:
                try:
                    cb(symbol, snapshot)
                except Exception as e:
                    log.error(f'[WS] Callback erreur {symbol}: {e}')

        except Exception as e:
            log.warning(f'[WS] Parsing erreur: {e}')

    # ── API publique ──────────────────────────────────────────
    def register_callback(self, fn: Callable):
        self._callbacks.append(fn)

    def get_price(self, symbol: str) -> float | None:
        return self._prices.get(symbol)

    def get_candles(self, symbol: str) -> list[dict] | None:
        return self._candles.get(symbol)

    def is_ready(self, symbol: str) -> bool:
        """True dès que le symbole a au moins 50 bougies (preload = immédiat)."""
        return len(self._candles.get(symbol, [])) >= 50

    def stop(self):
        self._running = False
        for ws in (self._ws_linear, self._ws_spot):
            if ws:
                try:
                    ws.exit()
                except Exception:
                    pass
        log.info('[WS] Connexions fermées')


# ── Singleton ─────────────────────────────────────────────
_ws_manager_instance: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager | None:
    return _ws_manager_instance


def init_ws_manager(symbols: list[str], timeframe: str = '15') -> WebSocketManager:
    global _ws_manager_instance
    _ws_manager_instance = WebSocketManager(symbols, timeframe)
    return _ws_manager_instance
