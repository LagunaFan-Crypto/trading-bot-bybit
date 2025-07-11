from flask import Flask, request
from pybit.unified_trading import HTTP
import requests
from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET

app = Flask(__name__)

# Ustawienie endpointa
base_url = "https://api-testnet.bybit.com" if TESTNET else "https://api.bybit.com"
session = HTTP(api_key=API_KEY, api_secret=API_SECRET, base_url=base_url)

# Funkcja wysyłająca wiadomości na Discorda
def send_to_discord(message):
    try:
        payload = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"❌ Błąd wysyłania do Discord: {e}")

# Funkcja obliczająca ilość kontraktów (dla WIFUSDT)
def calculate_qty(symbol):
    try:
        send_to_discord("🔍 Rozpoczynam obliczanie ilości...")

        balance_data = session.get_wallet_balance(accountType="UNIFIED")

        balance_info = balance_data["result"]["list"][0]["coin"]
        usdt = next(c for c in balance_info if c["coin"] == "USDT")
        available_usdt = float(usdt.get("walletBalance", 0))
        trade_usdt = available_usdt * 0.5  # 50% salda

        tickers_data = session.get_tickers(category="linear")
        price_info = next((item for item in tickers_data["result"]["list"] if item["symbol"] == symbol), None)

        if not price_info:
            send_to_discord(f"⚠️ Symbol {symbol} nie został znaleziony w tickers.")
            return None

        last_price = float(price_info["lastPrice"])
        qty = int(trade_usdt / last_price)

        if qty < 1:
            send_to_discord(f"⚠️ Obliczona ilość to {qty}. Za mała kwota do zakupu choćby 1 kontraktu.")
            return None

        send_to_discord(f"✅ Obliczona ilość: {qty} WIF przy cenie {last_price} USDT")
        return qty

    except Exception as e:
        send_to_discord(f"⚠️ Błąd obliczania ilości: {e}")
        return None

# Główna funkcja webhooka
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
        # 1. Zamknij przeciwną pozycję
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

        # 2. Otwórz nową pozycję
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

if __name__ == "__main__":
    app.run(debug=False, port=5000)
