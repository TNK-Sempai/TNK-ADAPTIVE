# ═══════════════════════════════════════════════════════════
#  symbol_manager.py — Gère la liste des paires /USDT
#  1 seul appel API pour récupérer tous les tickers
#  Filtre par volume et liquidité
# ═══════════════════════════════════════════════════════════

import time
import logging
import ccxt
from config import TOP_N_SYMBOLS, MIN_VOLUME_USDT, SYMBOL_REFRESH_MIN, EXCHANGE

log = logging.getLogger('symbols')

exchange = ccxt.bybit({'enableRateLimit': True})

_symbols_cache     = []
_last_refresh_time = 0.0

def get_active_symbols() -> list[str]:
    """
    Retourne le top N des paires USDT par volume 24h.
    Appelle spot et futures séparément (limitation Bybit API).
    """
    global _symbols_cache, _last_refresh_time

    now = time.time()
    if _symbols_cache and (now - _last_refresh_time) < SYMBOL_REFRESH_MIN * 60:
        return _symbols_cache

    log.info('Rafraîchissement de la liste des paires USDT...')
    try:
        markets = exchange.load_markets()

        # Séparer spot et futures/perp (Bybit refuse de les mélanger)
        spot_syms    = [sym for sym, m in markets.items()
                        if m.get('quote') == 'USDT' and m.get('spot')   and m.get('active')]
        futures_syms = [sym for sym, m in markets.items()
                        if m.get('quote') == 'USDT' and m.get('future') and m.get('active')]
        swap_syms    = [sym for sym, m in markets.items()
                        if m.get('quote') == 'USDT' and m.get('swap')   and m.get('active')]

        log.info(f'  Spot: {len(spot_syms)} | Futures: {len(futures_syms)} | Swap/Perp: {len(swap_syms)}')

        # Fetch tickers par type (appels séparés)
        all_tickers = {}
        for batch in [spot_syms, futures_syms, swap_syms]:
            if not batch:
                continue
            try:
                t = exchange.fetch_tickers(batch)
                all_tickers.update(t)
            except Exception as e:
                log.warning(f'  Batch partiel ignoré: {e}')

        # Filtrer par volume et trier
        usdt_pairs = [
            (sym, t)
            for sym, t in all_tickers.items()
            if t.get('quoteVolume') is not None
            and float(t['quoteVolume'] or 0) >= MIN_VOLUME_USDT
        ]

        usdt_pairs.sort(key=lambda x: float(x[1]['quoteVolume'] or 0), reverse=True)
        top = [sym for sym, _ in usdt_pairs[:TOP_N_SYMBOLS]]

        _symbols_cache     = top
        _last_refresh_time = now

        log.info(f'  {len(top)} paires actives (volume min: {MIN_VOLUME_USDT:,.0f} USDT)')
        log.info(f'  Top 5: {top[:5]}')

        return top

    except Exception as e:
        log.error(f'Erreur fetch symbols: {e}')
        return _symbols_cache

def get_ticker_prices() -> dict[str, float]:
    """
    Retourne un dict {symbol: last_price} pour tous les symboles actifs.
    Appelle spot et futures séparément (limitation Bybit API).
    """
    try:
        symbols  = get_active_symbols()
        markets  = exchange.markets or exchange.load_markets()

        # Séparer par type de marché
        spot    = [s for s in symbols if markets.get(s, {}).get('spot')]
        futures = [s for s in symbols if markets.get(s, {}).get('future')]
        swap    = [s for s in symbols if markets.get(s, {}).get('swap')]

        prices = {}
        for batch in [spot, futures, swap]:
            if not batch:
                continue
            try:
                tickers = exchange.fetch_tickers(batch)
                for sym, t in tickers.items():
                    if t.get('last'):
                        prices[sym] = float(t['last'])
            except Exception as e:
                log.warning(f'  Batch prix ignoré: {e}')

        return prices

    except Exception as e:
        log.error(f'Erreur fetch prices: {e}')
        return {}
