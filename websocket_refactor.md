# TNK ADAPTIVE — Refonte WebSocket
## Architecture Event-Driven Bybit

> Découpe en 4 modules indépendants.
> Chaque module = 1 session Claude Code séparée.
> Ordre d'exécution : Module 1 → 2 → 3 → 4.

---

## CONTEXTE GLOBAL (à coller en début de chaque session)

```
Tu travailles sur TNK Adaptive, un bot de paper trading Python.
Stack : Flask, ccxt, SQLite, pandas.
Le bot est en production et tourne actuellement.
NE PAS modifier : paper_broker.py, adaptive.py, database.py, api.py, index.html.
Fais des changements chirurgicaux, teste chaque modification.
```

---

## MODULE 1 — Dépendances & Configuration
**Modèle recommandé : claude-haiku** (tâche simple, peu de contexte)
**Fichiers touchés : requirements.txt, config.py**

```
CONTEXTE : Bot de trading Python avec ccxt, Flask, pandas, SQLite.

TÂCHE : Préparer les dépendances pour les WebSockets Bybit.

1. Dans requirements.txt, ajoute :
   pybit>=5.6.0
   
   pybit est le SDK officiel Bybit qui supporte
   les WebSockets V5 nativement.

2. Dans config.py, ajoute cette section
   sous le commentaire # ── WebSocket ── :

   # ── WebSocket ──────────────────────────────────────────
   USE_WEBSOCKET    = True     # False = retour au polling
   WS_PING_INTERVAL = 20       # secondes entre pings keepalive
   WS_RECONNECT_DELAY = 5      # secondes avant reconnexion auto
   
   # Timeframes disponibles pour les signaux
   # Le bot utilise SIGNAL_TIMEFRAME pour calculer les indicateurs
   # Le WS stream le ticker en temps réel (indépendant du timeframe)
   SIGNAL_TIMEFRAME = '15'     # minutes : 1, 3, 5, 15, 30, 60, 240
   
   # Seuil de déclenchement du check signal
   # Vérifie les signaux dès qu'une bougie SIGNAL_TIMEFRAME se ferme
   CHECK_ON_CANDLE_CLOSE = True

3. Dans requirements.txt, vérifie que ces packages
   sont déjà présents (ne pas dupliquer) :
   ccxt, pandas, flask, flask-cors, flask-limiter

4. Lance : pip install pybit
   et vérifie qu'il n'y a pas de conflit avec ccxt.

LIVRABLE : requirements.txt et config.py mis à jour.
```

---

## MODULE 2 — WebSocket Manager
**Modèle recommandé : claude-sonnet** (nouveau fichier complexe)
**Fichiers touchés : ws_manager.py (nouveau)**

```
CONTEXTE : Bot de trading Python. Tu crées un nouveau fichier
ws_manager.py qui gère les connexions WebSocket Bybit V5.

NE PAS modifier les fichiers existants dans cette session.

TÂCHE : Créer ws_manager.py avec cette architecture :

━━━ CLASSE WebSocketManager ━━━

Attributs :
  _instance       : singleton (une seule connexion WS)
  _prices         : dict {symbol: float} — prix temps réel
  _candles        : dict {symbol: list} — dernières 220 bougies
  _callbacks      : list — fonctions appelées à chaque bougie fermée
  _ws_linear      : connexion WebSocket futures/perp
  _ws_spot        : connexion WebSocket spot
  _running        : bool
  _lock           : threading.Lock

━━━ MÉTHODES ━━━

__init__(self, symbols: list[str], timeframe: str = '15'):
  Initialise les dicts, lance les connexions dans des threads daemon.

start(self, symbols: list[str]):
  Sépare les symboles en spot / linear (comme symbol_manager.py).
  Lance _connect_linear(linear_syms) et _connect_spot(spot_syms)
  dans des threads séparés.

_connect_linear(self, symbols):
  Utilise pybit.unified_trading.WebSocket avec channel_type='linear'.
  Subscribe au topic : 'kline.{timeframe}.{symbol}'
  Handler : _on_kline_linear

_connect_spot(self, symbols):
  Même chose avec channel_type='spot'.
  Handler : _on_kline_spot

_on_kline_linear(self, msg) et _on_kline_spot(self, msg):
  Parsent le message Bybit V5 WebSocket.
  Format du message kline Bybit :
  {
    "topic": "kline.15.BTCUSDT",
    "data": [{
      "start": 1234567890000,  # timestamp ms
      "end": 1234567890000,
      "interval": "15",
      "open": "50000",
      "close": "50100",
      "high": "50200",
      "low": "49900",
      "volume": "100",
      "confirm": true/false  # true = bougie fermée
    }]
  }
  
  À chaque message :
  1. Met à jour _prices[symbol] = float(close)
  2. Si confirm == True (bougie fermée) :
     - Ajoute la bougie à _candles[symbol]
     - Garde max 220 bougies (pop le plus ancien)
     - Appelle tous les _callbacks avec (symbol, candles)

  Gestion d'erreur : log WARNING si parsing échoue, 
  ne jamais lever d'exception (le WS doit rester connecté)

register_callback(self, fn):
  Ajoute fn à _callbacks.
  fn sera appelée avec (symbol: str, candles: list[dict])

get_price(self, symbol: str) -> float | None:
  Retourne _prices.get(symbol)

get_candles(self, symbol: str) -> list[dict] | None:
  Retourne _candles.get(symbol)

is_ready(self, symbol: str) -> bool:
  Retourne True si len(_candles.get(symbol, [])) >= 50

stop(self):
  _running = False, ferme les connexions WS proprement.

━━━ SINGLETON ━━━

_ws_manager_instance = None

def get_ws_manager() -> WebSocketManager | None:
    return _ws_manager_instance

def init_ws_manager(symbols, timeframe) -> WebSocketManager:
    global _ws_manager_instance
    _ws_manager_instance = WebSocketManager(symbols, timeframe)
    return _ws_manager_instance

━━━ FORMAT CANDLES ━━━

Les bougies dans _candles doivent être des dicts pandas-compatibles :
{
  'timestamp': int,   # ms
  'open': float,
  'high': float,
  'low': float,
  'close': float,
  'volume': float
}

━━━ LOGGING ━━━

log = logging.getLogger('websocket')
Préfixe tous les logs avec [WS] pour filtrer facilement.

LIVRABLE : ws_manager.py complet, standalone, importable.
```

---

## MODULE 3 — Refonte market_data.py
**Modèle recommandé : claude-sonnet** (refonte d'un fichier existant)
**Fichiers touchés : market_data.py**

```
CONTEXTE : Bot de trading Python.
Le fichier market_data.py gère actuellement le fetch OHLCV
via ccxt (polling). Tu vas l'adapter pour supporter
les deux modes : WebSocket (temps réel) ET polling (fallback).

Lis d'abord market_data.py en entier avant de modifier.

TÂCHE : Modifier market_data.py pour supporter les deux modes.

━━━ PRINCIPE ━━━

Si USE_WEBSOCKET=True ET ws_manager est prêt pour ce symbole :
  → Utilise les candles du ws_manager (temps réel)
Sinon :
  → Fallback sur ccxt fetch_ohlcv (comportement actuel)

━━━ MODIFICATIONS ━━━

1. Ajoute en haut du fichier :
   from config import USE_WEBSOCKET
   
   try:
       from ws_manager import get_ws_manager
   except ImportError:
       get_ws_manager = lambda: None

2. Modifie fetch_ohlcv(symbol, limit=220) :

   def fetch_ohlcv(symbol: str, limit: int = 220) -> pd.DataFrame | None:
     # Mode WebSocket
     if USE_WEBSOCKET:
         ws = get_ws_manager()
         if ws and ws.is_ready(symbol):
             candles = ws.get_candles(symbol)
             if candles and len(candles) >= 30:
                 df = pd.DataFrame(candles)
                 df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                 df = df.set_index('timestamp')
                 return df
     
     # Fallback polling ccxt (code existant, ne pas modifier)
     try:
         raw = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=limit)
         ...  # code existant inchangé

3. Ajoute une fonction pour convertir le timeframe config
   en format ccxt et Bybit WS :
   
   def get_timeframe_str() -> str:
     # SIGNAL_TIMEFRAME '15' → ccxt '15m', Bybit WS '15'
     from config import SIGNAL_TIMEFRAME
     mapping = {
       '1': '1m', '3': '3m', '5': '5m',
       '15': '15m', '30': '30m', '60': '1h',
       '240': '4h', '1440': '1d'
     }
     return mapping.get(str(SIGNAL_TIMEFRAME), '15m')

4. Dans calculate_indicators, calculate_atr, get_signal,
   should_exit : AUCUN changement — ils travaillent sur
   un DataFrame pandas, indépendant de la source des données.

━━━ IMPORTANT ━━━

Le fallback doit être transparent — si le WS est down
ou pas encore prêt, le bot continue à fonctionner
exactement comme avant. Zéro interruption.

LIVRABLE : market_data.py modifié avec mode dual WS/polling.
```

---

## MODULE 4 — Refonte main.py
**Modèle recommandé : claude-sonnet** (orchestration complexe)
**Fichiers touchés : main.py**

```
CONTEXTE : Bot de trading Python.
Tu vas modifier main.py pour intégrer les WebSockets
tout en gardant le fallback polling.

Lis d'abord main.py en entier avant de modifier.

TÂCHE : Intégrer ws_manager dans la boucle principale.

━━━ NOUVELLE ARCHITECTURE ━━━

Mode WebSocket actif (USE_WEBSOCKET=True) :
  - Au démarrage : init_ws_manager(symbols, SIGNAL_TIMEFRAME)
  - ws_manager.register_callback(on_candle_close)
  - La boucle principale tourne toujours mais sert de :
    * Heartbeat (log toutes les 60s)
    * Refresh liste symboles (toutes les 60min)
    * Fallback pour les symboles pas encore dans le WS
  - on_candle_close() remplace process_symbol() pour les
    symboles avec données WS

Mode polling (USE_WEBSOCKET=False) :
  - Comportement actuel inchangé

━━━ FONCTION on_candle_close ━━━

def on_candle_close(symbol: str, candles: list):
  """
  Appelée par ws_manager à chaque bougie fermée.
  Remplace process_symbol() pour les symboles WS.
  """
  try:
    price = broker.positions.get(symbol, {}).get('current_price')
    if not price:
        price = ws_manager.get_price(symbol)
    if not price:
        return
    
    params = get_params(symbol)
    
    # Récupère le DataFrame depuis ws_manager
    from market_data import fetch_ohlcv, calculate_indicators
    df = fetch_ohlcv(symbol)
    if df is None:
        return
    df = calculate_indicators(df, params)
    
    # Même logique que process_symbol() :
    # 1. Check SL/TP
    # 2. Check exit signal
    # 3. Check entry signal
    # (copie la logique existante de process_symbol)
    
    update_state(broker, ws_manager._prices, signals)
    
  except Exception as e:
    log.error(f'[on_candle_close] {symbol}: {e}')

━━━ MODIFICATIONS main() ━━━

1. Après init_db() et création du broker, ajoute :

   if USE_WEBSOCKET:
       from ws_manager import init_ws_manager
       from symbol_manager import get_active_symbols
       symbols = get_active_symbols()
       ws = init_ws_manager(symbols, str(SIGNAL_TIMEFRAME))
       ws.register_callback(on_candle_close)
       log.info(f'[WS] WebSocket initialisé sur {len(symbols)} paires')

2. Dans la boucle while True, si USE_WEBSOCKET=True :
   - Saute le process_symbol() pour les symboles is_ready()
   - Garde process_symbol() uniquement pour les symboles
     pas encore couverts par le WS (warmup period)
   - Réduis LOOP_INTERVAL à 5 secondes (juste pour le heartbeat)

3. Ajoute un log de statut WS toutes les 60s :
   ws_ready = sum(1 for s in symbols if ws.is_ready(s))
   log.info(f'[WS] {ws_ready}/{len(symbols)} paires connectées')

━━━ GESTION ERREURS ━━━

Si ws_manager plante : log ERROR + fallback polling automatique
Ne jamais crasher le bot à cause du WebSocket.

LIVRABLE : main.py avec intégration WebSocket dual-mode.
```

---

## ORDRE D'EXÉCUTION

```
Session 1 (Haiku)  → Module 1 : config + requirements
Session 2 (Sonnet) → Module 2 : ws_manager.py (nouveau fichier)
Session 3 (Sonnet) → Module 3 : market_data.py (adapter)
Session 4 (Sonnet) → Module 4 : main.py (orchestration)
```

## TEST FINAL

Après les 4 modules, dans les logs tu dois voir :
```
[WS] WebSocket initialisé sur 50 paires
[WS] 50/50 paires connectées
[WS] BTCUSDT — bougie 15m fermée → signal check
```

Et le dashboard se met à jour en temps réel sans attendre
le cycle de 60 secondes.

## ROLLBACK

Si quelque chose casse, dans config.py :
```python
USE_WEBSOCKET = False
```
Le bot repasse en mode polling immédiatement.
