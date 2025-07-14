# Zmienna śledząca, czy zlecenie zostało już złożone
order_in_progress = False

@app.route("/webhook", methods=["POST"])
def webhook():
    global last_action, order_in_progress  # Używamy zmiennej globalnej dla flagi

    try:
        data = request.get_json()
        print(f"🔔 Otrzymano webhook: {data}")
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

        # 2. Jeśli pozycja jest zamknięta, możemy złożyć nowe zlecenie
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
