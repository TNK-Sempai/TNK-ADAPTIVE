# ═══════════════════════════════════════════════════════════
#  main.py — Boucle principale multi-paires + apprentissage
#
#  Lancement : python main.py
#  Dashboard : ouvre dashboard/index.html dans le browser
# ═══════════════════════════════════════════════════════════

import time
import threading
import logging
import concurrent.futures
import pandas as pd

from symbol_manager import get_active_symbols, get_ticker_prices
from market_data    import fetch_ohlcv, calculate_indicators, get_signal, should_exit
from paper_broker   import PaperBroker
from database       import init_db, save_trade, get_params, is_on_cooldown, set_cooldown
from adaptive       import on_trade_closed
from api            import start_api, update_state
from config         import LOOP_INTERVAL, API_PORT, INITIAL_BALANCE

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = '%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt = '%H:%M:%S',
)
log = logging.getLogger('main')
SEP = '═' * 65

def process_symbol(symbol: str, price: float, broker: PaperBroker, params: dict) -> str | None:
    """
    Traite un symbole : fetch OHLCV → indicateurs → signal → ordre.
    Retourne le signal détecté ou None.
    """
    df = fetch_ohlcv(symbol)
    if df is None:
        return None

    df = calculate_indicators(df, params)

    last    = df.iloc[-1]
    atr_pct = (last['atr'] / last['close'] * 100) if last['close'] else 0.0
    ma200   = last.get('ma200')

    # ── SL / TP ───────────────────────────────────────────
    closed = broker.check_sl_tp(symbol, price)
    if closed:
        save_trade(closed)
        on_trade_closed(closed)
        emoji = '✅' if closed['win'] else '❌'
        log.info(f'  {emoji} {symbol} [{closed["reason"].upper()}] {closed["pnl"]:+.4f} USDT ({closed["pnl_pct"]:+.2f}%)')
        if closed['reason'] == 'stop_loss':
            set_cooldown(symbol)
            log.info(f'  ❄️  [{symbol}] Cooldown 4h activé après SL')

    # ── Exit signal ───────────────────────────────────────
    if broker.positions.get(symbol) and not closed:
        pos = broker.positions[symbol]
        if should_exit(pos['type'], df, params):
            closed = broker.close_position(symbol, price, 'signal')
            if closed:
                save_trade(closed)
                on_trade_closed(closed)
                emoji = '✅' if closed['win'] else '❌'
                log.info(f'  {emoji} {symbol} [SIGNAL EXIT] {closed["pnl"]:+.4f} USDT')

    # ── Entry signal ──────────────────────────────────────
    signal = get_signal(df, params)
    if signal and symbol not in broker.positions:
        if is_on_cooldown(symbol):
            return signal
        opened = broker.open_position(symbol, signal, price, params)
        if opened:
            arrow = '📈' if signal == 'long' else '📉'
            trend_info = (
                f'  MA200:{ma200:.6g} {"↑" if price > ma200 else "↓"}'
                if pd.notna(ma200) else ''
            )
            log.info(
                f'  {arrow} {symbol} [{signal.upper()}] '
                f'@ {price:.6g}  SL:{opened["stop_loss"]:.6g}  TP:{opened["take_profit"]:.6g}  '
                f'ATR:{atr_pct:.2f}%{trend_info}'
            )

    return signal

def main():
    log.info(SEP)
    log.info('  🦝  TNK Paper Trading Bot — Multi-paires + Adaptatif')
    log.info(f'  Balance initiale : {INITIAL_BALANCE:,.0f} USDT (paper)')
    log.info(f'  Dashboard        : http://localhost:{API_PORT}')
    log.info(SEP)

    init_db()
    broker = PaperBroker()

    # Démarrer Flask en background
    threading.Thread(target=start_api, args=(API_PORT,), daemon=True).start()
    time.sleep(1.5)

    iteration = 0

    while True:
        try:
            iteration += 1
            t_start = time.time()
            log.info(f'[#{iteration}] {SEP[-40:]}')

            # ── 1. Prix de tous les symboles (1 seul appel) ──
            prices = get_ticker_prices()
            if not prices:
                log.warning('Impossible de récupérer les prix. Retry dans 30s.')
                time.sleep(30)
                continue

            symbols = list(prices.keys())
            log.info(f'  {len(symbols)} paires actives | {len(broker.positions)} positions ouvertes')

            # ── 2. Traitement parallèle des symboles ──────────
            signals = {}

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = {}
                for sym in symbols:
                    p = prices.get(sym)
                    if p is None:
                        continue
                    params = get_params(sym)
                    futures[executor.submit(process_symbol, sym, p, broker, params)] = sym

                for fut in concurrent.futures.as_completed(futures):
                    sym = futures[fut]
                    try:
                        sig = fut.result()
                        if sig:
                            signals[sym] = sig
                    except Exception as e:
                        log.error(f'  [{sym}] Erreur: {e}')

            # ── 3. Stats ──────────────────────────────────────
            stats = broker.get_stats(prices)
            log.info(
                f'  💰 Equity: {stats["equity"]:.2f} USDT  |  '
                f'Rendement: {stats["return_pct"]:+.2f}%  |  '
                f'Trades: {stats["total_trades"]}  |  '
                f'WR: {stats["win_rate"]:.1f}%  |  '
                f'DD: {stats["max_drawdown_pct"]:.2f}%'
            )

            if signals:
                log.info(f'  📡 Signaux: {signals}')

            # ── 4. Update dashboard ───────────────────────────
            update_state(broker, prices, signals)

            elapsed = time.time() - t_start
            wait    = max(0, LOOP_INTERVAL - elapsed)
            log.info(f'  Traitement: {elapsed:.1f}s | Prochain check dans {wait:.0f}s')

            time.sleep(wait)

        except KeyboardInterrupt:
            log.info('Bot arrêté.')
            break
        except Exception as e:
            log.error(f'Erreur critique: {e}', exc_info=True)
            time.sleep(30)

if __name__ == '__main__':
    main()
