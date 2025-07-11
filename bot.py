from flask import Flask, request
from pybit.unified_trading import HTTP
import requests
from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET

app = Flask(__name__)

# 🔧 Inicjalizacja sesji bez błędnego argumentu "base_url"
session = HTTP(
    api_key=API_KEY,
    api_secret=API_SECRET,
    testnet=TESTNET
)

# 🔔 Wysyłanie wiadomości na Discorda
def send_to_discord(message):
    try:
        payload = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"❌ Błąd wysyłania do Discord: {e}")

# 🔢 Oblicz ilość kontraktów do otwarcia (50% dostępnego salda USDT)
def calculate_qty(symbol):
    try:
        send_to_discord("🔍 Rozpoczynam obliczanie ilości...")

        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        balance_info = balance_data["result"]["list"][0]["coin"]
        usdt = next(c for c in balance_info if c["coin"] == "USDT")
        available_usdt = float(usdt.get("walletBalance", 0))
        trade_usdt = available_usdt * 0.5

        tickers_data = session.get_tickers(category="linear")
        price_info = next((item for item in tickers_data["result"]["list"] if item["symbol"] == symbol), None)

        if not price_info:
            send_to_discord(f"⚠️ Symbol {symbol} nie został znaleziony w tickers.")
            return None

        last_price = float(price_info["lastPrice"])
        qty = int(trade_usdt / last_price)

        if qty < 1:
            send_to_discord(f"⚠️ Obliczona ilość to {qty}. Za mało USDT do zakupu choćby 1 kontraktu.")
            return None

        send_to_discord(f"✅ Obliczona ilość: {qty} {symbol} przy cenie {last_price} USDT")
        return qty

    except Exception as e:
        send_to_discord(f"⚠️ Błąd obliczania ilości: {e}")
        return None

# 🔄 Webhook — reaguje na sygnały "buy" lub "sell"
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    action = data.get("action", "").lower()

    if action not in ["buy", "sell"]:
        send_to_discord("⚠️ Nieprawidłowe polecenie. Użyj 'buy' lub 'sell'.")
        return "Invalid action", 400

    qty = calculate_qty(SYMBOL)
    if qty is None:
        return "Qty error", 400

    try:
        # 🔒 Najpierw zamknij przeciwną pozycję
        opposite_side = "Sell" if action == "buy" else "Buy"
        session.place_order(
            category="linear",
            symbol=SYMBOL,
            side=opposite_side,
            orderType="Market",
            qty=qty,
            reduceOnly=True,
            timeInForce="GoodTillCancel"
        )
        send_to_discord(f"🔒 Zamknięcie pozycji {opposite_side.upper()}")

        # ✅ Następnie otwórz nową pozycję w odpowiednim kierunku
        side = "Buy" if action == "buy" else "Sell"
        session.place_order(
            category="linear",
            symbol=SYMBOL,
            side=side,
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel"
        )
        send_to_discord(f"✅ {side.upper()} zlecenie złożone: {qty} {SYMBOL}")
        return "OK", 200

    except Exception as e:
        send_to_discord(f"❌ Błąd składania zlecenia: {e}")
        return "Order error", 500

# 🔧 Uruchomienie aplikacji Flask
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

