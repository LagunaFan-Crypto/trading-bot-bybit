🚀 BOT TRADINGOWY WIFUSDT.P – BYBIT + DISCORD + RENDER

1. W pliku config.py uzupełnij:
   - API_KEY i API_SECRET z Bybit
   - SYMBOL = "WIFUSDT.P"
   - TESTNET = True lub False
   - DISCORD_WEBHOOK_URL z kanału Discord

2. Upewnij się, że plik requirements.txt zawiera:
   flask, requests, pybit

3. Ten projekt działa z Render.com:
   - Wybierz "Web Service"
   - Build command: pip install -r requirements.txt
   - Start command: python bot.py
   - Port: 10000 (ustaw na Render jako PORT ENV VAR)

4. Webhook: https://twoja-nazwa.onrender.com/webhook