# ============================================================
#  STRATEGY ENGINE - SOL MOMENTUM SURGE
#  Indicadores: EMA 9/21 · RSI 14 · MACD · Volume SMA 20
# ============================================================
#
#  REGLAS DE ENTRADA
#  -----------------
#  LONG:
#    1. EMA(9) cruza hacia ARRIBA la EMA(21) [golden cross]
#    2. RSI > RSI_LONG_MIN (55) → momentum alcista confirmado
#    3. RSI < RSI_OVERBOUGHT (75) → no entrar en zona extrema
#    4. Volumen actual >= 1.5x promedio de volumen (surge)
#    5. MACD line > Signal line (confluencia direccional)
#
#  SHORT:
#    1. EMA(9) cruza hacia ABAJO la EMA(21) [death cross]
#    2. RSI < RSI_SHORT_MAX (45) → momentum bajista confirmado
#    3. RSI > RSI_OVERSOLD (25) → no entrar en zona extrema
#    4. Volumen actual >= 1.5x promedio de volumen (surge)
#    5. MACD line < Signal line (confluencia direccional)
#
#  REGLAS DE SALIDA
#  ----------------
#    - Take Profit: precio sube/baja 1.5% desde entrada
#    - Stop Loss:   precio baja/sube 0.8% desde entrada
#    - Cierre técnico: EMA cruza en dirección opuesta
#
# ============================================================

import pandas as pd
import numpy as np
import config
import joblib
import os

# Intentar cargar el modelo de ML si existe
MODEL_PATH = "trading_model.pkl"
model = None
if os.path.exists(MODEL_PATH):
    try:
        model = joblib.load(MODEL_PATH)
    except:
        model = None

# ------------------------------------------------------------------
#  CÁLCULO DE INDICADORES
# ------------------------------------------------------------------

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(series: pd.Series,
                   fast: int = config.MACD_FAST,
                   slow: int = config.MACD_SLOW,
                   signal: int = config.MACD_SIGNAL):
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_volume_sma(volume: pd.Series, period: int = config.VOLUME_SMA) -> pd.Series:
    return volume.rolling(window=period).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega todos los indicadores al DataFrame de velas."""
    df = df.copy()

    # EMAs
    df["ema_fast"] = calculate_ema(df["close"], config.EMA_FAST)
    df["ema_slow"] = calculate_ema(df["close"], config.EMA_SLOW)

    # RSI
    df["rsi"] = calculate_rsi(df["close"], config.RSI_PERIOD)

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = calculate_macd(df["close"])

    # Volumen
    df["volume_sma"] = calculate_volume_sma(df["volume"])
    df["volume_ratio"] = df["volume"] / df["volume_sma"]

    # EMA cross detection
    df["ema_cross"] = np.sign(df["ema_fast"] - df["ema_slow"])
    df["ema_cross_prev"] = df["ema_cross"].shift(1)

    # Golden Cross: ema_fast cruza hacia arriba ema_slow
    df["golden_cross"] = (df["ema_cross"] == 1) & (df["ema_cross_prev"] == -1)

    # Death Cross: ema_fast cruza hacia abajo ema_slow
    df["death_cross"] = (df["ema_cross"] == -1) & (df["ema_cross_prev"] == 1)

    return df


def get_ml_prediction(row, df_recent):
    """Retorna la probabilidad de éxito según el modelo de ML."""
    if model is None:
        return 0.5
    
    # Calcular características de volatilidad y volumen (basadas en histórico reciente)
    recent_range = (df_recent["high"] - df_recent["low"]) / df_recent["close"]
    volatility = recent_range.tail(10).mean()
    
    vol_change = 0
    if len(df_recent) >= 6:
        old_vol = df_recent["volume"].iloc[-6]
        if old_vol > 0:
            vol_change = (df_recent["volume"].iloc[-1] - old_vol) / old_vol

    # Mismas características que en ml_trainer.py
    features = pd.DataFrame([{
        "rsi":          row["rsi"],
        "macd_hist":    row["macd_hist"],
        "volume_ratio": row["volume_ratio"],
        "ema_dist":     (row["ema_fast"] - row["ema_slow"]) / row["ema_slow"],
        "price_dist_ema": (row["close"] - row["ema_fast"]) / row["ema_fast"],
        "volatility":   volatility,
        "vol_change":   vol_change
    }])
    
    try:
        prob = model.predict_proba(features)[0][1]
        return float(prob)
    except:
        return 0.5


# ------------------------------------------------------------------
#  GENERACIÓN DE SEÑALES
# ------------------------------------------------------------------

SIGNAL_LONG  = "LONG"
SIGNAL_SHORT = "SHORT"
SIGNAL_FLAT  = "FLAT"


def generate_signal(df: pd.DataFrame, cfg: dict = None) -> dict:
    """
    Evalúa la última vela completa y retorna la señal de trading.
    Ahora incluye un filtro de Machine Learning avanzado.
    """
    # Usar config dinámica si se provee, sino la de config.py
    rsi_long_min = cfg.get("rsi_long_min", config.RSI_LONG_MIN) if cfg else config.RSI_LONG_MIN
    rsi_short_max = cfg.get("rsi_short_max", config.RSI_SHORT_MAX) if cfg else config.RSI_SHORT_MAX
    rsi_overbought = cfg.get("rsi_overbought", config.RSI_OVERBOUGHT) if cfg else config.RSI_OVERBOUGHT
    rsi_oversold = cfg.get("rsi_oversold", config.RSI_OVERSOLD) if cfg else config.RSI_OVERSOLD
    volume_mult = cfg.get("volume_mult", config.VOLUME_MULT) if cfg else config.VOLUME_MULT

    df_with_inds = add_indicators(df)
    row = df_with_inds.iloc[-2]
    
    # 1. Reglas Técnicas (Momentum)
    conditions_long = {
        "golden_cross":     bool(row["golden_cross"]),
        "rsi_above_min":    bool(row["rsi"] > rsi_long_min),
        "rsi_not_overbought": bool(row["rsi"] < rsi_overbought),
        "volume_surge":     bool(row["volume_ratio"] >= volume_mult),
        "macd_bullish":     bool(row["macd"] > row["macd_signal"]),
    }

    conditions_short = {
        "death_cross":      bool(row["death_cross"]),
        "rsi_below_max":    bool(row["rsi"] < rsi_short_max),
        "rsi_not_oversold":  bool(row["rsi"] > rsi_oversold),
        "volume_surge":     bool(row["volume_ratio"] >= volume_mult),
        "macd_bearish":     bool(row["macd"] < row["macd_signal"]),
    }

    rules_pass_long = all(conditions_long.values())
    rules_pass_short = all(conditions_short.values())
    
    # 2. Filtro de Machine Learning (usando el DataFrame completo para contexto)
    ml_prob = get_ml_prediction(row, df_with_inds.iloc[:-1])
    
    # Umbral dinámico: si las reglas técnicas son muy fuertes, bajamos un poco la exigencia de ML
    ml_threshold_long = 0.52 if rules_pass_long else 0.65
    ml_threshold_short = 0.48 if rules_pass_short else 0.35 # Inverso para short si prob es 0..1 para LONG
    
    # Nota: El modelo parece estar entrenado para predecir éxito de LONG.
    # Si ml_prob es bajo, podría indicar éxito de SHORT, pero depende de cómo se entrenó.
    # Por ahora mantendremos la lógica original para LONG y una simplificada para SHORT.
    
    signal = SIGNAL_FLAT
    if rules_pass_long and ml_prob >= ml_threshold_long:
        signal = SIGNAL_LONG
    elif ml_prob > 0.70:
        signal = SIGNAL_LONG
    elif rules_pass_short:
        # Si no tenemos un modelo específico para SHORT, confiamos en las reglas técnicas
        signal = SIGNAL_SHORT

    return {
        "signal": signal,
        "ml_confidence": round(ml_prob, 4),
        "conditions_long": conditions_long,
        "conditions_short": conditions_short,
        "indicators": {
            "ema_fast": round(float(row["ema_fast"]), 4),
            "ema_slow": round(float(row["ema_slow"]), 4),
            "rsi": round(float(row["rsi"]), 2),
            "macd": round(float(row["macd"]), 4),
            "macd_signal": round(float(row["macd_signal"]), 4),
            "volume_ratio": round(float(row["volume_ratio"]), 2),
            "close": round(float(row["close"]), 4),
        },
        "timestamp": str(row["timestamp"]),
    }



# ------------------------------------------------------------------
#  EVALUACIÓN DE CIERRE DE POSICIÓN
# ------------------------------------------------------------------

def check_exit(position: dict, current_price: float, df: pd.DataFrame) -> dict:
    """
    Evalúa si una posición abierta debe cerrarse.

    Parameters
    ----------
    position     : dict con 'side', 'entry_price'
    current_price: precio actual de mercado
    df           : DataFrame con velas recientes

    Returns
    -------
    dict con:
        should_exit : bool
        reason      : 'take_profit' | 'stop_loss' | 'ema_cross' | None
        pnl_pct     : float
    """
    side        = position["side"]
    entry_price = position["entry_price"]

    if side == SIGNAL_LONG:
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - current_price) / entry_price

    # Take Profit
    if pnl_pct >= config.TAKE_PROFIT_PCT:
        return {"should_exit": True, "reason": "take_profit", "pnl_pct": round(pnl_pct, 4)}

    # Stop Loss
    if pnl_pct <= -config.STOP_LOSS_PCT:
        return {"should_exit": True, "reason": "stop_loss", "pnl_pct": round(pnl_pct, 4)}

    # Cierre técnico: EMA cross opuesto
    df = add_indicators(df)
    last = df.iloc[-2]
    if side == SIGNAL_LONG and bool(last["death_cross"]):
        return {"should_exit": True, "reason": "ema_cross", "pnl_pct": round(pnl_pct, 4)}
    if side == SIGNAL_SHORT and bool(last["golden_cross"]):
        return {"should_exit": True, "reason": "ema_cross", "pnl_pct": round(pnl_pct, 4)}

    return {"should_exit": False, "reason": None, "pnl_pct": round(pnl_pct, 4)}


# ------------------------------------------------------------------
#  SERIALIZACIÓN DEL DATAFRAME PARA API
# ------------------------------------------------------------------

def dataframe_to_chart_data(df: pd.DataFrame) -> dict:
    """Convierte el DataFrame con indicadores a formato JSON para gráficas."""
    df = add_indicators(df).tail(100)

    def safe(series):
        return [None if pd.isna(v) else round(float(v), 4) for v in series]

    return {
        "timestamps":   [str(t) for t in df["timestamp"]],
        "open":         safe(df["open"]),
        "high":         safe(df["high"]),
        "low":          safe(df["low"]),
        "close":        safe(df["close"]),
        "volume":       safe(df["volume"]),
        "ema_fast":     safe(df["ema_fast"]),
        "ema_slow":     safe(df["ema_slow"]),
        "rsi":          safe(df["rsi"]),
        "macd":         safe(df["macd"]),
        "macd_signal":  safe(df["macd_signal"]),
        "macd_hist":    safe(df["macd_hist"]),
        "volume_sma":   safe(df["volume_sma"]),
        "volume_ratio": safe(df["volume_ratio"]),
    }
