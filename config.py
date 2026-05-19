# ============================================================
#  SOL MOMENTUM SURGE - CONFIG
#  Estrategia: Momentum Scalping con filtros de volumen
#  Par: SOL/USDT | Timeframe: 5m | Exchange: Binance Testnet
# ============================================================

import os
from dotenv import load_dotenv

# Carga las variables del archivo .env (nunca hardcodear claves)
load_dotenv()

# --- Credenciales Binance (desde .env) ---
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# --- Modo de operación ---
# USE_TESTNET=True  → Binance Spot Testnet (testnet.binance.vision)
# USE_TESTNET=False → Producción real (¡cuidado!)
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
KLINES_LIMIT    = 200          # velas a traer por request

# --- Indicadores Técnicos ---
EMA_FAST        = 9
EMA_SLOW        = 21
RSI_PERIOD      = 14
RSI_LONG_MIN    = 55           # RSI mínimo para entrada LONG
RSI_SHORT_MAX   = 45           # RSI máximo para entrada SHORT
RSI_OVERBOUGHT  = 75           # evitar entradas largas aquí
RSI_OVERSOLD    = 25           # evitar entradas cortas aquí
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9
VOLUME_SMA      = 20
VOLUME_MULT     = 1.5          # volumen debe ser >= 1.5x promedio

# --- Gestión de Riesgo ---
# El capital se sincroniza con la cuenta real al iniciar.
# CAPITAL_USDT se usa solo como fallback si no hay conexión.
CAPITAL_USDT    = 1000.0
RISK_PER_TRADE  = 0.01         # 1% del capital por operación
TAKE_PROFIT_PCT = 0.015        # 1.5% take profit
STOP_LOSS_PCT   = 0.008        # 0.8%  stop loss
MAX_DAILY_LOSS  = 0.03         # detener si pierde 3% en el día
MAX_OPEN_TRADES = 1            # solo 1 posición abierta a la vez

# Precisión de SOL/USDT en Binance (stepSize y tickSize)
# Binance exige redondear qty y price a estos valores
SOL_QTY_PRECISION   = 2       # decimales para cantidad (ej: 1.25 SOL)
SOL_PRICE_PRECISION = 2       # decimales para precio   (ej: 142.35)

# --- Flask Server ---
HOST            = "0.0.0.0"
PORT            = 5000
DEBUG           = False