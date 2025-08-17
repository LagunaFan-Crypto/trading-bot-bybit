import os
import time
import json
import requests
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

# ====================== KONFIGURACJA ======================
# Preferuj config.py, ale pozwól też na ENV fallback (np. na serwerze)
try:
    from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET
except Exception:
    API_KEY = os.environ.get("API_KEY", "")
    API_SECRET = os.environ.get("API_SECRET", "")
    SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    TESTNET = os.environ.get("TESTNET", "true").lower() in ("1", "true", "yes")

PORT = int(os.environ.get("PORT", 5000))
ALERT_COOLDOWN = int(os.environ.get("ALERT_COOLDOWN", 3))  # sekundy

# ====================== FLASK & BYBIT ======================
app = Flask(__name__)

session = HTTP(
    api_key=API_KEY,
    api_secret=API_SECRET,
    testnet=TESTNET
)

# ====================== STAN BOTA ======================
processing = False
last_alert_time = 0


# ====================== POMOCNICZE ======================
def send_to_discord(message: str):
    """Wyślij prostą wiadomość na Discord (nie zrywa działania bota)."""
    if not DISCORD_WEBHOOK_URL:
        print(f"[Discord OFF] {message}")
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"❌ Błąd wysyłania do Discord: {e}")


def parse_incoming_json():
    """
    Tolerancyjne parsowanie ciała requestu:
    - normalnie: request.get_json(silent=True)
    - fallback: próba json.loads z request.data
    Zwraca dict albo None.
    """
    data = request.get_json(silent=True)
    if data is not None:
        return data
    raw = request.data.decode("utf-8") if request.data else ""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def get_current_position(symbol: str):
    """Zwróć (size: float, side: 'Buy'|'Sell'|'None') bez podnoszenia wyjątków."""
    try:
        result = session.get_positions(category="linear", symbol=symbol)
        position = result["result"]["list"][0]
        size = float(position.get("size", 0) or 0)
        side = position.get("side") or "None"
        return size, side
    except Exception as e:
        send_to_discord(f"❗ Błąd pobierania pozycji: {e}")
        return 0.0, "None"


def calculate_qty(symbol: str):
    """Prosty sizing: 100% wolnego USDT / ostatnia cena (zaokrąglone do int)."""
    try:
        send_to_discord("📊 Obliczam wielkość nowej pozycji...")
        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        coins = balance_data["result"]["list"][0]["coin"]
        usdt = next((c for c in coins if c.get("coin") == "USDT"), None)
        if not usdt:
            send_to_discord("❗ Brak monety USDT na koncie UNIFIED.")
            return None

        available_usdt = float(usdt.get("walletBalance", 0) or 0)
        trade_usdt = available_usdt * 1.0  # 100% — dostosuj wg potrzeby

        tickers_data = session.get_tickers(category="linear")
        price_info = next((it for it in tickers_data["result"]["list"] if it.get("symbol") == symbol), None)
        if not price_info:
            send_to_discord(f"❗ Symbol {symbol} nie znaleziony.")
            return None

        last_price = float(price_info.get("lastPrice") or 0)
        if last_price <= 0:
            send_to_discord("❗ Nieprawidłowa cena rynkowa.")
            return None

        qty = int(trade_usdt / last_price)
        send_to_discord(f"✅ Ilość do zlecenia: {qty} {symbol} przy cenie {last_price} USDT")
        return qty
    except Exception as e:
        send_to_discord(f"❗ Błąd podczas obliczania ilości: {e}")
        return None


# ====================== ROUTES ======================
@app.get("/")
def index():
    return "✅ Bot działa!", 200


@app.post("/webhook")
def webhook():
    global processing, last_alert_time

    # Anti-spam cooldown
    now = time.time()
    if now - last_alert_time < ALERT_COOLDOWN:
        send_to_discord("⏳ Alert zignorowany — zbyt krótki odstęp czasu.")
        return "Too soon", 429

    # Single-flight
    if processing:
        send_to_discord("⏳ Poprzedni alert nadal przetwarzany. Pomijam ten.")
        return "Processing in progress", 429

    processing = True
    last_alert_time = now

    try:
        data = parse_incoming_json()
        print(f"🔔 Odebrano alert: {data}")

        if not isinstance(data, dict):
            send_to_discord("⚠️ Webhook bez poprawnego JSON. Upewnij się, że w 'Wiadomość' jest {{strategy.order.alert_message}}.")
            processing = False
            return "Invalid JSON", 415

        action = str(data.get("action", "")).lower().strip()
        if action not in ("buy", "sell"):
            send_to_discord(f"⚠️ Nieprawidłowe polecenie: '{action}'. Dozwolone: 'buy' lub 'sell'.")
            processing = False
            return "Invalid action", 400

        # Aktualna pozycja
        position_size, position_side = get_current_position(SYMBOL)

        # Jeśli już w dobrym kierunku — nic nie rób
        if position_size > 0 and (
            (action == "buy" and position_side == "Buy") or
            (action == "sell" and position_side == "Sell")
        ):
            send_to_discord(f"ℹ️ Pozycja już otwarta w kierunku {position_side.upper()} — brak akcji.")
            processing = False
            return jsonify(ok=True, msg="Position already open"), 200

        # Jeśli jest pozycja w przeciwnym kierunku — zamknij
        if position_size > 0.0001 and position_side in ("Buy", "Sell"):
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
                send_to_discord(f"🔒 Zamknięto pozycję {position_side.upper()} ({position_size} {SYMBOL})")
                time.sleep(1.5)
            except Exception as e:
                send_to_discord(f"❗ Błąd przy zamykaniu pozycji: {e}")

        # Otwórz nową pozycję, jeśli już nic nie ma
        position_size, _ = get_current_position(SYMBOL)
        if position_size < 0.0001:
            qty = calculate_qty(SYMBOL)
            if not qty:
                send_to_discord("⚠️ Zbyt mała ilość do otwarcia pozycji. Anuluję.")
                processing = False
                return "Invalid qty", 400

            try:
                side = "Buy" if action == "buy" else "Sell"
                session.place_order(
                    category="linear",
                    symbol=SYMBOL,
                    side=side,
                    orderType="Market",
                    qty=qty,
                    timeInForce="GoodTillCancel"
                )
                send_to_discord(f"📥 Otwarto pozycję {side.upper()} ({qty} {SYMBOL})")
            except Exception as e:
                send_to_discord(f"❗ Błąd przy składaniu zlecenia: {e}")

        processing = False
        return jsonify(ok=True), 200

    except Exception as e:
        send_to_discord(f"❗ Błąd systemowy: {e}")
        processing = False
        return "Webhook error", 500


# ====================== START ======================
if __name__ == "__main__":
    print("🚀 Bot uruchomiony…")
    app.run(host="0.0.0.0", port=PORT)
