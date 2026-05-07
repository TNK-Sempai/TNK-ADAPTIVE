# ═══════════════════════════════════════════════════════════
#  api.py — Endpoints pour le dashboard multi-paires
# ═══════════════════════════════════════════════════════════

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app  = Flask(__name__)
CORS(app)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per minute"],
    storage_uri="memory://"
)

# État partagé
_broker  = None
_prices  = {}
_signals = {}

def update_state(broker, prices, signals):
    global _broker, _prices, _signals
    _broker  = broker
    _prices  = prices
    _signals = signals

@app.before_request
def exempt_localhost():
    from flask import request
    if request.remote_addr in ('127.0.0.1', '::1'):
        return None

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        'error': 'Too many requests',
        'retry_after': e.description
    }), 429

@app.route('/api/stats')
@limiter.limit("30 per minute")
def stats():
    if _broker is None:
        return jsonify({'error': 'Bot non démarré'}), 503
    return jsonify(_broker.get_stats(_prices))

@app.route('/api/positions')
@limiter.limit("30 per minute")
def positions():
    if _broker is None:
        return jsonify([])
    return jsonify(_broker.get_positions_snapshot(_prices))

@app.route('/api/trades')
@limiter.limit("10 per minute")
def trades():
    from database import get_all_trades
    return jsonify(get_all_trades(200))

@app.route('/api/signals')
@limiter.limit("30 per minute")
def signals():
    return jsonify(_signals)

@app.route('/api/params')
@limiter.limit("10 per minute")
def params():
    from database import get_all_symbol_params
    return jsonify(get_all_symbol_params())

@app.route('/api/adapt_log')
@limiter.limit("10 per minute")
def adapt_log():
    from database import get_adapt_log
    return jsonify(get_adapt_log(50))

@app.route('/api/cooldowns')
@limiter.limit("30 per minute")
def cooldowns():
    from database import get_active_cooldowns
    return jsonify(get_active_cooldowns())

@app.route('/api/prices')
@limiter.limit("30 per minute")
def prices():
    return jsonify(_prices)

@app.route('/api/health')
@limiter.limit("30 per minute")
def health():
    return jsonify({'status': 'ok', 'symbols': len(_prices)})

@app.route('/api/close/<path:symbol>', methods=['POST'])
@limiter.limit("10 per minute")
def force_close(symbol):
    from urllib.parse import unquote
    from database import save_trade
    from adaptive import on_trade_closed
    import ccxt
    sym = unquote(symbol)
    if _broker is None:
        return jsonify({'error': 'Bot non démarré'}), 503

    price = _prices.get(sym)
    if not price:
        try:
            exchange = ccxt.bybit({'enableRateLimit': True})
            ticker = exchange.fetch_ticker(sym)
            price = float(ticker['last'])
        except Exception:
            pos = _broker.positions.get(sym)
            if pos:
                price = pos['entry_price']
            else:
                return jsonify({'error': 'Position introuvable'}), 404

    closed = _broker.close_position(sym, price, 'manual')
    if not closed:
        return jsonify({'error': 'Position introuvable'}), 404
    save_trade(closed)
    on_trade_closed(closed)
    return jsonify(closed)

@app.route('/api/add/<path:symbol>', methods=['POST'])
@limiter.limit("10 per minute")
def add_to_position(symbol):
    from urllib.parse import unquote
    sym   = unquote(symbol)
    if _broker is None:
        return jsonify({'error': 'Bot non démarré'}), 503
    body  = request.get_json(silent=True) or {}
    extra = float(body.get('usdt', 5.0))
    price = _prices.get(sym)
    if not price:
        return jsonify({'error': 'Prix introuvable'}), 404
    updated = _broker.add_to_position(sym, price, extra)
    if not updated:
        return jsonify({'error': 'Position introuvable'}), 404
    return jsonify(updated)

@app.route('/proxy/kline')
@limiter.limit("60 per minute")
def proxy_kline():
    from flask import request
    import requests as req
    params = request.args.to_dict()
    r = req.get('https://api.bybit.com/v5/market/kline', params=params, timeout=10)
    return jsonify(r.json())

@app.route('/')
def serve_dashboard():
    from flask import send_from_directory
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    from flask import send_from_directory
    return send_from_directory('.', filename)

def start_api(port: int = 5000):
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
