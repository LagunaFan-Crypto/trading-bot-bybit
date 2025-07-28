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

processing = False
last_alert_time = 0
ALERT_COOLDOWN = 5  # sekundy

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
    global processing, last_alert_time

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        send_to_discord("⏳ Odrzucono alert — za szybko po poprzednim.")
        return "Too soon", 429

    if processing:
        send_to_discord("⏳ Bot już przetwarza poprzedni alert. Pomijam.")
        return "Processing in progress", 429

    processing = True
    last_alert_time = current_time

    try:
        data = request.get_json()
        print(f"🔔 Otrzymano webhook: {data}")
        action = data.get("action", "").lower()

        if action not in ["buy", "sell"]:
            send_to_discord(f"⚠️ Nieprawidłowe polecenie: '{action}'. Użyj 'buy' lub 'sell'.")
            processing = False
            return "Invalid action", 400

        position_size, position_side = get_current_position(SYMBOL)

        # Odwracamy stronę działania z alertu do zamknięcia aktualnej pozycji
        if position_size > 0:
            close_side = "Sell" if position_side == "Buy" else "Buy"
            if (action == "buy" and position_side == "Sell") or (action == "sell" and position_side == "Buy"):
                try:
                    session.place_order(
                        category="linear",
                        symbol=SYMBOL,
                        side=close_side,
                        orderType="Market",
                        qty=position_size,
                        reduceOnly=True,
                        timeInForce="GoodTillCancel"
                    )
                    send_to_discord(f"🔒 Zamknięcie pozycji {position_side.upper()} ({position_size} {SYMBOL})")
                except Exception as e:
                    send_to_discord(f"⚠️ Błąd zamykania pozycji: {e}")

                time.sleep(3)
                position_size, position_side = get_current_position(SYMBOL)

        # Składamy nowe zlecenie jeśli nie ma aktywnej pozycji
        if position_size < 0.0001:
            qty = calculate_qty(SYMBOL)
            if qty is None or qty == 0:
                send_to_discord("⚠️ Ilość nieprawidłowa, przerywam operację.")
                processing = False
                return "Invalid qty", 400

            order_side = "Buy" if action == "buy" else "Sell"
            try:
                session.place_order(
                    category="linear",
                    symbol=SYMBOL,
                    side=order_side,
                    orderType="Market",
                    qty=qty,
                    timeInForce="GoodTillCancel"
                )
                send_to_discord(f"✅ Zlecenie {order_side.upper()} złożone: {qty} {SYMBOL}")
            except Exception as e:
                send_to_discord(f"❌ Błąd składania nowego zlecenia: {e}")

        processing = False
        return "OK", 200

    except Exception as e:
        send_to_discord(f"❌ Błąd składania zlecenia: {e}")
        print(f"❌ Błąd: {e}")
        processing = False
        return "Order error", 500

if __name__ == "__main__":
    print("Bot uruchomiony...")
    app.run(host="0.0.0.0", port=port)
