import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
import logging
import time

import data_fetcher
import strategy
import config

# Configuración de logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Configuración del entrenamiento
LOOK_AHEAD = 12       # 1 hora (12 velas de 5m)
TARGET_PROFIT = 0.01  # 1%
STOP_LOSS_LIMIT = 0.01 # 1% (Ratio 1:1 para facilitar el aprendizaje inicial)

def fetch_large_history(symbol, interval, total_candles=5000):
    """Descarga un historial extenso de velas usando bucles."""
    all_klines = []
    last_timestamp = None
    
    # Binance permite 1000 por petición
    batches = (total_candles // 1000) + 1
    
    for i in range(batches):
        limit = min(1000, total_candles - len(all_klines))
        if limit <= 0: break
        
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if last_timestamp:
            params["endTime"] = last_timestamp - 1
            
        # Usamos el cliente base para peticiones directas
        url = f"{config.BINANCE_BASE_URL}/api/v3/klines"
        r = data_fetcher.requests.get(url, params=params)
        data = r.json()
        
        if not data: break
        
        all_klines = data + all_klines # Añadir al principio
        last_timestamp = data[0][0] # El timestamp de la vela más vieja del lote
        logger.info(f"Descargados {len(all_klines)}/{total_candles} registros...")
        time.sleep(0.5) # Evitar rate limits

    df = pd.DataFrame(all_klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])[["timestamp", "open", "high", "low", "close", "volume"]].copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df.sort_values("timestamp", inplace=True)
    return df

def prepare_ml_data(df):
    """
    Transforma el DataFrame en un conjunto de entrenamiento robusto.
    """
    # 1. Indicadores Base
    df = strategy.add_indicators(df)
    
    # 2. Nuevas Características (Features) para "Bajo Riesgo"
    # Volatilidad (ATR simplificado)
    df["range"] = (df["high"] - df["low"]) / df["close"]
    df["volatility"] = df["range"].rolling(window=10).mean()
    
    # Momentum de volumen
    df["vol_change"] = df["volume"].pct_change(5)
    
    # Normalización de indicadores
    df["ema_dist"] = (df["ema_fast"] - df["ema_slow"]) / df["ema_slow"]
    df["price_dist_ema"] = (df["close"] - df["ema_fast"]) / df["ema_fast"]
    
    # 3. Etiquetado Triple-Barrera (Simplificado)
    # 1 si llega al profit antes que al stop o antes de que pase el tiempo
    def label_row(i):
        if i + LOOK_AHEAD >= len(df): return np.nan
        future_prices = df["close"].iloc[i+1 : i+LOOK_AHEAD+1].values
        entry_price = df["close"].iloc[i]
        
        # ¿Tocó el Stop Loss antes?
        if np.any(future_prices < entry_price * (1 - STOP_LOSS_LIMIT)):
            return 0
        # ¿Tocó el Take Profit?
        if np.any(future_prices > entry_price * (1 + TARGET_PROFIT)):
            return 1
        return 0

    logger.info("Etiquetando datos (esto puede tardar)...")
    df["target"] = [label_row(i) for i in range(len(df))]
    
    df.dropna(inplace=True)
    
    features = [
        "rsi", "macd_hist", "volume_ratio", 
        "ema_dist", "price_dist_ema", "volatility", "vol_change"
    ]
    
    X = df[features]
    y = df["target"]
    
    return X, y

def train_model():
    logger.info(f"Iniciando entrenamiento avanzado para {config.SYMBOL}...")
    
    # Paso 1: Obtener muchos datos (10,000 velas = ~1 mes de datos 5m)
    df = fetch_large_history(config.SYMBOL, config.INTERVAL, total_candles=10000)
    
    # Paso 2: Preparar
    X, y = prepare_ml_data(df)
    
    # Ver balance de clases
    counts = y.value_counts()
    logger.info(f"Balance de clases: 0 (No entrar): {counts.get(0,0)}, 1 (Entrar): {counts.get(1,0)}")
    
    # Paso 3: Entrenar con balanceo de peso
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)
    
    # Usamos class_weight='balanced' para que la IA dé más importancia a los "1" (las ganancias)
    model = RandomForestClassifier(
        n_estimators=200, 
        max_depth=12, 
        class_weight="balanced", 
        random_state=42
    )
    
    model.fit(X_train, y_train)
    
    # Evaluación
    y_pred = model.predict(X_test)
    logger.info("\n" + classification_report(y_test, y_pred))
    
    joblib.dump(model, "trading_model.pkl")
    logger.info("¡Modelo optimizado guardado!")
    
    return model

if __name__ == "__main__":
    train_model()
