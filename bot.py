import os
import time
from flask import Flask, request
from pybit.unified_trading import HTTP
import requests
from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET

app = Flask(__name__)
port = int(os.environ.get("PORT", 5000))

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)

def send_to_discord(message):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
    except Exception as e:
        print(f"❌ Błąd Discord: {e}")

def get_current_position(symbol):
    try:
        result = session.get_positions(category="linear", symbol=symbol)
        pos = result["result"]["list"][0]
        size = float(pos["size"])
        side = pos["side"]
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
        wallet = session.get_wallet_balance(accountType="UNIFIED")
        usdt = next(c for c in wallet["result"]["list"][0]["coin"] if c["coin"] == "USDT")
        available = float(usdt.get("walletBalance", 0))
        trade_usdt = available * 1.0

        tickers = session.get_tickers(category="linear")
        price_info = next((i for i in tickers["result"]["list"] if i["symbol"] == symbol), None)
        if not price_info:
            send_to_discord(f"⚠️ Symbol {symbol} nie znaleziony.")
            return None

        price = float(price_info["lastPrice"])
        qty = int(trade_usdt / price)
        send_to_discord(f"✅ Obliczona ilość: {qty} {symbol} przy cenie {price} USDT")
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
            send_to_discord(f"⚠️ Nieprawidłowe polecenie: '{action}'. Użyj 'buy' lub 'sell'.")
            return "Invalid action", 400

        position_size, position_side = get_current_position(SYMBOL)

        if position_size > 0:
            if position_side.lower() == action:
                send_to_discord(f"⚠️ Pozycja już otwarta w odpowiednim kierunku ({position_side}), nie składam nowego zlecenia.")
                return "Pozycja już otwarta", 200

            # Zamykamy przeciwną pozycję
            close_side = "Sell" if position_side == "Buy" else "Buy"
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
                time.sleep(2)
            except Exception as e:
                send_to_discord(f"❌ Błąd składania zlecenia: {e}")
                return "ReduceOnly Error", 500

            # Sprawdź ponownie czy pozycja została zamknięta
            size_check, _ = get_current_position(SYMBOL)
            if size_check > 0:
                send_to_discord("⚠️ Pozycja nadal otwarta po próbie zamknięcia. Przerywam operację.")
                return "Pozycja nie została zamknięta", 400

        qty = calculate_qty(SYMBOL)
        if qty is None or qty == 0:
            send_to_discord("⚠️ Nie można obliczyć ilości do zlecenia.")
            return "Invalid qty", 400

        new_order = session.place_order(
            category="linear",
            symbol=SYMBOL,
            side="Buy" if action == "buy" else "Sell",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel"
        )
        send_to_discord(f"✅ Zlecenie {action.upper()} złożone: {qty} {SYMBOL}")
        return "OK", 200

    except Exception as e:
        send_to_discord(f"❌ Błąd ogólny: {e}")
        return "Webhook error", 500

if __name__ == "__main__":
    print("Bot uruchomiony...")
    app.run(host="0.0.0.0", port=port)
