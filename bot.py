import os
import time
import json
import requests
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

# ====================== KONFIGURACJA ======================
try:
    from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET
except Exception:
    API_KEY = os.environ.get("API_KEY", "")
    API_SECRET = os.environ.get("API_SECRET", "")
    SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    TESTNET = os.environ.get("TESTNET", "true").lower() in ("1", "true", "yes")

PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
session = HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)

# ====================== STAN BOTA ======================
processing = False

# ====================== POMOCNICZE ======================
def send_to_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        print(f"[Discord OFF] {message}")
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"❌ Błąd wysyłania do Discord: {e}")

def parse_incoming_json():
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
    try:
        result = session.get_positions(category="linear", symbol=symbol)
        items = (result or {}).get("result", {}).get("list", []) or []
        if not items:
            return 0.0, "None"
        position = items[0]
        size = float(position.get("size") or 0)
        side = position.get("side") or "None"
        return size, side
    except Exception as e:
        send_to_discord(f"❗ Błąd pobierania pozycji: {e}")
        return 0.0, "None"

def calculate_qty(symbol: str):
    try:
        send_to_discord("📊 Obliczam wielkość nowej pozycji…")
        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        coins = balance_data["result"]["list"][0]["coin"]
        usdt = next((c for c in coins if c.get("coin") == "USDT"), None)
        if not usdt:
            send_to_discord("❗ Brak monety USDT na koncie UNIFIED.")
            return None

        available_usdt = float(usdt.get("walletBalance", 0) or 0)
        trade_usdt = available_usdt * 1.0  # 100% — zmień jeśli chcesz mniejszy risk

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

# ---------- SL / TRADING-STOP na Bybit ---------- # <<< NEW
def set_stop_loss(symbol: str, side: str, sl_price: float | None):
    """
    Ustawia lub kasuje SL dla bieżącej pozycji.
    - sl_price > 0 -> ustaw SL na tej cenie
    - sl_price is None lub <= 0 -> kasuj SL
    """
    try:
        # positionIdx: 1 = Buy (long), 2 = Sell (short) w trybie ONEWAY
        idx = 1 if (side or "").lower().startswith("b") else 2
        payload = {
            "category": "linear",
            "symbol": symbol,
            "positionIdx": idx,
            "slOrderType": "Market",   # wyjście market po trafieniu SL
            "slTriggerBy": "LastPrice" # opcjonalnie: "MarkPrice"
        }
        if sl_price and sl_price > 0:
            payload["stopLoss"] = str(sl_price)
            send_to_discord(f"🛡️ Ustawiam SL {side.upper()} @ {sl_price} na {symbol}")
        else:
            payload["stopLoss"] = "0"  # 0 = wyczyść SL wg Bybit v5
            send_to_discord(f"🧹 Kasuję SL dla {side.upper()} na {symbol}")

        session.set_trading_stop(**payload)
        return True
    except Exception as e:
        send_to_discord(f"❗ Błąd set_trading_stop: {e}")
        return False
# ----------------------------------------------- # <<< NEW

# ====================== ROUTES ======================
@app.get("/")
def index():
    return "✅ Bot działa!", 200

@app.post("/webhook")
def webhook():
    global processing

    if processing:
        send_to_discord("⏳ Poprzedni alert nadal przetwarzany. Pomijam ten.")
        return "Processing in progress", 429

    processing = True
    try:
        data = parse_incoming_json()
        if not isinstance(data, dict):
            send_to_discord("⚠️ Webhook bez poprawnego JSON. Upewnij się, że w 'Wiadomość' jest {{strategy.order.alert_message}} lub poprawny JSON.")
            processing = False
            return "Invalid JSON", 415

        action = str(data.get("action", "")).lower().strip()
        symbol = str(data.get("symbol", SYMBOL)).upper().strip() or SYMBOL
        sl_val = data.get("sl")  # może być number lub string lub None
        try:
            sl_price = float(sl_val) if sl_val is not None and sl_val != "" else None
        except Exception:
            sl_price = None

        # Akcje obsługiwane przez bota  # <<< NEW
        # buy/sell -> otwórz pozycję (i ustaw SL jeśli podany)
        # update_sl -> przesuń istniejący SL
        # clear_sl  -> skasuj SL
        if action not in ("buy", "sell", "update_sl", "clear_sl"):
            send_to_discord(f"⚠️ Nieprawidłowe polecenie: '{action}'. Dozwolone: buy/sell/update_sl/clear_sl.")
            processing = False
            return "Invalid action", 400

        # ------ UPDATE/CLEAR SL bez zmian pozycji ------ # <<< NEW
        if action in ("update_sl", "clear_sl"):
            size, side = get_current_position(symbol)
            if size <= 0:
                send_to_discord("ℹ️ Brak otwartej pozycji — pomijam zmianę SL.")
            else:
                target_sl = None if action == "clear_sl" else sl_price
                set_stop_loss(symbol, side, target_sl)
            processing = False
            return jsonify(ok=True, msg="SL updated"), 200
        # ------------------------------------------------

        # ------ BUY/SELL ------ (Twoja dotychczasowa logika)
        position_size, position_side = get_current_position(symbol)

        # Jeśli już w dobrym kierunku — nic nie rób, ale zaktualizuj SL jeśli przyszedł
        if position_size > 0 and (
            (action == "buy" and position_side == "Buy") or
            (action == "sell" and position_side == "Sell")
        ):
            send_to_discord(f"ℹ️ Pozycja już otwarta w kierunku {position_side.upper()} — brak wejścia.")
            if sl_price is not None:
                set_stop_loss(symbol, position_side, sl_price)  # <<< NEW
            processing = False
            return jsonify(ok=True, msg="Position already open"), 200

        # Jeśli jest pozycja w przeciwnym kierunku — zamknij
        if position_size > 0.0001 and position_side in ("Buy", "Sell"):
            close_side = "Sell" if position_side == "Buy" else "Buy"
            try:
                session.place_order(
                    category="linear",
                    symbol=symbol,
                    side=close_side,
                    orderType="Market",
                    qty=position_size,
                    reduceOnly=True,
                    timeInForce="GoodTillCancel"
                )
                send_to_discord(f"🔒 Zamknięto pozycję {position_side.upper()} ({position_size} {symbol})")
                time.sleep(1.2)
            except Exception as e:
                send_to_discord(f"❗ Błąd przy zamykaniu pozycji: {e}")

        # Otwórz nową pozycję, jeśli nic nie ma
        position_size, _ = get_current_position(symbol)
        if position_size < 0.0001:
            qty = calculate_qty(symbol)
            if not qty:
                send_to_discord("⚠️ Zbyt mała ilość do otwarcia pozycji. Anuluję.")
                processing = False
                return "Invalid qty", 400

            try:
                side = "Buy" if action == "buy" else "Sell"
                session.place_order(
                    category="linear",
                    symbol=symbol,
                    side=side,
                    orderType="Market",
                    qty=qty,
                    timeInForce="GoodTillCancel"
                )
                send_to_discord(f"📥 Otwarto pozycję {side.upper()} ({qty} {symbol})")
                time.sleep(0.8)  # krótka pauza aż pozycja „pojawi się” po stronie Bybit

                # Ustaw SL jeśli przyszedł w JSON-ie
                if sl_price is not None:
                    set_stop_loss(symbol, side, sl_price)  # <<< NEW
            except Exception as e:
                send_to_discord(f"❗ Błąd przy składaniu zlecenia: {e}")

        processing = False
        return jsonify(ok=True), 200

    except Exception as e:
        send_to_discord(f"❗ Błąd systemowy: {e}")
        processing = False
        return "Webhook error", 500

if __name__ == "__main__":
    print("🚀 Bot uruchomiony…")
    app.run(host="0.0.0.0", port=PORT)
