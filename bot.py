import os
import time
import requests
from flask import Flask, request
from pybit.unified_trading import HTTP
from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET

app = Flask(__name__)
port = int(os.environ.get("PORT", 5000))

session = HTTP(
    api_key=API_KEY,
    api_secret=API_SECRET,
    testnet=TESTNET
)

def send_to_discord(message):
    try:
        payload = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"❌ Błąd wysyłania do Discord: {e}")

def get_current_position(symbol):
    try:
        result = session.get_positions(category="linear", symbol=symbol)
        position = result["result"]["list"][0]
        size = float(position["size"])
        side = position["side"]
        print(f"🔄 Pozycja: {side} o rozmiarze {size}")

        if size < 0.0001:
            send_to_discord(f"⚠️ Pozycja {side} jest zbyt mała, aby ją zamknąć.")
            return 0.0, "None"

        return size, side
    except Exception as e:
        send_to_discord(f"⚠️ Błąd pobierania pozycji: {e}")
        return 0.0, "None"

def calculate_qty(symbol):
    try:
        send_to_discord("🔍 Rozpoczynam obliczanie ilości...")

        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        balance_info = balance_data["result"]["list"][0]["coin"]
        usdt = next(c for c in balance_info if c["coin"] == "USDT")
        available_usdt = float(usdt.get("walletBalance", 0))
        trade_usdt = available_usdt * 1

        tickers_data = session.get_tickers(category="linear")
        price_info = next((item for item in tickers_data["result"]["list"] if item["symbol"] == symbol), None)

        if not price_info:
            send_to_discord(f"⚠️ Symbol {symbol} nie został znaleziony.")
            return None

        last_price = float(price_info["lastPrice"])
        qty = int(trade_usdt / last_price)

        send_to_discord(f"✅ Obliczona ilość: {qty} {symbol} przy cenie {last_price} USDT")
        return qty
    except Exception as e:
        send_to_discord(f"⚠️ Błąd obliczania ilości: {e}")
        return None

@app.route("/", methods=["GET"])
def index():
    return "✅ Bot działa!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        print(f"🔔 Otrzymano webhook: {data}")
        action = data.get("action", "").lower()

        if action not in ["buy", "sell"]:
            send_to_discord("⚠️ Nieprawidłowe polecenie. Użyj 'buy' lub 'sell'.")
            return "Invalid action", 400

        position_size, position_side = get_current_position(SYMBOL)

        if position_size > 0 and (
            (position_side == "Buy" and action == "sell") or
            (position_side == "Sell" and action == "buy")
        ):
            close_side = "Sell" if position_side == "Buy" else "Buy"
            close_order = session.place_order(
                category="linear",
                symbol=SYMBOL,
                side=close_side,
                orderType="Market",
                qty=position_size,
                reduceOnly=True,
                timeInForce="GoodTillCancel"
            )
            send_to_discord(f"🔒 Zamknięcie pozycji {position_side.upper()} ({position_size} {SYMBOL})")

            time.sleep(1.5)
            position_size, position_side = get_current_position(SYMBOL)

            if position_size > 0:
                send_to_discord("⚠️ Pozycja nadal otwarta po próbie zamknięcia. Przerywam operację.")
                return "Pozycja nie została zamknięta", 400

        if position_size == 0:
            qty = calculate_qty(SYMBOL)
            if qty is None or qty == 0:
                send_to_discord("⚠️ Ilość nieprawidłowa, przerywam operację.")
                return "Invalid qty", 400

            order_side = "Buy" if action == "buy" else "Sell"
            new_order = session.place_order(
                category="linear",
                symbol=SYMBOL,
                side=order_side,
                orderType="Market",
                qty=qty,
                timeInForce="GoodTillCancel"
            )
            send_to_discord(f"✅ Zlecenie {order_side.upper()} złożone: {qty} {SYMBOL}")
        else:
            send_to_discord(f"⚠️ Pozycja już otwarta w odpowiednim kierunku ({position_side.upper()}), nie składam nowego zlecenia.")

        return "OK", 200

    except Exception as e:
        send_to_discord(f"❌ Błąd składania zlecenia: {e}")
        print(f"❌ Błąd: {e}")
        return "Order error", 500

if __name__ == "__main__":
    print("Bot uruchomiony...")
    app.run(host="0.0.0.0", port=port)
