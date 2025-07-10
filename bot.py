from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP
import requests
import config

app = Flask(__name__)

session = HTTP(
    api_key=config.API_KEY,
    api_secret=config.API_SECRET,
    testnet=config.TESTNET
)

def send_to_discord(message):
    data = {"content": message}
    requests.post(config.DISCORD_WEBHOOK_URL, json=data)

def calculate_qty(symbol):
    try:
        balance_info = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next(c for c in balance_info if c["coin"] == "USDT")
        available_usdt = float(usdt["availableToTrade"])
        trade_usdt = available_usdt * 0.5
        price_info = session.get_ticker(symbol=symbol)["result"]
        last_price = float(price_info["lastPrice"])
        qty = round(trade_usdt / last_price, 3)
        return qty
    except Exception as e:
        send_to_discord(f"⚠️ Błąd obliczania ilości: {e}")
        return None

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    action = data.get("action")
    if action in ["buy", "sell"]:
        side = "Buy" if action == "buy" else "Sell"
        qty = calculate_qty(config.SYMBOL)
        if qty is None:
            return jsonify({"error": "Nie udało się obliczyć ilości"}), 400
        try:
            order = session.place_order(
                category="linear",
                symbol=config.SYMBOL,
                side=side,
                order_type="Market",
                qty=qty,
                time_in_force="GoodTillCancel"
            )
            send_to_discord(f"✅ {side.upper()} zlecenie złożone: {qty} {config.SYMBOL}")
            return jsonify(order)
        except Exception as e:
            send_to_discord(f"❌ Błąd składania zlecenia: {e}")
            return jsonify({"error": str(e)}), 500
    else:
        send_to_discord("⚠️ Odebrano nieznaną akcję.")
        return jsonify({"error": "Nieznana akcja"}), 400

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)