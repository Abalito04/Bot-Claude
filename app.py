# ============================================================
#  APP.PY - Flask Backend
#  SOL Momentum Surge Strategy
# ============================================================

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from datetime import datetime
import threading
import time
import logging

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
        position = risk_manager.open_trade(side, price, datetime.utcnow().isoformat())
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
        record = risk_manager.close_trade(price, "manual", datetime.utcnow().isoformat())
        return jsonify({"ok": True, "trade": record})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reinicia el paper trading (capital y historial)."""
    global risk_manager, last_signal, scan_count
    if bot_running:
        return jsonify({"ok": False, "error": "Detené el bot antes de resetear"}), 400

    risk_manager = RiskManager(initial_capital=config.CAPITAL_USDT)
    last_signal  = {"signal": "FLAT", "timestamp": None}
    scan_count   = 0
    return jsonify({"ok": True, "message": "Paper trading reseteado"})


# ------------------------------------------------------------------
#  BOT LOOP (paper trading)
# ------------------------------------------------------------------

def bot_loop():
    """
    Loop principal del bot (paper trading).
    Se ejecuta cada vez que cierra una vela de 5 minutos.
    """
    global last_signal, last_error, scan_count

    logger.info("Bot loop iniciado — esperando cierre de vela...")

    while bot_running:
        try:
            df     = fetch_klines()
            signal = generate_signal(df)
            price  = fetch_current_price()
            now    = datetime.utcnow().isoformat()

            last_signal = {"signal": signal["signal"], "timestamp": now}
            scan_count += 1

            # ---- Verificar posición abierta ----
            if risk_manager.open_position is not None:
                exit_check = check_exit(risk_manager.open_position, price, df)
                if exit_check["should_exit"]:
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
                    position = risk_manager.open_trade(signal["signal"], price, now)
                    logger.info(
                        f"APERTURA {signal['signal']} | "
                        f"Precio: {price} | "
                        f"Tamaño: {position['position_size']} SOL | "
                        f"TP: {position['take_profit']} | SL: {position['stop_loss']}"
                    )
                else:
                    logger.warning(f"No se puede operar: {check['reason']}")
            else:
                logger.info(f"Señal FLAT — sin acción. RSI: {signal['indicators']['rsi']}")

            last_error = None

        except Exception as e:
            last_error = str(e)
            logger.error(f"Error en bot loop: {e}")

        # Esperar 60 segundos entre escaneos (5m timeframe ≈ revisar cada minuto)
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