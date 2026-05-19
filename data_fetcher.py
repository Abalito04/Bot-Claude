# ============================================================
#  DATA FETCHER
#  Obtiene datos OHLCV de Binance + endpoints autenticados
#  Soporta Testnet y Producción según config.USE_TESTNET
# ============================================================

import time
import hmac
import hashlib
import requests
import pandas as pd
import config


# ------------------------------------------------------------------
#  CLIENTE HTTP BASE
# ------------------------------------------------------------------

def _headers() -> dict:
    """Headers con API key para endpoints privados."""
    return {"X-MBX-APIKEY": config.BINANCE_API_KEY}


def _sign(params: dict) -> dict:
    """
    Agrega timestamp y firma HMAC-SHA256 a los parámetros.
    Requerido para todos los endpoints privados de Binance.
    """
    params["timestamp"] = int(time.time() * 1000)
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    signature = hmac.new(
        config.BINANCE_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = signature
    return params


def _get_public(endpoint: str, params: dict = None, timeout: int = 10):
    """Request GET sin autenticación."""
    url = f"{config.BINANCE_BASE_URL}{endpoint}"
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _get_private(endpoint: str, params: dict = None, timeout: int = 10):
    """Request GET con firma HMAC."""
    url = f"{config.BINANCE_BASE_URL}{endpoint}"
    signed = _sign(params or {})
    r = requests.get(url, params=signed, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post_private(endpoint: str, params: dict = None, timeout: int = 10):
    """Request POST con firma HMAC (para órdenes)."""
    url = f"{config.BINANCE_BASE_URL}{endpoint}"
    signed = _sign(params or {})
    r = requests.post(url, params=signed, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def _delete_private(endpoint: str, params: dict = None, timeout: int = 10):
    """Request DELETE con firma HMAC (para cancelar órdenes)."""
    url = f"{config.BINANCE_BASE_URL}{endpoint}"
    signed = _sign(params or {})
    r = requests.delete(url, params=signed, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------
#  DATOS DE MERCADO (públicos)
# ------------------------------------------------------------------

def fetch_klines(symbol: str = config.SYMBOL,
                 interval: str = config.INTERVAL,
                 limit: int = config.KLINES_LIMIT) -> pd.DataFrame:
    """Descarga velas OHLCV y las devuelve como DataFrame."""
    raw = _get_public("/api/v3/klines", {
        "symbol": symbol, "interval": interval, "limit": limit
    })

    df = pd.DataFrame(raw, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])[["timestamp", "open", "high", "low", "close", "volume"]].copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def fetch_current_price(symbol: str = config.SYMBOL) -> float:
    """Retorna el último precio de mercado."""
    data = _get_public("/api/v3/ticker/price", {"symbol": symbol})
    return float(data["price"])


def fetch_24h_stats(symbol: str = config.SYMBOL) -> dict:
    """Estadísticas de las últimas 24h."""
    data = _get_public("/api/v3/ticker/24hr", {"symbol": symbol})
    return {
        "price_change_pct": float(data["priceChangePercent"]),
        "high_24h":         float(data["highPrice"]),
        "low_24h":          float(data["lowPrice"]),
        "volume_24h":       float(data["volume"]),
        "last_price":       float(data["lastPrice"]),
    }


def fetch_exchange_info(symbol: str = config.SYMBOL) -> dict:
    """
    Obtiene stepSize y tickSize del símbolo.
    Necesario para redondear qty y price correctamente.
    """
    data = _get_public("/api/v3/exchangeInfo", {"symbol": symbol})
    filters = data["symbols"][0]["filters"]
    info = {}
    for f in filters:
        if f["filterType"] == "LOT_SIZE":
            info["step_size"]  = float(f["stepSize"])
            info["min_qty"]    = float(f["minQty"])
        if f["filterType"] == "PRICE_FILTER":
            info["tick_size"]  = float(f["tickSize"])
        if f["filterType"] == "MIN_NOTIONAL":
            info["min_notional"] = float(f.get("minNotional", 5))
    return info


# ------------------------------------------------------------------
#  CUENTA (privados, requieren firma)
# ------------------------------------------------------------------

def fetch_account_balance(asset: str = "USDT") -> float:
    """
    Retorna el balance libre (free) del asset en la cuenta.
    Usa el endpoint /api/v3/account (requiere API key + secret).
    """
    data = _get_private("/api/v3/account")
    for b in data.get("balances", []):
        if b["asset"] == asset:
            return float(b["free"])
    return 0.0


def fetch_all_balances() -> dict:
    """Retorna todos los balances con saldo > 0."""
    data = _get_private("/api/v3/account")
    return {
        b["asset"]: {"free": float(b["free"]), "locked": float(b["locked"])}
        for b in data.get("balances", [])
        if float(b["free"]) > 0 or float(b["locked"]) > 0
    }


def fetch_open_orders(symbol: str = config.SYMBOL) -> list:
    """Retorna las órdenes abiertas del símbolo."""
    return _get_private("/api/v3/openOrders", {"symbol": symbol})


def fetch_order_status(symbol: str, order_id: int) -> dict:
    """Estado de una orden específica por ID."""
    return _get_private("/api/v3/order", {"symbol": symbol, "orderId": order_id})


def fetch_trade_history(symbol: str = config.SYMBOL, limit: int = 20) -> list:
    """Últimas operaciones ejecutadas en la cuenta."""
    return _get_private("/api/v3/myTrades", {"symbol": symbol, "limit": limit})


def test_connectivity() -> bool:
    """Verifica que la conexión con Binance (testnet o prod) funciona."""
    try:
        _get_public("/api/v3/ping")
        return True
    except Exception:
        return False


def test_credentials() -> dict:
    """
    Verifica que las credenciales son válidas haciendo una llamada
    firmada simple. Retorna el balance USDT disponible.
    """
    try:
        balance = fetch_account_balance("USDT")
        return {"ok": True, "usdt_balance": balance}
    except Exception as e:
        return {"ok": False, "error": str(e)}