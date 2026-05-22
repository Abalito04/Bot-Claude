# ============================================================
#  SOL MOMENTUM SURGE - CONFIG
#  Estrategia: Momentum Scalping con filtros de volumen
#  Par: SOL/USDT | Timeframe: 5m | Exchange: Binance Testnet
# ============================================================

import os
import json
from dotenv import load_dotenv

# Carga las variables del archivo .env (nunca hardcodear claves)
load_dotenv()

# --- Cargar Configuración Dinámica ---
def load_dynamic_config():
    with open("config.json", "r") as f:
        return json.load(f)

DYNAMIC = load_dynamic_config()

# --- Credenciales Binance (desde .env) ---
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# --- Modo de operación ---
USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

# URLs según el modo
if USE_TESTNET:
    BINANCE_BASE_URL    = "https://testnet.binance.vision"
    BINANCE_WS_URL      = "wss://testnet.binance.vision/ws"
else:
    BINANCE_BASE_URL    = "https://api.binance.com"
    BINANCE_WS_URL      = "wss://stream.binance.com:9443/ws"

# --- Exchange & Par ---
EXCHANGE        = "binance"
SYMBOL          = "SOLUSDT"
SYMBOL_DISPLAY  = "SOL/USDT"
INTERVAL        = "5m"
KLINES_LIMIT    = 200

# --- Indicadores Técnicos (dinámicos) ---
EMA_FAST        = DYNAMIC["ema_fast"]
EMA_SLOW        = DYNAMIC["ema_slow"]
RSI_PERIOD      = DYNAMIC["rsi_period"]
RSI_LONG_MIN    = DYNAMIC["rsi_long_min"]
RSI_SHORT_MAX   = DYNAMIC["rsi_short_max"]
RSI_OVERBOUGHT  = DYNAMIC["rsi_overbought"]
RSI_OVERSOLD    = DYNAMIC["rsi_oversold"]
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9
VOLUME_SMA      = 20
VOLUME_MULT     = DYNAMIC["volume_mult"]

# --- Gestión de Riesgo (dinámicos) ---
CAPITAL_USDT    = DYNAMIC["capital_usdt"]
RISK_PER_TRADE  = DYNAMIC["risk_per_trade"]
TAKE_PROFIT_PCT = DYNAMIC["take_profit_pct"]
STOP_LOSS_PCT   = DYNAMIC["stop_loss_pct"]
MAX_DAILY_LOSS  = 0.03
MAX_OPEN_TRADES = 1

# Precisión de SOL/USDT
SOL_QTY_PRECISION   = 2
SOL_PRICE_PRECISION = 2

# --- Flask Server ---
HOST            = "0.0.0.0"
PORT            = 5000
DEBUG           = False