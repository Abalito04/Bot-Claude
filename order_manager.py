# ============================================================
#  ORDER MANAGER
#  Ejecuta órdenes reales en Binance Testnet (o producción)
#  Maneja: MARKET · LIMIT · OCO (TP+SL combinado)
# ============================================================
#
#  FLUJO DE UNA OPERACIÓN COMPLETA:
#
#  1. Señal LONG/SHORT detectada
#  2. open_position() → orden MARKET de entrada
#  3. Binance confirma fill → guardamos precio real de ejecución
#  4. place_oco() → orden OCO (take profit + stop loss juntos)
#     Binance cancela automáticamente la que no se ejecuta
#  5. monitor_position() → chequea estado cada N segundos
#  6. close_position() → cancela OCO pendiente + orden MARKET de cierre
#
# ============================================================

import math
import logging
from datetime import datetime
from data_fetcher import (
    _post_private, _delete_private, _get_private,
    fetch_current_price, fetch_account_balance,
    fetch_exchange_info, fetch_open_orders
)
import config

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
#  HELPERS DE PRECISIÓN
# ------------------------------------------------------------------

def _round_step(value: float, step: float) -> float:
    """
    Redondea 'value' al múltiplo de 'step' más cercano hacia abajo.
    Binance rechaza órdenes que no cumplen con el stepSize/tickSize.
    """
    if not step or step <= 0:
        return value
    precision = int(round(-math.log(step, 10), 0)) if step < 1 else 0
    # Usar un pequeño epsilon para evitar errores de punto flotante
    return round(math.floor((value + 1e-10) / step) * step, precision)


def format_value(value: float, step: float) -> str:
    """Formatea un valor como string con la precisión correcta para Binance."""
    if not step or step <= 0:
        return str(value)
    precision = int(round(-math.log(step, 10), 0)) if step < 1 else 0
    return "{:0.{}f}".format(value, precision)


def get_symbol_filters() -> dict:
    """
    Obtiene y cachea los filtros de precisión del símbolo.
    Necesario antes de colocar cualquier orden.
    """
    try:
        info = fetch_exchange_info(config.SYMBOL)
        return info
    except Exception as e:
        logger.warning(f"No se pudo obtener filtros del símbolo: {e}. Usando defaults.")
        return {
            "step_size":    0.01,
            "tick_size":    0.01,
            "min_qty":      0.01,
            "min_notional": 5.0,
        }


# ------------------------------------------------------------------
#  ÓRDENES INDIVIDUALES
# ------------------------------------------------------------------

def place_market_order(side: str, quantity: float) -> dict:
    """
    Coloca una orden MARKET de entrada/salida.
    """
    filters = get_symbol_filters()
    qty_str = format_value(quantity, filters.get("step_size", 0.01))

    params = {
        "symbol":     config.SYMBOL,
        "side":       side,
        "type":       "MARKET",
        "quantity":   qty_str,
        "recvWindow": 10000
    }
    logger.info(f"ORDER MARKET {side} {qty_str} {config.SYMBOL}")
    response = _post_private("/api/v3/order", params)
    logger.info(f"Respuesta Binance: {response}")
    return response


def place_limit_order(side: str, quantity: float, price: float,
                      time_in_force: str = "GTC") -> dict:
    """
    Coloca una orden LIMIT.
    """
    filters = get_symbol_filters()
    qty_str = format_value(quantity, filters.get("step_size", 0.01))
    prc_str = format_value(price, filters.get("tick_size", 0.01))

    params = {
        "symbol":      config.SYMBOL,
        "side":        side,
        "type":        "LIMIT",
        "quantity":    qty_str,
        "price":       prc_str,
        "timeInForce": time_in_force,
        "recvWindow":  10000
    }
    logger.info(f"ORDER LIMIT {side} {qty_str} @ {prc_str}")
    return _post_private("/api/v3/order", params)


def place_oco_order(side: str, quantity: float,
                    price: float, stop_price: float,
                    stop_limit_price: float) -> dict:
    """
    Coloca una orden OCO para TP + SL simultáneo.
    """
    filters = get_symbol_filters()
    step = filters.get("step_size", 0.01)
    tick = filters.get("tick_size", 0.01)

    qty_str = format_value(quantity, step)
    prc_str = format_value(price, tick)
    stp_str = format_value(stop_price, tick)
    slm_str = format_value(stop_limit_price, tick)

    params = {
        "symbol":               config.SYMBOL,
        "side":                 side,
        "quantity":             qty_str,
        "price":                prc_str,           # TP limit price
        "stopPrice":            stp_str,           # SL trigger
        "stopLimitPrice":       slm_str,           # SL fill price
        "stopLimitTimeInForce": "GTC",
        "recvWindow":           10000
    }
    logger.info(
        f"ORDER OCO {side} {qty_str} | TP: {prc_str} | SL trigger: {stp_str} | SL limit: {slm_str}"
    )
    return _post_private("/api/v3/order/oco", params)


def cancel_order(order_id: int) -> dict:
    """Cancela una orden por su ID."""
    params = {"symbol": config.SYMBOL, "orderId": order_id}
    logger.info(f"CANCEL ORDER {order_id}")
    return _delete_private("/api/v3/order", params)


def cancel_oco_order(order_list_id: int) -> dict:
    """Cancela un grupo OCO por su orderListId."""
    params = {"symbol": config.SYMBOL, "orderListId": order_list_id}
    logger.info(f"CANCEL OCO {order_list_id}")
    return _delete_private("/api/v3/orderList", params)


def cancel_all_open_orders() -> list:
    """Cancela todas las órdenes abiertas del símbolo (para emergencias)."""
    params = {"symbol": config.SYMBOL}
    logger.warning("CANCELANDO TODAS LAS ÓRDENES ABIERTAS")
    return _delete_private("/api/v3/openOrders", params)


# ------------------------------------------------------------------
#  PRECIO PROMEDIO DE EJECUCIÓN
# ------------------------------------------------------------------

def get_avg_fill_price(order_response: dict) -> float:
    """
    Calcula el precio promedio ponderado de ejecución de una
    orden MARKET a partir de los 'fills' de la respuesta de Binance.
    """
    fills = order_response.get("fills", [])
    if not fills:
        return float(order_response.get("price", 0))

    total_qty  = sum(float(f["qty"]) for f in fills)
    total_cost = sum(float(f["price"]) * float(f["qty"]) for f in fills)

    return total_cost / total_qty if total_qty > 0 else 0.0


# ------------------------------------------------------------------
#  POSICIÓN COMPLETA (entrada + OCO automático)
# ------------------------------------------------------------------

def open_position(side: str, usdt_capital: float) -> dict:
    """
    Abre una posición completa:
      1. Calcula el tamaño (1% de riesgo)
      2. Coloca orden MARKET de entrada
      3. Calcula TP y SL basados en el fill real
      4. Coloca orden OCO de salida automática

    Parameters
    ----------
    side         : 'LONG' | 'SHORT'
    usdt_capital : capital disponible en USDT

    Returns
    -------
    dict con todos los detalles de la posición abierta
    """
    filters = get_symbol_filters()
    step    = float(filters.get("step_size", 0.01))
    tick    = float(filters.get("tick_size", 0.01))
    min_qty = float(filters.get("min_qty",   0.01))

    current_price = fetch_current_price()

    # Tamaño de posición (1% de riesgo / stop_loss_pct)
    risk_usdt     = usdt_capital * config.RISK_PER_TRADE
    raw_qty       = risk_usdt / (current_price * config.STOP_LOSS_PCT)
    quantity      = _round_step(raw_qty, step)

    if quantity < min_qty:
        raise ValueError(
            f"Cantidad calculada {quantity} SOL es menor al mínimo {min_qty}. "
            f"Aumentá el capital o ajustá el riesgo."
        )

    notional = quantity * current_price
    min_not  = float(filters.get("min_notional", 5.0))
    if notional < min_not:
        raise ValueError(f"Valor nocional {notional:.2f} USDT < mínimo {min_not} USDT")

    # Orden MARKET de entrada
    market_side = "BUY" if side == "LONG" else "SELL"
    entry_order = place_market_order(market_side, quantity)
    avg_price   = get_avg_fill_price(entry_order)

    if avg_price == 0:
        avg_price = current_price  # fallback

    # Calcular TP y SL sobre el precio real de ejecución
    if side == "LONG":
        tp_price  = _round_step(avg_price * (1 + config.TAKE_PROFIT_PCT), tick)
        sl_trigger= _round_step(avg_price * (1 - config.STOP_LOSS_PCT), tick)
        sl_limit  = _round_step(sl_trigger * 0.999, tick)   # 0.1% debajo del trigger
        oco_side  = "SELL"
    else:  # SHORT
        tp_price  = _round_step(avg_price * (1 - config.TAKE_PROFIT_PCT), tick)
        sl_trigger= _round_step(avg_price * (1 + config.STOP_LOSS_PCT), tick)
        sl_limit  = _round_step(sl_trigger * 1.001, tick)   # 0.1% arriba del trigger
        oco_side  = "BUY"

    # Orden OCO (TP + SL automáticos)
    oco_order = None
    oco_list_id = None
    try:
        oco_order   = place_oco_order(oco_side, quantity, tp_price, sl_trigger, sl_limit)
        oco_list_id = oco_order.get("orderListId")
        logger.info(f"OCO colocado correctamente. listId: {oco_list_id}")
    except Exception as e:
        logger.error(f"Error al colocar OCO: {e}. La posición está abierta SIN protección automática.")

    position = {
        "side":            side,
        "entry_price":     round(avg_price, config.SOL_PRICE_PRECISION),
        "quantity":        quantity,
        "position_value":  round(quantity * avg_price, 2),
        "risk_usdt":       round(risk_usdt, 2),
        "take_profit":     tp_price,
        "stop_loss":       sl_trigger,
        "oco_list_id":     oco_list_id,
        "entry_order_id":  entry_order.get("orderId"),
        "open_timestamp":  datetime.utcnow().isoformat(),
        "oco_active":      oco_list_id is not None,
    }

    return position


def close_position(position: dict, reason: str = "manual") -> dict:
    """
    Cierra una posición abierta:
      1. Cancela el OCO pendiente (si existe)
      2. Coloca orden MARKET de cierre

    Parameters
    ----------
    position : dict de la posición abierta
    reason   : motivo del cierre ('manual' | 'signal' | 'emergency')
    """
    # 1. Cancelar OCO si está activo
    if position.get("oco_active") and position.get("oco_list_id"):
        try:
            cancel_oco_order(position["oco_list_id"])
            logger.info(f"OCO {position['oco_list_id']} cancelado correctamente")
        except Exception as e:
            logger.warning(f"No se pudo cancelar OCO (puede ya haber ejecutado): {e}")

    # 2. Orden MARKET de cierre
    side     = position["side"]
    quantity = position["quantity"]
    close_side = "SELL" if side == "LONG" else "BUY"

    exit_order = place_market_order(close_side, quantity)
    exit_price = get_avg_fill_price(exit_order)

    if exit_price == 0:
        exit_price = fetch_current_price()

    # PnL
    entry = position["entry_price"]
    if side == "LONG":
        pnl_pct  = (exit_price - entry) / entry
    else:
        pnl_pct  = (entry - exit_price) / entry

    pnl_usdt = pnl_pct * position["position_value"]

    trade_record = {
        "side":           side,
        "entry_price":    entry,
        "exit_price":     round(exit_price, config.SOL_PRICE_PRECISION),
        "quantity":       quantity,
        "pnl_pct":        round(pnl_pct * 100, 3),
        "pnl_usdt":       round(pnl_usdt, 2),
        "exit_reason":    reason,
        "open_time":      position["open_timestamp"],
        "close_time":     datetime.utcnow().isoformat(),
        "exit_order_id":  exit_order.get("orderId"),
    }

    logger.info(
        f"CIERRE {side} | Precio: {exit_price} | "
        f"PnL: {pnl_usdt:+.2f} USDT ({pnl_pct*100:+.2f}%) | Motivo: {reason}"
    )

    return trade_record


# ------------------------------------------------------------------
#  MONITOREO DE OCO (detectar si ya ejecutó por TP o SL)
# ------------------------------------------------------------------

def check_oco_status(position: dict) -> dict:
    """
    Verifica si el OCO ya se ejecutó (TP o SL alcanzado por Binance).

    Returns
    -------
    dict con:
        executed : bool   → True si el OCO ya ejecutó
        reason   : str    → 'take_profit' | 'stop_loss' | None
        fill_price: float → precio de ejecución
    """
    if not position.get("oco_active") or not position.get("oco_list_id"):
        return {"executed": False, "reason": None, "fill_price": None}

    try:
        # Verificar si quedan órdenes abiertas del símbolo
        open_orders = fetch_open_orders(config.SYMBOL)
        open_ids    = {o["orderListId"] for o in open_orders if "orderListId" in o}

        if position["oco_list_id"] not in open_ids:
            # OCO ejecutado — determinar si fue TP o SL
            current = fetch_current_price()
            entry   = position["entry_price"]
            tp      = position["take_profit"]
            sl      = position["stop_loss"]

            if position["side"] == "LONG":
                reason = "take_profit" if current >= tp else "stop_loss"
            else:
                reason = "take_profit" if current <= tp else "stop_loss"

            logger.info(f"OCO ejecutado por: {reason}")
            return {"executed": True, "reason": reason, "fill_price": current}

    except Exception as e:
        logger.error(f"Error al verificar OCO: {e}")

    return {"executed": False, "reason": None, "fill_price": None}