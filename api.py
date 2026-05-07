# ═══════════════════════════════════════════════════════════
#  api.py — Endpoints pour le dashboard multi-paires
# ═══════════════════════════════════════════════════════════

from flask import Flask, jsonify
from flask_cors import CORS

app  = Flask(__name__)
CORS(app)

# État partagé
_broker  = None
_prices  = {}
_signals = {}

def update_state(broker, prices, signals):
    global _broker, _prices, _signals
    _broker  = broker
    _prices  = prices
    _signals = signals

@app.route('/api/stats')
def stats():
    if _broker is None:
        return jsonify({'error': 'Bot non démarré'}), 503
    return jsonify(_broker.get_stats(_prices))

@app.route('/api/positions')
def positions():
    if _broker is None:
        return jsonify([])
    return jsonify(_broker.get_positions_snapshot(_prices))

@app.route('/api/trades')
def trades():
    from database import get_all_trades
    return jsonify(get_all_trades(200))

@app.route('/api/signals')
def signals():
    return jsonify(_signals)

@app.route('/api/params')
def params():
    from database import get_all_symbol_params
    return jsonify(get_all_symbol_params())

@app.route('/api/adapt_log')
def adapt_log():
    from database import get_adapt_log
    return jsonify(get_adapt_log(50))

@app.route('/api/prices')
def prices():
    return jsonify(_prices)

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'symbols': len(_prices)})

@app.route('/proxy/kline')
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
