import os
import time
import math
import json
import requests
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

# ====================== KONFIGURACJA ======================
try:
    from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET, ALLOWED_SYMBOLS
except Exception:
    API_KEY = os.environ.get("API_KEY", "")
    API_SECRET = os.environ.get("API_SECRET", "")
    SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    TESTNET = os.environ.get("TESTNET", "true").lower() in ("1", "true", "yes")
    ALLOWED_SYMBOLS = [
        s.strip().upper()
        for s in os.environ.get("ALLOWED_SYMBOLS", "WIFUSDT,COAIUSDT").split(",")
        if s.strip()
    ]

PORT = int(os.environ.get("PORT", 5000))

RESPECT_MANUAL_SL = os.environ.get("RESPECT_MANUAL_SL", "true").lower() in ("1", "true", "yes")
RESPECT_MANUAL_TP = os.environ.get("RESPECT_MANUAL_TP", "true").lower() in ("1", "true", "yes")
AUTO_RESUME_ON_MANUAL_REMOVE = os.environ.get("AUTO_RESUME_ON_MANUAL_REMOVE", "true").lower() in ("1", "true", "yes")
IGNORE_NON_JSON = os.environ.get("IGNORE_NON_JSON", "true").lower() in ("1", "true", "yes")

app = Flask(__name__)
session = HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)

# ====================== STAN BOTA ======================
processing = False
last_close_ts = 0.0

last_sl_value = None
last_tp_value = None
last_sl_set_ts = 0.0
last_tp_set_ts = 0.0
manual_sl_locked = False
manual_tp_locked = False

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

def get_sl_tp(symbol: str):
    try:
        res = session.get_positions(category="linear", symbol=symbol)
        items = (res or {}).get("result", {}).get("list", []) or []
        if not items:
            return None, None, 0
        pos = items[0]
        sl = float(pos.get("stopLoss") or 0) or None
        tp = float(pos.get("takeProfit") or 0) or None
        idx = int(pos.get("positionIdx", 0) or 0)
        return sl, tp, idx
    except Exception:
        return None, None, 0

def calculate_qty(symbol: str):
    try:
        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        coins = balance_data["result"]["list"][0]["coin"]
        usdt = next((c for c in coins if c.get("coin") == "USDT"), None)
        if not usdt:
            send_to_discord("❗ Brak monety USDT.")
            return None
        available_usdt = float(usdt.get("walletBalance", 0) or 0)
        trade_usdt = available_usdt * 1
        tickers_data = session.get_tickers(category="linear")
        price_info = next((it for it in tickers_data["result"]["list"] if it.get("symbol") == symbol), None)
        if not price_info:
            send_to_discord(f"❗ Symbol {symbol} nie znaleziony.")
            return None
        last_price = float(price_info.get("lastPrice") or 0)
        qty = int(trade_usdt / last_price)
        return qty if qty >= 1 else None
    except Exception as e:
        send_to_discord(f"❗ Błąd ilości: {e}")
        return None

def _isclose(a: float, b: float) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=0.0)
    except Exception:
        return str(a) == str(b)

# ====================== FUNKCJE DLA SL/TP ======================
def set_tp_sl_safe(symbol: str, side: str, sl_price: float | None, tp_price: float | None):
    global last_sl_value, last_tp_value, last_sl_set_ts, last_tp_set_ts
    try:
        cur_sl, cur_tp, idx = get_sl_tp(symbol)
        payload = {
            "category": "linear",
            "symbol": symbol,
            "positionIdx": idx,
            "tpslMode": "Full",
            "slTriggerBy": "LastPrice",
            "tpTriggerBy": "LastPrice"
        }

        if sl_price and sl_price > 0:
            if not cur_sl or not _isclose(cur_sl, sl_price):
                payload["stopLoss"] = str(sl_price)
                session.set_trading_stop(**payload)
                send_to_discord(f"🛡️ SL ustawiony: {sl_price}")
                last_sl_value = sl_price
                last_sl_set_ts = time.time()
        elif cur_sl and sl_price is None:
            payload["stopLoss"] = "0"
            session.set_trading_stop(**payload)
            send_to_discord("🧹 SL usunięty.")
            last_sl_value = None

        if tp_price and tp_price > 0:
            if not cur_tp or not _isclose(cur_tp, tp_price):
                payload["takeProfit"] = str(tp_price)
                session.set_trading_stop(**payload)
                send_to_discord(f"🎯 TP ustawiony: {tp_price}")
                last_tp_value = tp_price
                last_tp_set_ts = time.time()
        elif cur_tp and tp_price is None:
            payload["takeProfit"] = "0"
            session.set_trading_stop(**payload)
            send_to_discord("🧹 TP usunięty.")
            last_tp_value = None

    except Exception as e:
        send_to_discord(f"❗ Błąd ustawiania TP/SL: {e}")

# ====================== ROUTES ======================
@app.get("/")
def index():
    return "✅ Bot działa!", 200

@app.post("/webhook")
def webhook():
    global processing, last_close_ts, manual_sl_locked, manual_tp_locked

    if processing:
        return "Processing", 429
    processing = True

    try:
        data = parse_incoming_json()
        if not isinstance(data, dict):
            if IGNORE_NON_JSON:
                processing = False
                return "", 204
        action = str(data.get("action", "")).lower().strip()
        symbol = str(data.get("symbol", SYMBOL)).upper().strip() or SYMBOL
        if symbol not in ALLOWED_SYMBOLS:
            send_to_discord(f"🚫 Niedozwolony symbol: {symbol}")
            processing = False
            return jsonify(error="symbol not allowed"), 400

        sl_val = data.get("sl")
        tp_val = data.get("tp")
        sl_price = float(sl_val) if sl_val not in ("", None) else None
        tp_price = float(tp_val) if tp_val not in ("", None) else None

        allowed = ("buy", "sell", "close", "update_sl", "update_tp",
                   "clear_sl", "clear_tp", "unlock_sl", "unlock_tp",
                   "force_update_sl", "force_update_tp")
        if action not in allowed:
            processing = False
            return "", 204

        size, side = get_current_position(symbol)

        # ===== AKCJE =====
        if action in ("unlock_sl", "unlock_tp"):
            if "sl" in action: manual_sl_locked = False
            if "tp" in action: manual_tp_locked = False
            send_to_discord("🔓 Odblokowano SL/TP.")
            processing = False
            return jsonify(ok=True), 200

        if action == "close":
            now = time.time()
            if now - last_close_ts < 1.0:
                processing = False
                return jsonify(ok=True), 200
            last_close_ts = now
            if size > 0:
                close_side = "Sell" if side == "Buy" else "Buy"
                session.place_order(category="linear", symbol=symbol, side=close_side,
                                    orderType="Market", qty=size, reduceOnly=True)
                send_to_discord(f"🧯 Zamknięto pozycję {side} ({size} {symbol})")
                set_tp_sl_safe(symbol, side, None, None)
            processing = False
            return jsonify(ok=True), 200

        if action in ("update_sl", "update_tp", "clear_sl", "clear_tp"):
            set_tp_sl_safe(
                symbol,
                side,
                None if "clear_sl" in action else sl_price,
                None if "clear_tp" in action else tp_price
            )
            processing = False
            return jsonify(ok=True), 200

        # BUY / SELL
        if action in ("buy", "sell"):
            if size > 0:
                close_side = "Sell" if side == "Buy" else "Buy"
                session.place_order(category="linear", symbol=symbol, side=close_side,
                                    orderType="Market", qty=size, reduceOnly=True)
                time.sleep(1)

            qty = calculate_qty(symbol)
            if not qty:
                processing = False
                return "Invalid qty", 400

            side_new = "Buy" if action == "buy" else "Sell"
            session.place_order(category="linear", symbol=symbol, side=side_new,
                                orderType="Market", qty=qty)
            send_to_discord(f"📥 Nowa pozycja {side_new.upper()} ({qty} {symbol})")
            set_tp_sl_safe(symbol, side_new, sl_price, tp_price)

        processing = False
        return jsonify(ok=True), 200

    except Exception as e:
        send_to_discord(f"❗ Błąd systemowy: {e}")
        processing = False
        return "Error", 500

if __name__ == "__main__":
    print("🚀 Bot uruchomiony…")
    print(f"✅ Dozwolone pary: {', '.join(ALLOWED_SYMBOLS)}")
    app.run(host="0.0.0.0", port=PORT)
