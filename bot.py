from flask import Flask, request
import time
from pybit.unified_trading import HTTP
import requests
from config import API_KEY, API_SECRET, SYMBOL, DISCORD_WEBHOOK_URL, TESTNET

# Tworzymy instancję aplikacji Flask
app = Flask(__name__)

# Upewnij się, że używasz poprawnego portu z Render
port = int(os.environ.get("PORT", 5000))

session = HTTP(
    api_key=API_KEY,
    api_secret=API_SECRET,
    testnet=TESTNET
)

# Zmienna śledząca, czy zlecenie zostało już złożone
order_in_progress = False

def send_to_discord(message):
    """Funkcja wysyłająca wiadomość na Discord."""
    try:
        payload = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"❌ Błąd wysyłania do Discord: {e}")

def get_current_position(symbol):
    """Funkcja sprawdzająca, czy istnieje otwarta pozycja."""
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
    """Funkcja do obliczania ilości do zlecenia na podstawie salda."""
    try:
        send_to_discord("🔍 Rozpoczynam obliczanie ilości...")

        balance_data = session.get_wallet_balance(accountType="UNIFIED")
        balance_info = balance_data["result"]["list"][0]["coin"]
        usdt = next(c for c in balance_info if c["coin"] == "USDT")
        available_usdt = float(usdt.get("walletBalance", 0))
        trade_usdt = available_usdt * 0.5  # Używamy 50% dostępnego USDT

        tickers_data = session.get_tickers(category="linear")
        price_info = next((item for item in tickers_data["result"]["list"] if item["symbol"] == symbol), None)

        if not price_info:
            send_to_discord(f"⚠️ Symbol {symbol} nie został znaleziony.")
            return None

        last_price = float(price_info["lastPrice"])
        qty = int(trade_usdt / last_price)

        if qty < 1:
            send_to_discord(f"⚠️ Obliczona ilość to {qty}. Za mało USDT.")
            return None

        send_to_discord(f"✅ Obliczona ilość: {qty} {symbol} przy cenie {last_price} USDT")
        return qty
    except Exception as e:
        send_to_discord(f"⚠️ Błąd obliczania ilości: {e}")
        return None

def round_to_precision(value, precision=2):
    """Funkcja do zaokrąglania wartości do określonej liczby miejsc po przecinku (domyślnie 2)."""
    return round(value, precision)

# Definicja webhooka
@app.route("/webhook", methods=["POST"])
def webhook():
    global last_action, order_in_progress

    try:
        data = request.get_json()
        print(f"🔔 Otrzymano webhook: {data}")  # Logowanie otrzymanych danych
        action = data.get("action", "").lower()

        if action not in ["buy", "sell"]:
            send_to_discord("⚠️ Nieprawidłowe polecenie. Użyj 'buy' lub 'sell'.")
            return "Invalid action", 400

        # Sprawdzenie, czy poprzedni alert był tego samego typu
        if action == last_action:
            print(f"🔁 Otrzymano powtórny alert: {action}. Ignorowanie zlecenia.")
            return "Alert ignored", 200

        # 1. Sprawdzamy, czy istnieją otwarte pozycje
        position_size, position_side = get_current_position(SYMBOL)

        # Jeśli pozycja nie została jeszcze zamknięta
        if position_size > 0:
            position_size = round_to_precision(position_size)

            if position_size < 0.01:
                send_to_discord("⚠️ Pozycja jest zbyt mała, aby ją zamknąć.")
                return "Invalid position size", 400

            close_side = "Buy" if position_side == "Sell" else "Sell"
            try:
                close_order = session.place_order(
                    category="linear",
                    symbol=SYMBOL,
                    side=close_side,
                    orderType="Market",
                    qty=position_size,
                    reduceOnly=True,
                    timeInForce="GoodTillCancel"
                )
                print(f"Zamknięcie pozycji: {close_order}")
                send_to_discord(f"🔒 Zamknięcie pozycji {position_side.upper()} ({position_size} {SYMBOL})")
                time.sleep(5)
                
            except Exception as e:
                send_to_discord(f"⚠️ Błąd zamykania pozycji: {e}")
                return "Order error", 500
        else:
            send_to_discord("⚠️ Brak otwartej pozycji, nie można zamknąć pozycji.")

        # 2. Jeśli pozycja jest zamknięta, składamy nowe zlecenie
        if position_size == 0 and not order_in_progress:  # Tylko jeśli zlecenie jeszcze nie zostało złożone
            order_in_progress = True  # Ustawiamy flagę na True, że zlecenie jest w trakcie składania
            
            qty = calculate_qty(SYMBOL)
            if qty is None or qty < 0.01:
                send_to_discord(f"⚠️ Obliczona ilość to {qty}. Zbyt mało środków na zlecenie.")
                order_in_progress = False
                return "Qty error", 400

            qty = round_to_precision(qty)

            # Składamy zlecenie w zależności od akcji
            new_side = "Buy" if action == "buy" else "Sell"
            new_order = session.place_order(
                category="linear",
                symbol=SYMBOL,
                side=new_side,
                orderType="Market",
                qty=qty,
                timeInForce="GoodTillCancel"
            )
            print(f"Nowe zlecenie: {new_order}")
            send_to_discord(f"✅ {new_side.upper()} zlecenie złożone: {qty} {SYMBOL}")
            last_action = action
            order_in_progress = False  # Po złożeniu zlecenia resetujemy flagę

        else:
            send_to_discord(f"⚠️ Pozycja nie została jeszcze zamknięta, nie składamy nowego zlecenia.")

        return "OK", 200

    except Exception as e:
        send_to_discord(f"❌ Błąd składania zlecenia: {e}")
        print(f"❌ Błąd: {e}")
        return "Order error", 500

if __name__ == "__main__":
    print("Bot uruchomiony...")  # Logowanie rozpoczęcia działania bota
    app.run(host="0.0.0.0", port=5000)
