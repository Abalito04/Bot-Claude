# ============================================================
#  APP.PY - Flask Backend
#  SOL Momentum Surge Strategy
# ============================================================

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from datetime import datetime, timezone
from order_manager import open_position, close_position, check_oco_status
import threading
import time
import logging
import os

import config
from data_fetcher import fetch_klines, fetch_current_price, fetch_24h_stats
from strategy import generate_signal, dataframe_to_chart_data, check_exit
from risk_manager import RiskManager

# ------------------------------------------------------------------
#  Configuración Flask
# ------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
#  Estado global (paper trading)
# ------------------------------------------------------------------
risk_manager = RiskManager(initial_capital=config.CAPITAL_USDT)
risk_manager.load_state()
bot_running  = False
bot_thread   = None
last_signal  = {"signal": "FLAT", "timestamp": None}
last_error   = None
scan_count   = 0


# ------------------------------------------------------------------
#  ENDPOINTS DE PÁGINAS
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------
#  ENDPOINTS DE API
# ------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    """Estado general del bot y del mercado."""
    global last_error, scan_count

    try:
        price  = fetch_current_price()
        stats  = fetch_24h_stats()
        rm_stats = risk_manager.get_stats()

        return jsonify({
            "ok":          True,
            "bot_running": bot_running,
            "scan_count":  scan_count,
            "last_error":  last_error,
            "last_signal": last_signal,
            "market": {
                "symbol":          config.SYMBOL_DISPLAY,
                "price":           round(price, 4),
                "change_24h_pct":  stats["price_change_pct"],
                "high_24h":        stats["high_24h"],
                "low_24h":         stats["low_24h"],
                "volume_24h":      round(stats["volume_24h"], 2),
            },
            "portfolio": rm_stats,
            "config": {
                "interval":        config.INTERVAL,
                "ema_fast":        config.EMA_FAST,
                "ema_slow":        config.EMA_SLOW,
                "rsi_period":      config.RSI_PERIOD,
                "volume_mult":     config.VOLUME_MULT,
                "take_profit_pct": config.TAKE_PROFIT_PCT * 100,
                "stop_loss_pct":   config.STOP_LOSS_PCT * 100,
                "risk_per_trade":  config.RISK_PER_TRADE * 100,
            }
        })
    except Exception as e:
        last_error = str(e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Obtiene o actualiza la configuración dinámica."""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    
    if request.method == "POST":
        new_config = request.get_json()
        try:
            with open(config_path, "w") as f:
                json.dump(new_config, f, indent=2)
            import importlib
            import config
            importlib.reload(config)
            return jsonify({"ok": True, "message": "Configuración actualizada"})
        except Exception as e:
            logger.error(f"Error escribiendo config: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500
    
    # GET
    try:
        if not os.path.exists(config_path):
            # Si no existe, crear uno por defecto basado en los valores actuales
            default_config = {
                "ema_fast": config.EMA_FAST,
                "ema_slow": config.EMA_SLOW,
                "rsi_period": config.RSI_PERIOD,
                "rsi_long_min": config.RSI_LONG_MIN,
                "rsi_short_max": config.RSI_SHORT_MAX,
                "rsi_overbought": config.RSI_OVERBOUGHT,
                "rsi_oversold": config.RSI_OVERSOLD,
                "volume_mult": config.VOLUME_MULT,
                "take_profit_pct": config.TAKE_PROFIT_PCT,
                "stop_loss_pct": config.STOP_LOSS_PCT,
                "risk_per_trade": config.RISK_PER_TRADE,
                "capital_usdt": config.CAPITAL_USDT
            }
            with open(config_path, "w") as f:
                json.dump(default_config, f, indent=2)
            return jsonify({"ok": True, "config": default_config})
            
        with open(config_path, "r") as f:
            return jsonify({"ok": True, "config": json.load(f)})
    except Exception as e:
        logger.error(f"Error leyendo config: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/chart")
def api_chart():
    """Datos OHLCV + indicadores para el gráfico."""
    try:
        df      = fetch_klines()
        chart   = dataframe_to_chart_data(df)
        return jsonify({"ok": True, "data": chart})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/signal")
def api_signal():
    """Señal actual de la estrategia."""
    try:
        df     = fetch_klines()
        signal = generate_signal(df)
        return jsonify({"ok": True, "signal": signal})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/trades")
def api_trades():
    """Historial de operaciones."""
    stats = risk_manager.get_stats()
    return jsonify({
        "ok":            True,
        "trade_history": stats["trade_history"],
        "total_trades":  stats["total_trades"],
        "win_rate":      stats["win_rate"],
    })


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    """Inicia el loop del bot."""
    global bot_running, bot_thread
    if bot_running:
        return jsonify({"ok": False, "message": "El bot ya está corriendo"})

    bot_running = True
    bot_thread  = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    logger.info("Bot iniciado.")
    return jsonify({"ok": True, "message": "Bot iniciado correctamente"})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    """Detiene el loop del bot."""
    global bot_running
    bot_running = False
    logger.info("Bot detenido.")
    return jsonify({"ok": True, "message": "Bot detenido"})


@app.route("/api/trade/open", methods=["POST"])
def api_trade_open():
    """Abre una operación manualmente (paper trading)."""
    data = request.get_json(silent=True) or {}
    side = data.get("side", "").upper()

    if side not in ("LONG", "SHORT"):
        return jsonify({"ok": False, "error": "side debe ser LONG o SHORT"}), 400

    check = risk_manager.can_open_trade()
    if not check["allowed"]:
        return jsonify({"ok": False, "error": check["reason"]}), 400

    try:
        price    = fetch_current_price()
        position = risk_manager.open_trade(side, price, datetime.now(timezone.utc).isoformat())
        return jsonify({"ok": True, "position": position})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/trade/close", methods=["POST"])
def api_trade_close():
    """Cierra la posición actual manualmente."""
    if risk_manager.open_position is None:
        return jsonify({"ok": False, "error": "No hay posición abierta"}), 400

    try:
        price  = fetch_current_price()
        record = risk_manager.close_trade(price, "manual", datetime.now(timezone.utc).isoformat())
        return jsonify({"ok": True, "trade": record})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
def api_reset():
    global risk_manager, last_signal, scan_count
    if bot_running:
        return jsonify({"ok": False, "error": "Detené el bot antes de resetear"}), 400

    risk_manager = RiskManager(initial_capital=config.CAPITAL_USDT)
    last_signal  = {"signal": "FLAT", "timestamp": None}
    scan_count   = 0

    if os.path.exists("state.json"):
        os.remove("state.json")   # ← agregar esto

    return jsonify({"ok": True, "message": "Paper trading reseteado"})


# ------------------------------------------------------------------
#  BOT LOOP (paper trading)
# ------------------------------------------------------------------

def bot_loop():
    """
    Loop principal del bot.
    Detecta señales y ejecuta órdenes reales en Binance (con OCO automático).
    """
    global last_signal, last_error, scan_count

    logger.info("Bot loop iniciado — esperando señal...")

    while bot_running:
        try:
            df     = fetch_klines()
            signal = generate_signal(df)
            price  = fetch_current_price()
            now    = datetime.now(timezone.utc).isoformat()

            last_signal = {"signal": signal["signal"], "timestamp": now}
            scan_count += 1

            # ---- Verificar posición abierta ----
            if risk_manager.open_position is not None:
                risk_manager.update_trailing_stop(price)

                # 1. Verificar si Binance ya ejecutó el OCO (TP o SL automático)
                oco = check_oco_status(risk_manager.open_position)
                if oco["executed"]:
                    record = risk_manager.close_trade(oco["fill_price"], oco["reason"], now)
                    logger.info(
                        f"OCO EJECUTADO: {oco['reason'].upper()} | "
                        f"PnL: {record['pnl_usdt']:+.2f} USDT ({record['pnl_pct']:+.2f}%)"
                    )

                else:
                    # 2. Verificar señal de salida de la estrategia (ej: señal contraria)
                    exit_check = check_exit(risk_manager.open_position, price, df)
                    if exit_check["should_exit"]:
                        close_position(risk_manager.open_position, exit_check["reason"])
                        record = risk_manager.close_trade(price, exit_check["reason"], now)
                        logger.info(
                            f"CIERRE {record['side']} | "
                            f"Motivo: {record['exit_reason']} | "
                            f"PnL: {record['pnl_usdt']:+.2f} USDT ({record['pnl_pct']:+.2f}%)"
                        )

            # ---- Verificar señal de entrada ----
            elif signal["signal"] in ("LONG", "SHORT"):
                check = risk_manager.can_open_trade()
                if check["allowed"]:
                    # Abrir orden real en Binance (MARKET + OCO automático)
                    real_pos = open_position(signal["signal"], risk_manager.current_capital)
                    # Registrar en risk_manager con el precio real de ejecución
                    position = risk_manager.open_trade(
                        signal["signal"], real_pos["entry_price"], now
                    )
                    # Sincronizar el oco_list_id para poder monitorearlo
                    risk_manager.open_position["oco_list_id"] = real_pos.get("oco_list_id")
                    risk_manager.open_position["oco_active"]  = real_pos.get("oco_active", False)
                    risk_manager.save_state()

                    logger.info(
                        f"APERTURA {signal['signal']} | "
                        f"Precio: {real_pos['entry_price']} | "
                        f"Tamaño: {real_pos['quantity']} SOL | "
                        f"TP: {real_pos['take_profit']} | SL: {real_pos['stop_loss']} | "
                        f"OCO: {real_pos.get('oco_list_id')}"
                    )
                else:
                    logger.warning(f"No se puede operar: {check['reason']}")
            else:
                logger.info(f"Señal FLAT — sin acción. RSI: {signal['indicators']['rsi']}")

            last_error = None

        except Exception as e:
            last_error = str(e)
            logger.error(f"Error en bot loop: {e}")

        # Esperar 60 segundos entre escaneos
        for _ in range(60):
            if not bot_running:
                break
            time.sleep(1)

    logger.info("Bot loop finalizado.")

# ------------------------------------------------------------------
#  MAIN
# ------------------------------------------------------------------

if __name__ == "__main__":
    logger.info(f"Iniciando SOL Momentum Surge en {config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)