def webhook():
    try:
        data = request.get_json()
        print(f"🔔 Otrzymano webhook: {data}")  # Logowanie otrzymanych danych
        action = data.get("action", "").lower()

        if action not in ["buy", "sell"]:
            send_to_discord("⚠️ Nieprawidłowe polecenie. Użyj 'buy' lub 'sell'.")
            return "Invalid action", 400

        qty = calculate_qty(SYMBOL)
        if qty is None:
            return "Qty error", 400

        position_size, position_side = get_current_position(SYMBOL)

        # 🔒 Sprawdzanie, czy pozycja jest otwarta przed zamknięciem
        if position_size > 0:
            close_side = "Buy" if position_side == "Sell" else "Sell"
            # Zamykamy pozycję tylko jeśli rozmiar pozycji jest większy niż 0
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

        # 🟢 Otwórz nową pozycję zgodnie z kierunkiem strategii
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
