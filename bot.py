import os
import time
import math
import json
import requests
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

# ====================== NARZĘDZIA / NORMALIZACJA ======================
def normalize_symbol(sym: str) -> str:
    """Normalizuje symbole z TradingView/Bybit: usuwa '.P', spacje i ustawia UPPERCASE"""
    if not sym:
        return ""
    s = str(sym).strip().upper()
    if s.endswith(".P"):
        s = s[:-2]
    return s

# ====================== KONFIGURACJA ======================
try:
    from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET, ALLOWED_SYMBOLS, POSITION_MODE, POSITION_VALUE
except Exception:
    API_KEY = os.environ.get("API_KEY", "")
    API_SECRET = os.environ.get("API_SECRET", "")
    SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    TESTNET = os.environ.get("TESTNET", "true").lower() in ("1", "true", "yes")
    ALLOWED_SYMBOLS = [
        s.strip() for s in os.environ.get("ALLOWED_SYMBOLS", "WIFUSDT,COAIUSDT").split(",") if s.strip()
    ]
    POSITION_MODE = os.environ.get("POSITION_MODE", "PERCENT").upper()
    POSITION_VALUE = float(os.environ.get("POSITION_VALUE", "1.0"))

# Zestaw dozwolonych symboli po normalizacji
ALLOWED_SET = {normalize_symbol(s) for s in (ALLOWED_SYMBOLS or [])}
PORT = int(os.environ.get("PORT", 5000))

# Tryby zachowania
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
    """Zwraca (size: float, side: 'Buy'|'Sell'|'None') dla podanego symbolu."""
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
    """Zwraca (current_sl: float|None, current_tp: float|None, positionIdx: int)."""
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

# ====================== NOWA FUNKCJA WYLICZANIA ILOŚCI ======================
def calculate_qty(symbol: str):
    """
    Zwraca (qty, value_usdt):
    - qty = ilość jednostek
    - value_usdt = wartość pozycji w USDT
    """
    try:
        send_to_discord(f"📊 Tryb pozycji: {POSITION_MODE}, wartość: {POSITION_VALUE}")

        tickers_data = session.get_tickers(category="linear")
        price_info = next((it for it in tickers_data["result"]["list"] if it.get("symbol") == symbol), None)
        if not price_info:
            send_to_discord(f"❗ Symbol {symbol} nie znaleziony.")
            return None, None

        last_price = float(price_info.get("lastPrice") or 0)
        if last_price <= 0:
            send_to_discord("❗ Nieprawidłowa cena rynkowa.")
            return None, None

        # --- TRYB STAŁEJ WIELKOŚCI ---
        if POSITION_MODE == "SIZE":
            qty = float(POSITION_VALUE)
            if qty <= 0:
                send_to_discord("❗ Ilość musi być > 0.")
                return None, None
            value_usdt = qty * last_price
            send_to_discord(f"✅ Wielkość ustalona: {qty} {symbol} ≈ {value_usdt:.2f} USDT (Cena: {last_price})")
            return qty, value_usdt

        # --- TRYB PROCENTOWEGO KAPITAŁU ---
        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        coins = balance_data["result"]["list"][0]["coin"]
        usdt = next((c for c in coins if c.get("coin") == "USDT"), None)
        if not usdt:
            send_to_discord("❗ Brak USDT na koncie UNIFIED.")
            return None, None

        available_usdt = float(usdt.get("walletBalance", 0) or 0)
        trade_usdt = available_usdt * POSITION_VALUE   # np. 1.0 → 100%, 0.5 → 50%
        qty = trade_usdt / last_price
        qty = round(qty, 6)

        send_to_discord(f"✅ Wyliczona ilość: {qty} {symbol} ≈ {trade_usdt:.2f} USDT (Cena: {last_price})")
        return qty, trade_usdt

    except Exception as e:
        send_to_discord(f"❗ Błąd calculate_qty: {e}")
        return None, None

def _isclose(a: float, b: float) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=0.0)
    except Exception:
        return str(a) == str(b)

# ====================== SL / TP ======================
def set_tp_sl_safe(symbol: str, side: str, sl_price: float | None, tp_price: float | None,
                   *, clear_sl: bool = False, clear_tp: bool = False):
    global last_sl_value, last_tp_value, last_sl_set_ts, last_tp_set_ts
    try:
        cur_sl, cur_tp, idx = get_sl_tp(symbol)
        size, _ = get_current_position(symbol)
        if size <= 0:
            return {"skipped": "no position"}

        want_sl, want_tp = None, None
        if clear_sl:
            want_sl = "0"
        elif sl_price:
            want_sl = str(sl_price)
        if clear_tp:
            want_tp = "0"
        elif tp_price:
            want_tp = str(tp_price)

        if want_sl is None and want_tp is None:
            return {"ok": True, "skipped": "no changes"}

        payload = {"category": "linear", "symbol": symbol, "positionIdx": idx,
                   "tpslMode": "Full", "slTriggerBy": "LastPrice", "tpTriggerBy": "LastPrice"}
        if want_sl: payload["stopLoss"] = want_sl
        if want_tp: payload["takeProfit"] = want_tp
        session.set_trading_stop(**payload)

        if want_sl == "0":
            send_to_discord(f"🧹 Kasuję SL dla {symbol}")
        elif want_sl: send_to_discord(f"🛡️ Ustawiam SL @ {want_sl}")
        if want_tp == "0":
            send_to_discord(f"🧹 Kasuję TP dla {symbol}")
        elif want_tp: send_to_discord(f"🎯 Ustawiam TP @ {want_tp}")
        return {"ok": True}
    except Exception as e:
        send_to_discord(f"❗ Błąd set_tp_sl_safe: {e}")
        return {"error": str(e)}

# ====================== FLASK ROUTES ======================
@app.get("/")
def index():
    return "✅ Bot działa!", 200

@app.post("/webhook")
def webhook():
    global processing, last_close_ts
    if processing:
        return "Processing in progress", 429
    processing = True
    try:
        data = parse_incoming_json()
        if not isinstance(data, dict):
            if IGNORE_NON_JSON:
                processing = False
                return ("", 204)
            processing = False
            return "Ignored non-JSON", 204

        action = str(data.get("action", "")).lower().strip()
        symbol_raw = str(data.get("symbol", SYMBOL)).strip() or SYMBOL
        symbol = normalize_symbol(symbol_raw)
        if symbol not in ALLOWED_SET:
            send_to_discord(f"🚫 Niedozwolony symbol: {symbol_raw}")
            processing = False
            return jsonify(error="symbol not allowed"), 400

        sl_val = float(data.get("sl") or 0) or None
        tp_val = float(data.get("tp") or 0) or None
        size, side = get_current_position(symbol)

        # ===== CLOSE =====
        if action == "close":
            now = time.time()
            if now - last_close_ts < 1.0:
                processing = False
                return jsonify(ok=True), 200
            last_close_ts = now
            if size <= 0:
                processing = False
                return ("", 204)
            tickers = session.get_tickers(category="linear")["result"]["list"]
            last_price = float(next((t["lastPrice"] for t in tickers if t["symbol"] == symbol), 0))
            value_usdt = size * last_price
            close_side = "Sell" if side == "Buy" else "Buy"
            session.place_order(category="linear", symbol=symbol, side=close_side,
                                orderType="Market", qty=size, reduceOnly=True, timeInForce="GoodTillCancel")
            send_to_discord(f"🧯 CLOSE: zamknięto {side.upper()} {size} {symbol} ≈ {value_usdt:.2f} USDT")
            set_tp_sl_safe(symbol, side, None, None, clear_sl=True, clear_tp=True)
            processing = False
            return jsonify(ok=True), 200

        # ===== BUY / SELL =====
        if action in ("buy", "sell"):
            if size > 0:
                close_side = "Sell" if side == "Buy" else "Buy"
                session.place_order(category="linear", symbol=symbol, side=close_side,
                                    orderType="Market", qty=size, reduceOnly=True, timeInForce="GoodTillCancel")
                send_to_discord(f"🔒 Zamknięto poprzednią pozycję {side.upper()} ({size} {symbol})")
                time.sleep(1.2)

            qty, value_usdt = calculate_qty(symbol)
            if not qty:
                processing = False
                return "Invalid qty", 400

            side_new = "Buy" if action == "buy" else "Sell"
            session.place_order(category="linear", symbol=symbol, side=side_new,
                                orderType="Market", qty=qty, timeInForce="GoodTillCancel")
            msg = f"📥 Otwarto pozycję {side_new.upper()} ({qty} {symbol})"
            if value_usdt:
                msg += f" ≈ {value_usdt:.2f} USDT"
            send_to_discord(msg)
            print("[INFO]", msg)
            set_tp_sl_safe(symbol, side_new, sl_val, tp_val)
            processing = False
            return jsonify(ok=True), 200

        processing = False
        return jsonify(ok=True), 200
    except Exception as e:
        send_to_discord(f"❗ Błąd systemowy: {e}")
        processing = False
        return "Webhook error", 500

if __name__ == "__main__":
    print("🚀 Bot uruchomiony…")
    print(f"✅ Dozwolone pary: {', '.join(sorted(ALLOWED_SET))}")
    print(f"📈 Tryb pozycji: {POSITION_MODE}, wartość: {POSITION_VALUE}")
    app.run(host="0.0.0.0", port=PORT)
