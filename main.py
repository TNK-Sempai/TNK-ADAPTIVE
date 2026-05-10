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
from api            import start_api, update_state, notify_n8n
from config         import (
    LOOP_INTERVAL, SLTP_INTERVAL, API_PORT, INITIAL_BALANCE,
    USE_WEBSOCKET, SIGNAL_TIMEFRAME, CHECK_ON_CANDLE_CLOSE,
)

try:
    from ws_manager import init_ws_manager, get_ws_manager
    _WS_LIB = True
except ImportError:
    _WS_LIB = False
    def get_ws_manager(): return None

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = '%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt = '%H:%M:%S',
)
log = logging.getLogger('main')
SEP = '═' * 65

# ── Globals partagés pour le callback WS ──────────────────
_broker: PaperBroker | None = None
_signals: dict = {}
_signals_lock = threading.Lock()


def on_candle_close(symbol: str, candles: list[dict]):
    """Callback WS déclenché à chaque bougie fermée : gère signaux entrée/sortie."""
    if _broker is None:
        return
    try:
        ws = get_ws_manager()
        price = ws.get_price(symbol) if ws else None
        if not price:
            return
        params = get_params(symbol)
        sig = process_symbol(symbol, price, _broker, params)
        with _signals_lock:
            if sig:
                _signals[symbol] = sig
            else:
                _signals.pop(symbol, None)
    except Exception as e:
        log.error(f'[WS CB] {symbol}: {e}')


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
        if closed['win']:
            notify_n8n('trade_win', {
                'symbol': closed['symbol'], 'pnl': closed['pnl'],
                'pnl_pct': closed['pnl_pct'], 'reason': closed['reason'],
            })
        else:
            notify_n8n('trade_loss', {
                'symbol': closed['symbol'], 'pnl': closed['pnl'],
                'pnl_pct': closed['pnl_pct'], 'reason': closed['reason'],
            })
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
                event = 'trade_win' if closed['win'] else 'trade_loss'
                notify_n8n(event, {
                    'symbol': closed['symbol'], 'pnl': closed['pnl'],
                    'pnl_pct': closed['pnl_pct'], 'reason': closed['reason'],
                })

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
            notify_n8n('trade_open', {
                'symbol': symbol, 'direction': signal,
                'entry_price': opened['entry_price'], 'size_usdt': opened['size_usdt'],
            })

    return signal


def _handle_sltp(sym: str, price: float, broker: PaperBroker):
    """SL/TP check standalone pour le heartbeat WS."""
    closed = broker.check_sl_tp(sym, price)
    if not closed:
        return
    save_trade(closed)
    on_trade_closed(closed)
    emoji = '✅' if closed['win'] else '❌'
    log.info(f'  {emoji} {sym} [{closed["reason"].upper()}] {closed["pnl"]:+.4f} USDT ({closed["pnl_pct"]:+.2f}%)')
    event = 'trade_win' if closed['win'] else 'trade_loss'
    notify_n8n(event, {
        'symbol': closed['symbol'], 'pnl': closed['pnl'],
        'pnl_pct': closed['pnl_pct'], 'reason': closed['reason'],
    })
    if closed['reason'] == 'stop_loss':
        set_cooldown(sym)
        log.info(f'  ❄️  [{sym}] Cooldown 4h activé après SL')


def main():
    global _broker

    log.info(SEP)
    log.info('  🦝  TNK Paper Trading Bot — Multi-paires + Adaptatif')
    log.info(f'  Balance initiale : {INITIAL_BALANCE:,.0f} USDT (paper)')
    log.info(f'  Dashboard        : http://localhost:{API_PORT}')
    log.info(SEP)

    init_db()
    broker = PaperBroker()
    _broker = broker

    # Démarrer Flask en background
    threading.Thread(target=start_api, args=(API_PORT,), daemon=True).start()
    time.sleep(1.5)

    # Récupérer les symboles initiaux
    initial_prices = get_ticker_prices()
    if not initial_prices:
        log.error('Impossible de récupérer les prix initiaux. Arrêt.')
        return
    symbols = list(initial_prices.keys())

    # Init WebSocket si activé
    ws = None
    if USE_WEBSOCKET and _WS_LIB:
        try:
            ws = init_ws_manager(symbols, SIGNAL_TIMEFRAME)
            ws.register_callback(on_candle_close)
            log.info(f'[WS] Actif — {len(symbols)} paires | TF: {SIGNAL_TIMEFRAME}m')
        except Exception as e:
            log.warning(f'[WS] Echec init ({e}) → retour au polling')
            ws = None

    iteration = 0
    last_sltp_check = 0
    last_heartbeat_log = 0
    prices = {}

    while True:
        try:
            now = time.time()

            if ws:
                # ── Mode WebSocket : boucle rapide, SL/TP toutes les SLTP_INTERVAL ──

                # Check SL/TP + update dashboard toutes les SLTP_INTERVAL (15s)
                if now - last_sltp_check >= SLTP_INTERVAL:
                    ws_prices = {s: ws.get_price(s) for s in symbols if ws.get_price(s)}
                    if not ws_prices:
                        log.warning('[WS] Aucun prix disponible, attente...')
                    else:
                        prices = ws_prices
                        for sym in list(broker.positions.keys()):
                            price = ws.get_price(sym) or prices.get(sym)
                            if price:
                                _handle_sltp(sym, price, broker)
                        with _signals_lock:
                            sigs = dict(_signals)
                        update_state(broker, prices, sigs)
                    last_sltp_check = now

                # Heartbeat log toutes les LOOP_INTERVAL (60s)
                if now - last_heartbeat_log >= LOOP_INTERVAL:
                    iteration += 1
                    ws_prices = {s: ws.get_price(s) for s in symbols if ws.get_price(s)}
                    if ws_prices:
                        prices = ws_prices
                    with _signals_lock:
                        sigs = dict(_signals)
                    stats = broker.get_stats(prices)
                    log.info(f'[#{iteration}] {SEP[-40:]}')
                    log.info(f'  ⚡ WS | {len(prices)} prix | {len(broker.positions)} positions ouvertes')
                    log.info(
                        f'  💰 Equity: {stats["equity"]:.2f} USDT  |  '
                        f'Rendement: {stats["return_pct"]:+.2f}%  |  '
                        f'Trades: {stats["total_trades"]}  |  '
                        f'WR: {stats["win_rate"]:.1f}%  |  '
                        f'DD: {stats["max_drawdown_pct"]:.2f}%'
                    )
                    if sigs:
                        log.info(f'  📡 Signaux: {sigs}')
                    last_heartbeat_log = now

                time.sleep(5)

            else:
                # ── Mode Polling : comportement original ──────────
                iteration += 1
                t_start = time.time()
                log.info(f'[#{iteration}] {SEP[-40:]}')

                prices = get_ticker_prices()
                if not prices:
                    log.warning('Impossible de récupérer les prix. Retry dans 30s.')
                    time.sleep(30)
                    continue

                symbols = list(prices.keys())
                log.info(f'  {len(symbols)} paires actives | {len(broker.positions)} positions ouvertes')

                sigs = {}
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
                                sigs[sym] = sig
                        except Exception as e:
                            log.error(f'  [{sym}] Erreur: {e}')

                # ── Stats + dashboard (mode Polling) ──────────────
                stats = broker.get_stats(prices)
                log.info(
                    f'  💰 Equity: {stats["equity"]:.2f} USDT  |  '
                    f'Rendement: {stats["return_pct"]:+.2f}%  |  '
                    f'Trades: {stats["total_trades"]}  |  '
                    f'WR: {stats["win_rate"]:.1f}%  |  '
                    f'DD: {stats["max_drawdown_pct"]:.2f}%'
                )

                if sigs:
                    log.info(f'  📡 Signaux: {sigs}')

                update_state(broker, prices, sigs)

                elapsed = time.time() - t_start
                wait    = max(0, LOOP_INTERVAL - elapsed)
                log.info(f'  🔄 Polling | Traitement: {elapsed:.1f}s | Prochain check dans {wait:.0f}s')
                time.sleep(wait)

        except KeyboardInterrupt:
            log.info('Bot arrêté.')
            if ws:
                ws.stop()
            break
        except Exception as e:
            log.error(f'Erreur critique: {e}', exc_info=True)
            time.sleep(30)

if __name__ == '__main__':
    main()
