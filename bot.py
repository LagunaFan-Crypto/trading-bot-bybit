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
    from config import (
        API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL,
        TESTNET, ALLOWED_SYMBOLS, POSITION_MODE, POSITION_VALUE
    )
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

ALLOWED_SET = {normalize_symbol(s) for s in (ALLOWED_SYMBOLS or [])}
PORT = int(os.environ.get("PORT", 5000))

RESPECT_MANUAL_SL = os.environ.get("RESPECT_MANUAL_SL", "true").lower() in ("1", "true", "yes")
RESPECT_MANUAL_TP = os.environ.get("RESPECT_MANUAL_TP", "true").lower() in ("1", "true", "yes")
IGNORE_NON_JSON = os.environ.get("IGNORE_NON_JSON", "true").lower() in ("1", "true", "yes")

app = Flask(__name__)
session = HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)

processing = False
last_close_ts = 0.0

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
    """Zwraca (size, side, entryPrice)"""
    try:
        res = session.get_positions(category="linear", symbol=symbol)
        items = (res or {}).get("result", {}).get("list", []) or []
        if not items:
            return 0.0, "None", 0.0
        p = items[0]
        return float(p.get("size") or 0), p.get("side") or "None", float(p.get("entryPrice") or 0)
    except Exception as e:
        send_to_discord(f"❗ Błąd pobierania pozycji: {e}")
        return 0.0, "None", 0.0

# ====================== WYLICZANIE ILOŚCI ======================
def calculate_qty(symbol: str):
    """Zwraca (qty, value_usdt)"""
    try:
        send_to_discord(f"📊 Tryb pozycji: {POSITION_MODE}, wartość: {POSITION_VALUE}")

        tickers = session.get_tickers(category="linear")["result"]["list"]
        info = next((x for x in tickers if x["symbol"] == symbol), None)
        if not info:
            send_to_discord(f"❗ Symbol {symbol} nie znaleziony.")
            return None, None
        last_price = float(info["lastPrice"])
        if last_price <= 0:
            return None, None

        # --- TRYB STAŁEJ WIELKOŚCI ---
        if POSITION_MODE == "SIZE":
            qty = float(POSITION_VALUE)
            value = qty * last_price
            send_to_discord(f"✅ Wielkość ustalona: {qty} {symbol} ≈ {value:.2f} USDT (Cena: {last_price})")
            return qty, value

        # --- TRYB PROCENTOWY ---
        balance = session.get_wallet_balance(accountType="UNIFIED")
        coins = balance["result"]["list"][0]["coin"]
        usdt = next((c for c in coins if c["coin"] == "USDT"), None)
        if not usdt:
            send_to_discord("❗ Brak USDT.")
            return None, None
        wallet = float(usdt["walletBalance"])
        trade_usdt = wallet * POSITION_VALUE
        qty = round(trade_usdt / last_price, 6)
        send_to_discord(f"✅ Wyliczona ilość: {qty} {symbol} ≈ {trade_usdt:.2f} USDT (Cena: {last_price})")
        return qty, trade_usdt
    except Exception as e:
        send_to_discord(f"❗ Błąd calculate_qty: {e}")
        return None, None

# ====================== ZLECENIA SL/TP ======================
def set_tp_sl_safe(symbol, side, sl, tp):
    try:
        res = session.get_positions(category="linear", symbol=symbol)
        items = res["result"]["list"]
        if not items:
            return
        idx = int(items[0]["positionIdx"])
        payload = {"category": "linear", "symbol": symbol, "positionIdx": idx,
                   "tpslMode": "Full", "slTriggerBy": "LastPrice", "tpTriggerBy": "LastPrice"}
        if sl: payload["stopLoss"] = str(sl)
        if tp: payload["takeProfit"] = str(tp)
        session.set_trading_stop(**payload)
        if sl: send_to_discord(f"🛡️ Ustawiam SL @ {sl}")
        if tp: send_to_discord(f"🎯 Ustawiam TP @ {tp}")
    except Exception as e:
        send_to_discord(f"❗ Błąd set_tp_sl_safe: {e}")

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
            processing = False
            return ("", 204)

        action = data.get("action", "").lower()
        symbol = normalize_symbol(data.get("symbol", SYMBOL))
        sl = float(data.get("sl") or 0) or None
        tp = float(data.get("tp") or 0) or None

        size, side, entry = get_current_position(symbol)

        # ===== CLOSE =====
        if action == "close":
            if size <= 0:
                processing = False
                return ("", 204)
            tickers = session.get_tickers(category="linear")["result"]["list"]
            last = float(next((t["lastPrice"] for t in tickers if t["symbol"] == symbol), 0))
            value = size * last
            pnl_pct = 0.0
            if entry > 0:
                if side == "Buy":
                    pnl_pct = (last - entry) / entry * 100
                else:
                    pnl_pct = (entry - last) / entry * 100
            close_side = "Sell" if side == "Buy" else "Buy"
            session.place_order(category="linear", symbol=symbol, side=close_side,
                                orderType="Market", qty=size, reduceOnly=True,
                                timeInForce="GoodTillCancel")
            sign = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < 0 else "⚪"
            msg = f"🧯 CLOSE: zamknięto {side.upper()} {size} {symbol} ≈ {value:.2f} USDT ({sign}{pnl_pct:.2f}%)"
            send_to_discord(msg)
            print("[INFO]", msg)
            set_tp_sl_safe(symbol, side, None, None)
            processing = False
            return jsonify(ok=True), 200

        # ===== BUY / SELL =====
        if action in ("buy", "sell"):
            if size > 0:
                close_side = "Sell" if side == "Buy" else "Buy"
                session.place_order(category="linear", symbol=symbol, side=close_side,
                                    orderType="Market", qty=size, reduceOnly=True,
                                    timeInForce="GoodTillCancel")
                send_to_discord(f"🔒 Zamknięto poprzednią pozycję {side.upper()} ({size} {symbol})")
                time.sleep(1.2)

            qty, value = calculate_qty(symbol)
            if not qty:
                processing = False
                return "Invalid qty", 400

            new_side = "Buy" if action == "buy" else "Sell"
            session.place_order(category="linear", symbol=symbol, side=new_side,
                                orderType="Market", qty=qty, timeInForce="GoodTillCancel")
            msg = f"📥 Otwarto pozycję {new_side.upper()} ({qty} {symbol})"
            if value:
                msg += f" ≈ {value:.2f} USDT"
            send_to_discord(msg)
            print("[INFO]", msg)
            set_tp_sl_safe(symbol, new_side, sl, tp)
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
