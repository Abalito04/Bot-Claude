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
#  • Comisiones: 0.1% por lado (0.2% round-trip)
#  • Trailing stop: se activa al 50% del TP
#  • Circuit breaker: pausa tras 3 pérdidas consecutivas
#  • Drawdown máximo acumulado: 10% desde capital máximo
#
# ============================================================

from datetime import datetime, date, timedelta
from typing import Optional
import config
import json
import os
import logging

COMMISSION_PCT = 0.001
STATE_FILE     = "state.json"

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, initial_capital: float = config.CAPITAL_USDT):
        self.initial_capital      = initial_capital
        self.current_capital      = initial_capital
        self.peak_capital         = initial_capital
        self.daily_start_capital  = initial_capital
        self.last_reset_date      = date.today()

        self.trade_history        = []
        self.open_position        = None

        self.total_trades         = 0
        self.winning_trades       = 0
        self.losing_trades        = 0
        self.total_pnl_usdt       = 0.0
        self.total_fees_usdt      = 0.0

        self.consecutive_losses   = 0
        self.pause_until          = None

    # ------------------------------------------------------------------
    #  PERSISTENCIA DE ESTADO
    # ------------------------------------------------------------------

    def save_state(self) -> None:
        """Persiste el estado crítico en disco (state.json)."""
        state = {
            "current_capital":     self.current_capital,
            "peak_capital":        self.peak_capital,
            "daily_start_capital": self.daily_start_capital,
            "last_reset_date":     self.last_reset_date.isoformat(),
            "open_position":       self.open_position,
            "total_trades":        self.total_trades,
            "winning_trades":      self.winning_trades,
            "losing_trades":       self.losing_trades,
            "total_pnl_usdt":      self.total_pnl_usdt,
            "total_fees_usdt":     self.total_fees_usdt,
            "consecutive_losses":  self.consecutive_losses,
            "trade_history":       self.trade_history,
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error guardando estado: {e}")

    def load_state(self) -> bool:
        """
        Carga el estado desde disco si existe.
        Retorna True si se cargó correctamente.
        """
        if not os.path.exists(STATE_FILE):
            logger.info("No hay state.json — arrancando desde cero.")
            return False
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)

            self.current_capital     = state["current_capital"]
            self.peak_capital        = state["peak_capital"]
            self.daily_start_capital = state["daily_start_capital"]
            self.last_reset_date     = date.fromisoformat(state["last_reset_date"])
            self.open_position       = state["open_position"]
            self.total_trades        = state["total_trades"]
            self.winning_trades      = state["winning_trades"]
            self.losing_trades       = state["losing_trades"]
            self.total_pnl_usdt      = state["total_pnl_usdt"]
            self.total_fees_usdt     = state["total_fees_usdt"]
            self.consecutive_losses  = state["consecutive_losses"]
            self.trade_history       = state["trade_history"]

            if self.open_position:
                logger.warning(
                    f"⚠️  Posición abierta recuperada: {self.open_position['side']} "
                    f"@ {self.open_position['entry_price']} — verificar OCO en Binance"
                )
            logger.info(f"Estado cargado — Capital: {self.current_capital} USDT | Trades: {self.total_trades}")
            return True

        except Exception as e:
            logger.error(f"Error cargando estado: {e} — arrancando desde cero")
            return False

    # ------------------------------------------------------------------
    #  RESET DIARIO
    # ------------------------------------------------------------------

    def _check_daily_reset(self):
        """Reinicia el capital de referencia diario si cambió el día."""
        today = date.today()
        if today != self.last_reset_date:
            self.daily_start_capital  = self.current_capital
            self.last_reset_date      = today
            self.consecutive_losses   = 0
            self.pause_until          = None

    # ------------------------------------------------------------------
    #  CÁLCULO DE TAMAÑO DE POSICIÓN
    # ------------------------------------------------------------------

    def calculate_position_size(self, entry_price: float) -> dict:
        fee_entry      = entry_price * COMMISSION_PCT
        risk_usdt      = self.current_capital * config.RISK_PER_TRADE
        position_size  = risk_usdt / (entry_price * config.STOP_LOSS_PCT)
        position_value = position_size * entry_price

        trailing_activation_long  = round(entry_price * (1 + config.TAKE_PROFIT_PCT * 0.5), 4)
        trailing_activation_short = round(entry_price * (1 - config.TAKE_PROFIT_PCT * 0.5), 4)

        return {
            "position_size_sol":          round(position_size, 4),
            "position_value_usdt":        round(position_value, 2),
            "risk_usdt":                  round(risk_usdt, 2),
            "tp_price_long":              round(entry_price * (1 + config.TAKE_PROFIT_PCT), 4),
            "sl_price_long":              round(entry_price * (1 - config.STOP_LOSS_PCT), 4),
            "tp_price_short":             round(entry_price * (1 - config.TAKE_PROFIT_PCT), 4),
            "sl_price_short":             round(entry_price * (1 + config.STOP_LOSS_PCT), 4),
            "trailing_activation_long":   trailing_activation_long,
            "trailing_activation_short":  trailing_activation_short,
            "breakeven_price_long":       round(entry_price * (1 + COMMISSION_PCT * 2), 4),
            "breakeven_price_short":      round(entry_price * (1 - COMMISSION_PCT * 2), 4),
        }

    # ------------------------------------------------------------------
    #  VERIFICACIONES PREVIAS A APERTURA
    # ------------------------------------------------------------------

    def can_open_trade(self) -> dict:
        self._check_daily_reset()

        if self.pause_until and datetime.now() < self.pause_until:
            remaining = (self.pause_until - datetime.now()).seconds // 60
            return {
                "allowed": False,
                "reason": f"Circuit breaker activo — pausa de {remaining} min restantes (3 pérdidas consecutivas)"
            }

        if self.open_position is not None:
            return {"allowed": False, "reason": "Ya hay una posición abierta"}

        daily_loss = (self.daily_start_capital - self.current_capital) / self.daily_start_capital
        if daily_loss >= config.MAX_DAILY_LOSS:
            return {
                "allowed": False,
                "reason": f"Límite de pérdida diaria alcanzado ({daily_loss*100:.2f}%)"
            }

        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        if drawdown >= 0.10:
            return {
                "allowed": False,
                "reason": f"Drawdown máximo alcanzado ({drawdown*100:.2f}% desde el pico)"
            }

        if self.current_capital < 10:
            return {"allowed": False, "reason": "Capital insuficiente (< 10 USDT)"}

        return {"allowed": True, "reason": None}

    # ------------------------------------------------------------------
    #  APERTURA DE POSICIÓN
    # ------------------------------------------------------------------

    def open_trade(self, side: str, entry_price: float, timestamp: str) -> dict:
        sizing = self.calculate_position_size(entry_price)
        tp = sizing["tp_price_long"]  if side == "LONG"  else sizing["tp_price_short"]
        sl = sizing["sl_price_long"]  if side == "LONG"  else sizing["sl_price_short"]
        trailing_activation = sizing["trailing_activation_long"] if side == "LONG" else sizing["trailing_activation_short"]

        fee_entry = sizing["position_value_usdt"] * COMMISSION_PCT
        self.current_capital  -= fee_entry
        self.total_fees_usdt  += fee_entry

        self.open_position = {
            "side":                 side,
            "entry_price":         entry_price,
            "position_size":       sizing["position_size_sol"],
            "position_value":      sizing["position_value_usdt"],
            "risk_usdt":           sizing["risk_usdt"],
            "take_profit":         tp,
            "stop_loss":           sl,
            "trailing_activation": trailing_activation,
            "trailing_active":     False,
            "open_timestamp":      timestamp,
            "fee_entry":           round(fee_entry, 4),
            "oco_list_id":         None,
            "oco_active":          False,
        }

        self.save_state()
        return self.open_position

    # ------------------------------------------------------------------
    #  ACTUALIZAR TRAILING STOP
    # ------------------------------------------------------------------

    def update_trailing_stop(self, current_price: float) -> None:
        if self.open_position is None:
            return

        pos  = self.open_position
        side = pos["side"]

        if not pos["trailing_active"]:
            if side == "LONG" and current_price >= pos["trailing_activation"]:
                pos["stop_loss"]       = round(pos["entry_price"] * (1 + COMMISSION_PCT * 2), 4)
                pos["trailing_active"] = True
                self.save_state()
            elif side == "SHORT" and current_price <= pos["trailing_activation"]:
                pos["stop_loss"]       = round(pos["entry_price"] * (1 - COMMISSION_PCT * 2), 4)
                pos["trailing_active"] = True
                self.save_state()

    # ------------------------------------------------------------------
    #  CIERRE DE POSICIÓN
    # ------------------------------------------------------------------

    def close_trade(self, exit_price: float, exit_reason: str, timestamp: str) -> dict:
        if self.open_position is None:
            raise ValueError("No hay posición abierta para cerrar")

        pos   = self.open_position
        side  = pos["side"]
        entry = pos["entry_price"]
        size  = pos["position_size"]

        if side == "LONG":
            pnl_usdt = (exit_price - entry) * size
        else:
            pnl_usdt = (entry - exit_price) * size

        fee_exit = exit_price * size * COMMISSION_PCT
        pnl_usdt -= fee_exit
        self.total_fees_usdt += fee_exit

        self.current_capital = max(0.0, self.current_capital + pnl_usdt)
        self.total_pnl_usdt += pnl_usdt
        self.total_trades   += 1

        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

        if pnl_usdt > 0:
            self.winning_trades      += 1
            self.consecutive_losses   = 0
        else:
            self.losing_trades       += 1
            self.consecutive_losses  += 1
            if self.consecutive_losses >= 3:
                self.pause_until = datetime.now() + timedelta(hours=1)

        pnl_pct = ((exit_price - entry) / entry) if side == "LONG" else ((entry - exit_price) / entry)

        trade_record = {
            "id":            self.total_trades,
            "side":          side,
            "entry_price":   round(entry, 4),
            "exit_price":    round(exit_price, 4),
            "position_size": size,
            "pnl_pct":       round(pnl_pct * 100, 3),
            "pnl_usdt":      round(pnl_usdt, 2),
            "fee_total":     round(pos["fee_entry"] + fee_exit, 4),
            "capital_after": round(self.current_capital, 2),
            "trailing_used": pos["trailing_active"],
            "exit_reason":   exit_reason,
            "open_time":     pos["open_timestamp"],
            "close_time":    timestamp,
        }

        self.trade_history.append(trade_record)
        self.open_position = None

        self.save_state()
        return trade_record

    # ------------------------------------------------------------------
    #  ESTADÍSTICAS
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        self._check_daily_reset()

        win_rate   = (self.winning_trades / self.total_trades * 100
                      if self.total_trades > 0 else 0)

        daily_loss = (self.daily_start_capital - self.current_capital) / self.daily_start_capital
        daily_pnl  = self.current_capital - self.daily_start_capital
        drawdown   = (self.peak_capital - self.current_capital) / self.peak_capital

        return {
            "capital_initial":        round(self.initial_capital, 2),
            "capital_current":        round(self.current_capital, 2),
            "peak_capital":           round(self.peak_capital, 2),
            "total_pnl_usdt":         round(self.total_pnl_usdt, 2),
            "total_pnl_pct":          round(self.total_pnl_usdt / self.initial_capital * 100, 3),
            "total_fees_usdt":        round(self.total_fees_usdt, 4),
            "daily_pnl_usdt":         round(daily_pnl, 2),
            "daily_pnl_pct":          round(-daily_loss * 100, 3),
            "daily_limit_pct":        config.MAX_DAILY_LOSS * 100,
            "drawdown_pct":           round(drawdown * 100, 3),
            "total_trades":           self.total_trades,
            "winning_trades":         self.winning_trades,
            "losing_trades":          self.losing_trades,
            "win_rate":               round(win_rate, 1),
            "consecutive_losses":     self.consecutive_losses,
            "circuit_breaker_active": self.pause_until is not None and datetime.now() < self.pause_until,
            "risk_reward_ratio":      f"1:{config.TAKE_PROFIT_PCT / config.STOP_LOSS_PCT:.2f}",
            "open_position":          self.open_position,
            "trade_history":          self.trade_history[-20:],
        }