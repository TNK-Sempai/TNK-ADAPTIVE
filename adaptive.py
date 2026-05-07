# ═══════════════════════════════════════════════════════════
#  adaptive.py — Cerveau adaptatif
#
#  Après N trades sur un symbole, le bot analyse ses perfs
#  et ajuste automatiquement ses propres paramètres.
#
#  RÈGLES D'ADAPTATION :
#
#  Win rate < 40%  → conditions d'entrée plus strictes
#                    (RSI oversold plus bas, overbought plus haut)
#
#  SL hit > 60%    → le stop est trop serré, on l'élargit
#                    OU les entrées sont mauvaises, on les resserre
#
#  TP hit > 60%    → le TP est trop facilement atteint,
#                    on le monte pour maximiser les gains
#
#  Win rate > 65%  → la strat marche bien, on augmente légèrement
#                    le TP et on desserre un peu le SL
#
#  Avg PnL < 0     → malgré un win rate correct, on perd de l'argent
#                    → ratio R:R mauvais → réduire SL, augmenter TP
# ═══════════════════════════════════════════════════════════

import logging
from database import (
    get_params, save_params, get_recent_trades,
    increment_trades_since_adapt, log_adaptation
)
from config import (
    ADAPT_AFTER_N_TRADES, ADAPT_RSI_STEP, ADAPT_SL_STEP, ADAPT_TP_STEP,
    RSI_OVERSOLD_MIN, RSI_OVERSOLD_MAX, RSI_OVERBOUGHT_MIN, RSI_OVERBOUGHT_MAX,
    SL_MIN, SL_MAX, TP_MIN, TP_MAX
)

log = logging.getLogger('adaptive')

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def should_adapt(symbol: str) -> bool:
    p = get_params(symbol)
    return p['trades_since_adapt'] >= ADAPT_AFTER_N_TRADES

def adapt(symbol: str):
    """
    Analyse les N derniers trades du symbole et ajuste les paramètres.
    Appelé automatiquement après chaque trade fermé si le seuil est atteint.
    """
    trades = get_recent_trades(symbol, ADAPT_AFTER_N_TRADES)
    if len(trades) < ADAPT_AFTER_N_TRADES:
        return

    p = get_params(symbol)
    changes = {}
    reasons = []

    # ── Métriques ────────────────────────────────────────────
    wins        = sum(1 for t in trades if t['win'])
    win_rate    = wins / len(trades)
    avg_pnl     = sum(t['pnl'] for t in trades) / len(trades)
    sl_hits     = sum(1 for t in trades if t['reason'] == 'stop_loss')
    tp_hits     = sum(1 for t in trades if t['reason'] == 'take_profit')
    sl_hit_pct  = sl_hits / len(trades)
    tp_hit_pct  = tp_hits / len(trades)

    log.info(f'[{symbol}] Adaptation — WR: {win_rate:.0%} | AvgPnL: {avg_pnl:+.4f} | SL: {sl_hit_pct:.0%} | TP: {tp_hit_pct:.0%}')

    old_p = {k: p[k] for k in ['rsi_oversold', 'rsi_overbought', 'stop_loss_pct', 'take_profit_pct']}

    # ── Règle 1 : Win rate mauvais → entrées plus strictes ───
    if win_rate < 0.40:
        p['rsi_oversold']   = clamp(p['rsi_oversold']   - ADAPT_RSI_STEP, RSI_OVERSOLD_MIN,  RSI_OVERSOLD_MAX)
        p['rsi_overbought'] = clamp(p['rsi_overbought'] + ADAPT_RSI_STEP, RSI_OVERBOUGHT_MIN, RSI_OVERBOUGHT_MAX)
        reasons.append(f'win_rate faible ({win_rate:.0%}) → RSI plus restrictif')

    # ── Règle 2 : Win rate excellent → on peut assouplir légèrement ──
    elif win_rate > 0.65:
        p['rsi_oversold']   = clamp(p['rsi_oversold']   + ADAPT_RSI_STEP, RSI_OVERSOLD_MIN,  RSI_OVERSOLD_MAX)
        p['rsi_overbought'] = clamp(p['rsi_overbought'] - ADAPT_RSI_STEP, RSI_OVERBOUGHT_MIN, RSI_OVERBOUGHT_MAX)
        reasons.append(f'win_rate excellent ({win_rate:.0%}) → RSI assoupli')

    # ── Règle 3 : Trop de SL → stopper trop serré ────────────
    if sl_hit_pct > 0.60:
        p['stop_loss_pct'] = clamp(p['stop_loss_pct'] + ADAPT_SL_STEP, SL_MIN, SL_MAX)
        reasons.append(f'SL touché {sl_hit_pct:.0%} → SL élargi')

    # ── Règle 4 : TP souvent atteint → le monter ─────────────
    if tp_hit_pct > 0.60:
        p['take_profit_pct'] = clamp(p['take_profit_pct'] + ADAPT_TP_STEP, TP_MIN, TP_MAX)
        reasons.append(f'TP touché {tp_hit_pct:.0%} → TP augmenté')

    # ── Règle 5 : PnL moyen négatif malgré un win rate correct ──
    if avg_pnl < 0 and win_rate >= 0.40:
        # Les losses sont trop gros vs les gains → réduire SL, augmenter TP
        p['stop_loss_pct']   = clamp(p['stop_loss_pct']   - ADAPT_SL_STEP, SL_MIN, SL_MAX)
        p['take_profit_pct'] = clamp(p['take_profit_pct'] + ADAPT_TP_STEP, TP_MIN, TP_MAX)
        reasons.append(f'PnL moyen négatif → ratio R:R corrigé')

    # ── Enregistrement ────────────────────────────────────────
    for k in old_p:
        if abs(p[k] - old_p[k]) > 0.0001:
            changes[k] = {'from': old_p[k], 'to': p[k]}

    reason_str = ' | '.join(reasons) if reasons else 'stable — aucun ajustement'

    p['trades_since_adapt'] = 0
    p['total_adaptations']  = p.get('total_adaptations', 0) + 1
    p['last_adapt_reason']  = reason_str

    save_params(p)
    log_adaptation(symbol, win_rate, avg_pnl, sl_hit_pct, changes)

    if changes:
        for k, v in changes.items():
            log.info(f'  [{symbol}] {k}: {v["from"]} → {v["to"]}')
    else:
        log.info(f'  [{symbol}] Paramètres stables, aucun changement')

def on_trade_closed(trade: dict):
    """
    À appeler après chaque fermeture de trade.
    Incrémente le compteur et adapte si seuil atteint.
    """
    symbol = trade['symbol']
    increment_trades_since_adapt(symbol)
    if should_adapt(symbol):
        adapt(symbol)
