def round_to_precision(value, precision=2):
    """Funkcja do zaokrąglania wartości do określonej liczby miejsc po przecinku (domyślnie 2)."""
    return round(value, precision)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        print(f"🔔 Otrzymano webhook: {data}")  # Logowanie otrzymanych danych
        action = data.get("action", "").lower()

        if action not in ["buy", "sell"]:
            send_to_discord("⚠️ Nieprawidłowe polecenie. Użyj 'buy' lub 'sell'.")
            return "Invalid action", 400

        # 1. Sprawdzamy, czy istnieją otwarte pozycje
        position_size, position_side = get_current_position(SYMBOL)

        # 2. Jeśli istnieją otwarte pozycje, zamykamy je
        if position_size > 0:
            # Zaokrąglamy wartość pozycji do 2 miejsc po przecinku
            position_size = round_to_precision(position_size)

            # Upewniamy się, że rozmiar pozycji jest większy niż minimalna wielkość (np. 0.01)
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
                print(f"Zamknięcie pozycji: {close_order}")  # Logowanie zamknięcia pozycji
                send_to_discord(f"🔒 Zamknięcie pozycji {position_side.upper()} ({position_size} {SYMBOL})")
            except Exception as e:
                send_to_discord(f"⚠️ Błąd zamykania pozycji: {e}")
                return "Order error", 500
        else:
            send_to_discord(f"⚠️ Brak otwartej pozycji, nie można zamknąć pozycji {position_side.upper()}.")

        # 3. Sprawdzamy stan konta i obliczamy kwotę potrzebną do złożenia zlecenia
        qty = calculate_qty(SYMBOL)
        if qty is None or qty < 0.01:
            send_to_discord(f"⚠️ Obliczona ilość to {qty}. Zbyt mało środków na zlecenie.")
            return "Qty error", 400

        # Zaokrąglamy ilość do dwóch miejsc po przecinku
        qty = round_to_precision(qty)

        # 4. Składamy zlecenie (Buy/Sell)
        new_side = "Buy" if action == "buy" else "Sell"
        new_order = session.place_order(
            category="linear",
            symbol=SYMBOL,
            side=new_side,
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel"
        )
        print(f"Nowe zlecenie: {new_order}")  # Logowanie nowego zlecenia
        send_to_discord(f"✅ {new_side.upper()} zlecenie złożone: {qty} {SYMBOL}")

        return "OK", 200

    except Exception as e:
        send_to_discord(f"❌ Błąd składania zlecenia: {e}")
        print(f"❌ Błąd: {e}")  # Logowanie błędu
        return "Order error", 500
