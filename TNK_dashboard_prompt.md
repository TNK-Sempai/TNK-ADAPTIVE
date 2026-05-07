# TNK ADAPTIVE — Dashboard Prompt pour Claude Code

## Contexte du projet

Tu travailles sur **TNK Adaptive**, un bot de paper trading multi-paires développé sous la marque **Tanuki Corporation**. Le bot tourne en Python (Flask API sur `localhost:5000`) et trade des paires USDT sur Bybit en temps réel avec un moteur d'apprentissage adaptatif.

Le fichier `dashboard/index.html` actuel est fonctionnel mais basique. Ta mission : le réécrire complètement en un seul fichier HTML/CSS/JS magistral.

---

## Design System Tanuki Corporation

```
Couleurs :
  --bg:       #080808   (fond principal)
  --panel:    #0e0e0e   (panneaux)
  --panel2:   #111111   (panneaux secondaires)
  --border:   #1a1a1a   (bordures)
  --border2:  #262626   (bordures secondaires)
  --lime:     #c8f060   (accent principal — LIME GREEN)
  --text:     #cccccc   (texte principal)
  --muted:    #555555   (texte secondaire)
  --green:    #3ddc84   (PnL positif, long)
  --red:      #ff4f4f   (PnL négatif, short, SL)
  --orange:   #ff8c42   (warnings, SL atteint)
  --blue:     #5b9cf6   (adaptations, info)

Typographie :
  Display     : Bebas Neue (Google Fonts) — titres, KPIs, labels majeurs
  Monospace   : JetBrains Mono (Google Fonts) — données, prix, code
  Corps       : DM Sans (Google Fonts) — texte courant, descriptions

Style général :
  - Fond très sombre proche du noir
  - Accent lime vert fluo sur les éléments clés
  - Grain overlay subtil via SVG filter
  - Bordures fines 1px sur les panneaux
  - Pas de border-radius ou très léger (2px max)
  - Typographie monospace pour toutes les données numériques
```

---

## API Backend (Flask sur localhost:5000)

```
GET /api/stats       → KPIs globaux du portfolio
GET /api/positions   → Positions ouvertes avec PnL temps réel
GET /api/signals     → Signaux détectés ce cycle
GET /api/trades      → Historique des trades (200 derniers)
GET /api/adapt_log   → Journal des adaptations du bot
GET /api/params      → Paramètres adaptatifs par symbole
GET /api/prices      → Prix courants de toutes les paires suivies
```

### Réponse /api/stats
```json
{
  "initial_balance": 200.0,
  "cash": 180.5,
  "equity": 203.2,
  "total_pnl": 3.2,
  "unrealized_pnl": 1.5,
  "return_pct": 1.6,
  "win_rate": 62.5,
  "total_trades": 16,
  "wins": 10,
  "losses": 6,
  "open_positions": 3,
  "max_drawdown_pct": 2.1
}
```

### Réponse /api/positions (array)
```json
[{
  "symbol": "BTC/USDT:USDT",
  "type": "long",
  "entry_price": 94200.0,
  "current_price": 94850.0,
  "size_usdt": 10.0,
  "size_tokens": 0.000106,
  "stop_loss": 91374.0,
  "take_profit": 99852.0,
  "entry_time": 1746648000.0,
  "unrealized_pnl": 0.069,
  "params_snap": { "rsi_oversold": 35, "rsi_overbought": 65, "stop_loss_pct": 0.03, "take_profit_pct": 0.06 }
}]
```

### Réponse /api/trades (array)
```json
[{
  "id": 42,
  "symbol": "SOL/USDT",
  "type": "long",
  "entry_price": 148.2,
  "exit_price": 157.1,
  "size_usdt": 10.0,
  "pnl": 0.6,
  "pnl_pct": 6.01,
  "entry_time": 1746640000.0,
  "exit_time": 1746648000.0,
  "reason": "take_profit",
  "win": 1,
  "params_snap": "{}"
}]
```

### Réponse /api/adapt_log (array)
```json
[{
  "id": 3,
  "symbol": "BTC/USDT",
  "timestamp": 1746640000.0,
  "win_rate": 0.4,
  "avg_pnl": -0.12,
  "sl_hit_pct": 0.7,
  "changes": "{\"stop_loss_pct\": {\"from\": 0.03, \"to\": 0.035}}"
}]
```

### Réponse /api/params (array)
```json
[{
  "symbol": "BTC/USDT",
  "rsi_period": 14,
  "rsi_oversold": 33,
  "rsi_overbought": 67,
  "ma_fast": 7,
  "ma_slow": 25,
  "stop_loss_pct": 0.035,
  "take_profit_pct": 0.07,
  "trades_since_adapt": 4,
  "total_adaptations": 2,
  "last_adapt_reason": "win_rate faible (40%) → RSI plus restrictif"
}]
```

---

## Fonctionnalités requises

### 1. Graphiques en chandelles (OBLIGATOIRE)
Utilise la bibliothèque **Lightweight Charts de TradingView** (CDN gratuit) :
```html
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
```

Pour chaque position ouverte, affiche :
- Un chart en chandelles **1h** fetchant les données depuis l'API publique Bybit (sans clé API)
- URL : `https://api.bybit.com/v5/market/kline?category=linear&symbol={SYMBOL_CLEAN}&interval=60&limit=100`
  - `SYMBOL_CLEAN` = supprimer le `/` et `:USDT` → `BTC/USDT:USDT` → `BTCUSDT`
- Ligne horizontale **SL** en rouge sur le chart
- Ligne horizontale **TP** en vert sur le chart
- Ligne horizontale **Entry** en lime sur le chart
- Mise à jour du dernier prix toutes les 10s via le même endpoint

### 2. Navigation par onglets
- **Overview** — KPIs + positions ouvertes + derniers trades
- **Charts** — Un chart par position ouverte (grille responsive)
- **Trades** — Historique complet avec filtres (win/loss, symbole)
- **Adaptations** — Journal des apprentissages du bot
- **Paramètres** — Tableau des params adaptatifs par symbole

### 3. Animations & micro-interactions
- **Entrée de page** : staggered reveal (opacity + translateY) sur les KPI cards
- **Mise à jour des chiffres** : flash lime bref quand une valeur change
- **Nouvelles positions** : animation slide-in depuis la droite
- **PnL en direct** : couleur qui pulse doucement (green/red) selon profit/perte
- **Header** : prix qui clignote brièvement au refresh
- **Grain overlay** animé très subtil
- **Hover sur les cards** : légère élévation (box-shadow lime tenue)
- **Indicateur live** : dot vert animé en header

### 4. KPI Cards (row en haut)
```
[ Equity USDT ]  [ PnL Réalisé ]  [ Win Rate + barre ]  [ Trades W/L ]  [ Positions / DD ]
```
- Valeurs en Bebas Neue grand format
- Flash animation sur update
- Barre de win rate animée

### 5. Position Cards (overview + charts)
Chaque position = une card avec :
- Symbole en grand (Bebas Neue)
- Badge LONG (vert) ou SHORT (rouge)
- Barre de progression entre SL et TP avec curseur sur le prix actuel
- PnL non réalisé en temps réel (couleur dynamique)
- Durée depuis l'entrée (timer live)
- Le chart Lightweight Charts intégré dans la card (onglet Charts)

### 6. Tableau trades
- Colonnes : #, Symbole, Type, Entrée, Sortie, Taille, PnL, %, Raison, Durée, Date
- Filtres : All / Win / Loss / Long / Short
- Ligne colorée à gauche selon win (vert) ou loss (rouge)
- Animation d'ajout de nouvelle ligne en haut

### 7. Refresh intelligent
- Stats + positions + signaux : **toutes les 15 secondes**
- Prix des charts : **toutes les 10 secondes**
- Pas de full reload — mise à jour DOM ciblée uniquement

---

## Contraintes techniques

- **Fichier unique** : tout en `dashboard/index.html` (HTML + CSS + JS inline)
- **Zéro framework JS** : vanilla JS uniquement (pas de React, Vue, etc.)
- **Zéro dépendance** sauf :
  - Google Fonts (Bebas Neue, JetBrains Mono, DM Sans)
  - Lightweight Charts TradingView (CDN)
- **CORS** : Flask a flask-cors activé, appels directs depuis le HTML OK
- **Gestion d'erreur** : si l'API est offline, afficher un état dégradé propre (pas de crash)
- **Responsive** : fonctionne de 1200px à 1920px minimum

---

## Ambiance visuelle cible

**Retro-futuriste éditorial sombre.** Pense Bloomberg Terminal rencontrant un zine underground Tokyo. Données denses mais lisibles. Chaque pixel justifié. Rien de gratuit, rien de manquant.

Ce dashboard sera streamé en live — il doit être **visuellement impressionnant** et **informationnellement dense**. Quelqu'un qui regarde le stream sans connaître le code doit sentir que c'est une machine sérieuse qui tourne.

Les animations doivent renforcer la sensation que **c'est vivant** — le bot respire, les prix bougent, les chiffres pulsent.

---

## Fichiers à lire avant de coder

Le dashboard remplace uniquement `dashboard/index.html`. Les fichiers Python ne changent pas.

Lis d'abord :
- `api.py` — pour comprendre exactement ce que retourne chaque endpoint
- `paper_broker.py` — pour comprendre la structure des positions
- `config.py` — pour les constantes (INITIAL_BALANCE, etc.)

---

## Output attendu

Un seul fichier : `dashboard/index.html`

Commence par définir l'architecture CSS (variables, layout, composants) avant d'attaquer le JS. Le JS doit être organisé en modules clairs :
- `fetchAll()` — récupère toutes les données
- `renderKPIs()` — met à jour les KPI cards
- `renderPositions()` — positions + timers
- `renderCharts()` — init et update Lightweight Charts
- `renderTrades()` — tableau avec filtres
- `renderAdapt()` — journal adaptations
- `renderParams()` — tableau paramètres
- `startLoop()` — boucles de refresh séparées
