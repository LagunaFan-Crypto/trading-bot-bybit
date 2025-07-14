@app.route("/webhook", methods=["POST"])
def webhook():
    """Obsługuje przychodzący webhook z TradingView."""
    try:
        data = request.get_json()
        print(f"🔔 Otrzymano webhook: {data}")  # Logowanie otrzymanych danych
        action = data.get("action", "").lower()

        # Upewnij się, że tylko jeden sygnał jest przetwarzany
        if action not in ["buy", "sell"]:
            send_to_discord("⚠️ Nieprawidłowe polecenie. Użyj 'buy' lub 'sell'.")
            return "Invalid action", 400

        # Sprawdzamy, czy istnieją otwarte pozycje
        position_size, position_side = get_current_position(SYMBOL)

        # Jeśli pozycja jest otwarta, najpierw ją zamykamy
        if position_size > 0:
            position_size = round(position_size, 2)
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
                
                # Sprawdzamy status pozycji po zamknięciu
                position_size, _ = get_current_position(SYMBOL)
                if position_size > 0:
                    send_to_discord(f"⚠️ Pozycja nadal otwarta po zamknięciu. Będziemy próbować ponownie.")
                    return "Position still open", 400
                else:
                    print("Pozycja zamknięta, kontynuujemy.")
                
            except Exception as e:
                send_to_discord(f"⚠️ Błąd zamykania pozycji: {e}")
                return "Order error", 500
        else:
            send_to_discord("⚠️ Brak otwartej pozycji, nie można zamknąć pozycji.")

        # Sprawdzamy stan konta i obliczamy kwotę potrzebną do złożenia zlecenia
        qty = calculate_qty(SYMBOL)
        if qty is None or qty < 0.01:
            send_to_discord(f"⚠️ Obliczona ilość to {qty}. Zbyt mało środków na zlecenie.")
            return "Qty error", 400

        # Składamy zlecenie (Buy/Sell) tylko, jeśli pozycja została zamknięta lub nie istnieje
        if position_size == 0:  # Zlecenie tylko, gdy pozycja jest zamknięta
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
        else:
            send_to_discord(f"⚠️ Pozycja nie została jeszcze zamknięta, nie składamy nowego zlecenia.")

        return "OK", 200

    except Exception as e:
        send_to_discord(f"❌ Błąd składania zlecenia: {e}")
        print(f"❌ Błąd: {e}")  # Logowanie błędu
        return "Order error", 500
