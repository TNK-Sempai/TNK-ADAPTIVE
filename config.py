# ═══════════════════════════════════════════════════════════
#  config.py — Paramètres globaux (défauts adaptatifs inclus)
# ═══════════════════════════════════════════════════════════

# ── Exchange ───────────────────────────────────────────────
EXCHANGE        = 'bybit'
TIMEFRAME       = '15m'
QUOTE_CURRENCY  = 'USDT'

# ── Filtre de paires ───────────────────────────────────────
TOP_N_SYMBOLS      = 50        # Ne trader que le top 50 par volume 24h
MIN_VOLUME_USDT    = 500_000   # Volume min 24h en USDT (exclure les illiquides)
SYMBOL_REFRESH_MIN = 60        # Rafraîchir la liste des paires toutes les 60 min

# ── Portfolio paper ────────────────────────────────────────
INITIAL_BALANCE    = 200.0  # USDT fictif de départ
MAX_OPEN_POSITIONS = 8         # Pas plus de 5 trades simultanés
TRADE_SIZE_PCT     = 0.05      # 5% du portfolio par trade

# ── Paramètres par défaut (avant adaptation) ──────────────
DEFAULT_RSI_PERIOD     = 14
DEFAULT_RSI_OVERSOLD   = 35
DEFAULT_RSI_OVERBOUGHT = 65
DEFAULT_MA_FAST        = 7
DEFAULT_MA_SLOW        = 25
DEFAULT_STOP_LOSS_PCT  = 0.03   # -3%
DEFAULT_TAKE_PROFIT_PCT= 0.06   # +6%

# ── Règles d'adaptation ────────────────────────────────────
ADAPT_AFTER_N_TRADES   = 10    # Adapter les params tous les N trades
ADAPT_RSI_STEP         = 2     # Ajustement RSI par itération (+/- 2 points)
ADAPT_SL_STEP          = 0.005 # Ajustement SL (+/- 0.5%)
ADAPT_TP_STEP          = 0.01  # Ajustement TP (+/- 1%)

# Bornes de sécurité pour éviter des valeurs absurdes
RSI_OVERSOLD_MIN, RSI_OVERSOLD_MAX   = 20, 45
RSI_OVERBOUGHT_MIN, RSI_OVERBOUGHT_MAX = 55, 80
SL_MIN, SL_MAX = 0.01, 0.08
TP_MIN, TP_MAX = 0.02, 0.20

# ── Trailing stop ─────────────────────────────────────────
TRAILING_ACTIVATION_PCT = 0.015  # S'active à +1.5% de profit
TRAILING_DISTANCE_PCT   = 0.015  # Suit à -1.5% du meilleur prix

# ── Cooldown post-SL ──────────────────────────────────────
COOLDOWN_AFTER_SL = 14400  # 4 heures en secondes

# ── Filtre ATR ─────────────────────────────────────────────
ATR_PERIOD  = 14   # Période de calcul ATR
MIN_ATR_PCT = 0.8  # Volatilité minimum 0.8% par bougie pour entrer

# ── Filtre tendance MA200 ───────────────────────────────────
MA200_FILTER = True  # False pour désactiver sans toucher au code

# ── WebSocket ──────────────────────────────────────────────
USE_WEBSOCKET         = True   # False = retour au polling immédiat
WS_PING_INTERVAL      = 20     # secondes entre pings keepalive
WS_RECONNECT_DELAY    = 5      # secondes avant reconnexion auto
SIGNAL_TIMEFRAME      = '15'   # minutes : '1','3','5','15','30','60','240'
CHECK_ON_CANDLE_CLOSE = True   # Vérifie les signaux à chaque bougie fermée

# ── Notifications n8n ─────────────────────────────────────
N8N_WEBHOOK_URL = ''  # URL du webhook n8n, vide = désactivé

# ── Bot ────────────────────────────────────────────────────
LOOP_INTERVAL   = 60   # Signaux : toutes les 5 min
SLTP_INTERVAL   = 15    # SL/TP : toutes les 30 secondes
API_PORT        = 5000
OHLCV_LIMIT     = 220   # Nombre de bougies à récupérer par paire (220 pour MA200)
N8N_WEBHOOK_URL = 'http://localhost:5678/webhook-test/af7b6b50-6d24-48af-b00d-c07b2935a87f'
# ── Admin ────────────────────────────────────────────────
ADMIN_TOKEN = 'TNK_SUPER_SECRET_458921'