# ============================================================
#  RISK MANAGER
#  Gestión de capital, sizing y límites de pérdida
# ============================================================
#
#  REGLAS DE RIESGO:
#  • Riesgo por operación: 1% del capital
#  • Stop Loss: 0.8% → define el tamaño de la posición
#  • Tamaño = (Capital × 0.01) / (Precio × SL%)
#  • Límite de pérdida diaria: 3% del capital inicial
#  • Máximo 1 posición abierta simultánea
#  • Ratio Riesgo/Recompensa: 1 : 1.875 (SL 0.8% / TP 1.5%)
#
# ============================================================

from datetime import datetime, date
from typing import Optional
import config


class RiskManager:
    def __init__(self, initial_capital: float = config.CAPITAL_USDT):
        self.initial_capital  = initial_capital
        self.current_capital  = initial_capital
        self.daily_start_capital = initial_capital
        self.last_reset_date  = date.today()

        self.trade_history    = []       # lista de operaciones cerradas
        self.open_position    = None     # dict | None

        self.total_trades     = 0
        self.winning_trades   = 0
        self.losing_trades    = 0
        self.total_pnl_usdt   = 0.0

    # ------------------------------------------------------------------
    #  RESET DIARIO
    # ------------------------------------------------------------------

    def _check_daily_reset(self):
        """Reinicia el capital de referencia diario si cambió el día."""
        today = date.today()
        if today != self.last_reset_date:
            self.daily_start_capital = self.current_capital
            self.last_reset_date = today

    # ------------------------------------------------------------------
    #  CÁLCULO DE TAMAÑO DE POSICIÓN
    # ------------------------------------------------------------------

    def calculate_position_size(self, entry_price: float) -> dict:
        """
        Calcula el tamaño de la posición basado en el riesgo del 1%.

        Fórmula:
            risk_usdt   = capital × risk_pct
            position_sz = risk_usdt / (entry_price × stop_loss_pct)

        Returns
        -------
        dict con:
            position_size_sol  : cantidad de SOL a comprar/vender
            position_value_usdt: valor en USDT de la posición
            risk_usdt          : USDT en riesgo
            tp_price           : precio de take profit
            sl_price           : precio de stop loss
        """
        risk_usdt     = self.current_capital * config.RISK_PER_TRADE
        position_size = risk_usdt / (entry_price * config.STOP_LOSS_PCT)
        position_value = position_size * entry_price

        return {
            "position_size_sol":   round(position_size, 4),
            "position_value_usdt": round(position_value, 2),
            "risk_usdt":           round(risk_usdt, 2),
            "tp_price_long":  round(entry_price * (1 + config.TAKE_PROFIT_PCT), 4),
            "sl_price_long":  round(entry_price * (1 - config.STOP_LOSS_PCT), 4),
            "tp_price_short": round(entry_price * (1 - config.TAKE_PROFIT_PCT), 4),
            "sl_price_short": round(entry_price * (1 + config.STOP_LOSS_PCT), 4),
        }

    # ------------------------------------------------------------------
    #  VERIFICACIONES PREVIAS A APERTURA
    # ------------------------------------------------------------------

    def can_open_trade(self) -> dict:
        """
        Verifica si se puede abrir una nueva operación.

        Returns
        -------
        dict con:
            allowed : bool
            reason  : str | None
        """
        self._check_daily_reset()

        # Ya hay una posición abierta
        if self.open_position is not None:
            return {"allowed": False, "reason": "Ya hay una posición abierta"}

        # Límite de pérdida diaria
        daily_loss = (self.daily_start_capital - self.current_capital) / self.daily_start_capital
        if daily_loss >= config.MAX_DAILY_LOSS:
            return {
                "allowed": False,
                "reason": f"Límite de pérdida diaria alcanzado ({daily_loss*100:.2f}%)"
            }

        # Capital insuficiente (< 10 USDT como mínimo)
        if self.current_capital < 10:
            return {"allowed": False, "reason": "Capital insuficiente"}

        return {"allowed": True, "reason": None}

    # ------------------------------------------------------------------
    #  APERTURA DE POSICIÓN
    # ------------------------------------------------------------------

    def open_trade(self, side: str, entry_price: float, timestamp: str) -> dict:
        """
        Registra la apertura de una posición.

        Parameters
        ----------
        side        : 'LONG' | 'SHORT'
        entry_price : precio de entrada
        timestamp   : timestamp de la señal
        """
        sizing = self.calculate_position_size(entry_price)
        tp = sizing["tp_price_long"] if side == "LONG" else sizing["tp_price_short"]
        sl = sizing["sl_price_long"] if side == "LONG" else sizing["sl_price_short"]

        self.open_position = {
            "side":            side,
            "entry_price":     entry_price,
            "position_size":   sizing["position_size_sol"],
            "position_value":  sizing["position_value_usdt"],
            "risk_usdt":       sizing["risk_usdt"],
            "take_profit":     tp,
            "stop_loss":       sl,
            "open_timestamp":  timestamp,
        }

        return self.open_position

    # ------------------------------------------------------------------
    #  CIERRE DE POSICIÓN
    # ------------------------------------------------------------------

    def close_trade(self, exit_price: float, exit_reason: str, timestamp: str) -> dict:
        """
        Cierra la posición abierta y actualiza el capital.

        Returns
        -------
        dict con el registro completo de la operación.
        """
        if self.open_position is None:
            raise ValueError("No hay posición abierta para cerrar")

        pos   = self.open_position
        side  = pos["side"]
        entry = pos["entry_price"]
        size  = pos["position_size"]

        if side == "LONG":
            pnl_pct  = (exit_price - entry) / entry
        else:
            pnl_pct  = (entry - exit_price) / entry

        pnl_usdt = pnl_pct * pos["position_value"]
        self.current_capital += pnl_usdt
        self.total_pnl_usdt  += pnl_usdt
        self.total_trades    += 1

        if pnl_usdt > 0:
            self.winning_trades += 1
        else:
            self.losing_trades  += 1

        trade_record = {
            "id":             self.total_trades,
            "side":           side,
            "entry_price":    round(entry, 4),
            "exit_price":     round(exit_price, 4),
            "position_size":  size,
            "pnl_pct":        round(pnl_pct * 100, 3),
            "pnl_usdt":       round(pnl_usdt, 2),
            "capital_after":  round(self.current_capital, 2),
            "exit_reason":    exit_reason,
            "open_time":      pos["open_timestamp"],
            "close_time":     timestamp,
        }

        self.trade_history.append(trade_record)
        self.open_position = None

        return trade_record

    # ------------------------------------------------------------------
    #  ESTADÍSTICAS
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Retorna un resumen completo del rendimiento."""
        self._check_daily_reset()

        win_rate = (self.winning_trades / self.total_trades * 100
                    if self.total_trades > 0 else 0)

        daily_loss = (self.daily_start_capital - self.current_capital) / self.daily_start_capital
        daily_pnl  = self.current_capital - self.daily_start_capital

        return {
            "capital_initial":   round(self.initial_capital, 2),
            "capital_current":   round(self.current_capital, 2),
            "total_pnl_usdt":    round(self.total_pnl_usdt, 2),
            "total_pnl_pct":     round(self.total_pnl_usdt / self.initial_capital * 100, 3),
            "daily_pnl_usdt":    round(daily_pnl, 2),
            "daily_pnl_pct":     round(-daily_loss * 100, 3),
            "daily_limit_pct":   config.MAX_DAILY_LOSS * 100,
            "total_trades":      self.total_trades,
            "winning_trades":    self.winning_trades,
            "losing_trades":     self.losing_trades,
            "win_rate":          round(win_rate, 1),
            "risk_reward_ratio": f"1:{config.TAKE_PROFIT_PCT / config.STOP_LOSS_PCT:.2f}",
            "open_position":     self.open_position,
            "trade_history":     self.trade_history[-20:],  # últimas 20
        }
