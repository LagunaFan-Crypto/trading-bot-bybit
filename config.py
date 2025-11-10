# ======================
# 🔑 USTAWIENIA API BYBIT
# ======================
API_KEY = "fMqmICCnGQtafLBuKf"
API_SECRET = "ySpYC00YLtn3dLQENrkBM0txN2xlvGK9aLlB"

# ======================
# ⚙️ PARAMETRY BOTA
# ======================
SYMBOL = "WIFUSDT"  # Domyślny symbol
ALLOWED_SYMBOLS = ["WIFUSDT", "COAIUSDT", "ZECUSDT","ZKUSDT","NEARUSDT"]  # Lista dozwolonych symboli
TESTNET = False  # False = konto realne, True = testnet

# ======================
# 💬 POWIADOMIENIA
# ======================
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1392636936723763210/nf-ZLx2Tz_nlen9eDwUeeTiiLDSlVR6yRvNGILNFLLpNsOJiXJxyO5EHD5DGhqQ4U2SZ"

# ======================
# 💰 DOMYŚLNY TRYB HANDLU
# ======================
# Bot używa tych wartości tylko wtedy,
# jeśli strategia NIE przekaże "mode" i "value" w webhooku.
POSITION_MODE = "PERCENT"   # "PERCENT" lub "SIZE"
POSITION_VALUE = 1.0        # 1.0 = 100% kapitału lub np. 100 = 100 sztuk w trybie SIZE

LEVERAGE = 5           # dźwignia dla kontraktów linear
AUTOSCALE_QTY = True   # automatycznie zmniejsz ilość, gdy brakuje marginu
SAFETY_MARGIN = 0.95   # nie używaj 100% dostępnego marginu
