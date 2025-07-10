from flask import Flask, request
from pybit.unified_trading import HTTP
import requests
import os

app = Flask(__name__)

# -------- KONFIGURACJA --------
API_KEY = "W3LJVCmbmyTN3mgoOl"
API_SECRET = "JaFt7WrggPhGhzKyexC1ecfaGUHiPhuVLZ7R"
TESTNET = False  # Ustaw na True, jeśli używasz testnetu
DISCORD_WEBHOOK_URL = "https://trading-bot-bybit-9rju.onrender.com/webhook"

SYMBOL = "BTCUSDT"  # ✅ Zmienimy na WIFUSDT, jak ustalimy poprawną nazwę

# -------- INICJALIZACJA SESSION --------
base_url = "https://api-testnet.bybit.com" if TESTNET else "https://api.bybit.com"
session = HTTP(api_key=API_KEY, api_secret=API_SECRET, endpoint=base_url)


# -------- FUNKCJA WYSYŁANIA WIADOMOŚCI NA DISCORD --------
def send_to_discord(message):
    payload = {"content": message}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"Nie udało się wysłać na Discord: {e}")


# -------- FUNKCJA OBLICZANIA ILOŚCI --------
def calculate_qty(symbol):
    try:
        send_to_discord("🔍 Rozpoczynam obliczanie ilości...")

        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        send_to_discord(f"💰 Odpowiedź z get_wallet_balance:\n{balance_data}")

        balance_info = balance_data["result"]["list"][0]["coin"]
        usdt = next(c for c in balance_info if c["coin"] == "USDT")
        available_usdt = float(usdt.get("walletBalance", 0))
        trade_usdt = available_usdt * 0.5

        tickers_data = session.get_tickers(category="linear")
        send_to_discord(f"📈 Odpowiedź z get_tickers:\n{tickers_data}")

        # WYŚWIETL WSZYSTKIE SYMBOLE (debug)
        all_symbols = [item["symbol"] for item in tickers_data["result"]["list"]]
        send_to_discord(f"📜 Lista symboli:\n{all_symbols}")

        price_info = next((item for item in tickers_data["result"]["list"] if item["symbol"] == symbol), None)

        if not price_info:
            send_to_discord(f"⚠️ Symbol {symbol} nie został znaleziony w tickers.")
            return None

        last_price = float(price_info["lastPrice"])
        qty = round(trade_usdt / last_price, 3)
        send_to_discord(f"✅ Obliczona ilość: {qty} przy cenie {last_price}")
        return qty

    except Exception as e:
        send_to_discord(f"⚠️ Błąd obliczania ilości: {e}")
        return None


# -------- ENDPOINT WEBHOOKA --------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    action = data.get("action", "").lower()

    if action not in ["buy", "sell"]:
        send_to_discord("⚠️ Nieprawidłowe polecenie. Użyj 'buy' lub 'sell'.")
        return "Invalid action", 400

    qty = calculate_qty(SYMBOL)
    if qty is None:
        return "Failed to calculate qty", 500

    try:
        side = "Buy" if action == "buy" else "Sell"
        order = session.place_order(
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


# -------- URUCHOMIENIE APLIKACJI --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
