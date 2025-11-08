# ======================
# 🔑 USTAWIENIA API BYBIT
# ======================
API_KEY = "fMqmICCnGQtafLBuKf"
API_SECRET = "ySpYC00YLtn3dLQENrkBM0txN2xlvGK9aLlB"

# ======================
# ⚙️ PARAMETRY BOTA
# ======================
SYMBOL = "WIFUSDT"  # Domyślny symbol
ALLOWED_SYMBOLS = ["WIFUSDT", "COAIUSDT", "ZECUSDT"]  # Lista dozwolonych symboli
TESTNET = False  # False = konto realne, True = testnet

# ======================
# 💬 POWIADOMIENIA
# ======================
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1392636936723763210/nf-ZLx2Tz_nlen9eDwUeeTiiLDSlVR6yRvNGILNFLLpNsOJiXJxyO5EHD5DGhqQ4U2SZ"

# ======================
# 💰 WIELKOŚĆ POZYCJI
# ======================
# Tryb obliczania wielkości pozycji:
# - "PERCENT" → procent dostępnego kapitału (np. 1.0 = 100%, 0.5 = 50%)
# - "SIZE"    → stała liczba jednostek (np. 100 COAI)
POSITION_MODE = "PERCENT"

# Wartość dla wybranego trybu
# Jeśli POSITION_MODE = "PERCENT" → 1.0 = 100% kapitału
# Jeśli POSITION_MODE = "SIZE" → np. 100 = 100 COAI
POSITION_VALUE = 1.0
