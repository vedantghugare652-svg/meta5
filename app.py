import os
import sys
import time
import requests
import threading
import asyncio
import pandas as pd
import MetaTrader5 as mt5
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ==============================================================================
# CONFIGURATION SETUP
# ==============================================================================
TELEGRAM_TOKEN = "8548134538:AAFC2kiFPNCNvHs4fIRmvPFdS2ohNF0X6d4"
TELEGRAM_CHAT_ID = "1289000990"

# Path to MetaTrader 5 terminal executable
MT5_PATH = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

# Restricted solely to Gold (XAUUSD)
SYMBOLS = ["XAUUSD"]
TIMEFRAME = mt5.TIMEFRAME_H1
RR_RATIO = 2.0
USE_VOL_FILTER = True

last_alerted_candles = {symbol: None for symbol in SYMBOLS}

# ==============================================================================
# TELEGRAM NOTIFIER & COMMAND HANDLERS
# ==============================================================================
def send_telegram_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"[Telegram Error] {response.text}")
    except Exception as e:
        print(f"[Network Error] Failed to send Telegram alert: {e}")

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Processing live market test for XAUUSD...")
    
    mt5.initialize(path=MT5_PATH)
    symbol = "XAUUSD"
    mt5.symbol_select(symbol, True)
    
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if tick else 2500.00
    sl = price - 10.0
    tp = price + (10.0 * RR_RATIO)

    test_msg = (
        f"🧪 *TEST STRATEGY ALERT [SIMULATED]*\n\n"
        f"• *Asset:* #{symbol}\n"
        f"• *Entry Price:* `{price:.2f}`\n"
        f"• *Stop Loss (SL):* `{sl:.2f}`\n"
        f"• *Take Profit (TP):* `{tp:.2f}`\n"
        f"• *Risk/Reward:* 1:{RR_RATIO}\n"
        f"• *Status:* MT5 Feed & Bot Handlers Active!"
    )
    await update.message.reply_text(test_msg, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mt5.initialize(path=MT5_PATH)
    terminal_info = mt5.terminal_info()
    mt5_state = "Connected 🟢" if terminal_info is not None else "Disconnected 🔴"
    
    msg = (
        f"📊 *SYSTEM STATUS*\n\n"
        f"• *MT5 Connection:* {mt5_state}\n"
        f"• *Monitored Symbol:* `{', '.join(SYMBOLS)}`\n"
        f"• *Timeframe:* `1 Hour (H1)`\n"
        f"• *Volume Filter:* `{'Enabled' if USE_VOL_FILTER else 'Disabled'}`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *3-Candle Doji Bot Commands:*\n\n"
        "• `/test` - Send a simulated setup alert using live XAUUSD prices.\n"
        "• `/status` - Check MT5 connection and configuration.\n"
        "• `/help` - Show command options."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

def run_telegram_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    mt5.initialize(path=MT5_PATH)
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))
    
    app.run_polling(drop_pending_updates=True, stop_signals=None)

# ==============================================================================
# CORE STRATEGY LOGIC
# ==============================================================================
def check_3candle_doji_setup(symbol: str):
    global last_alerted_candles

    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, 30)
    if rates is None or len(rates) < 25:
        print(f"[{symbol}] Failed to fetch price data. Check if '{symbol}' exists in MT5 Market Watch.")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    c3 = df.iloc[-2]  
    c2 = df.iloc[-3]  
    c1 = df.iloc[-4]  

    current_bar_time = c3['time']
    if last_alerted_candles[symbol] == current_bar_time:
        return  

    vol_sma_20 = df['tick_volume'].iloc[-22:-2].mean()
    vol_valid = not USE_VOL_FILTER or (c3['tick_volume'] > vol_sma_20)

    c1_red = c1['close'] < c1['open']
    c1_green = c1['close'] > c1['open']

    c2_range = c2['high'] - c2['low']
    c2_body = abs(c2['close'] - c2['open'])
    c2_doji = (c2_range > 0) and ((c2_body / c2_range) <= 0.35)
    c2_green_doji = c2_doji and (c2['close'] >= c2['open'])
    c2_red_doji = c2_doji and (c2['close'] <= c2['open'])

    c3_range = c3['high'] - c3['low']
    c3_strong_bull = (c3['close'] > c3['open']) and ((c3['close'] - c3['open']) > c3_range * 0.5)
    c3_strong_bear = (c3['close'] < c3['open']) and ((c3['open'] - c3['close']) > c3_range * 0.5)

    buy_setup = (c1_red and c2_green_doji and 
                 c3['close'] > c1['high'] and 
                 c3['close'] > c2['high'] and 
                 c3_strong_bull and vol_valid)

    sell_setup = (c1_green and c2_red_doji and 
                  c3['close'] < c1['low'] and 
                  c3['close'] < c2['low'] and 
                  c3_strong_bear and vol_valid)

    if buy_setup:
        sl = min(c2['low'], c1['low'])
        risk = c3['close'] - sl
        tp = c3['close'] + (risk * RR_RATIO)
        
        msg = (
            f"🚀 *BUY SETUP PREPARED [1H]*\n\n"
            f"• *Asset:* #{symbol}\n"
            f"• *Entry Price:* `{c3['close']:.2f}`\n"
            f"• *Stop Loss (SL):* `{sl:.2f}`\n"
            f"• *Take Profit (TP):* `{tp:.2f}`\n"
            f"• *Risk/Reward:* 1:{RR_RATIO}\n"
            f"• *Bar Time:* `{current_bar_time}` UTC"
        )
        print(f"[{symbol}] BUY Alert Generated!")
        send_telegram_alert(msg)
        last_alerted_candles[symbol] = current_bar_time

    elif sell_setup:
        sl = max(c2['high'], c1['high'])
        risk = sl - c3['close']
        tp = c3['close'] - (risk * RR_RATIO)

        msg = (
            f"🔻 *SELL SETUP PREPARED [1H]*\n\n"
            f"• *Asset:* #{symbol}\n"
            f"• *Entry Price:* `{c3['close']:.2f}`\n"
            f"• *Stop Loss (SL):* `{sl:.2f}`\n"
            f"• *Take Profit (TP):* `{tp:.2f}`\n"
            f"• *Risk/Reward:* 1:{RR_RATIO}\n"
            f"• *Bar Time:* `{current_bar_time}` UTC"
        )
        print(f"[{symbol}] SELL Alert Generated!")
        send_telegram_alert(msg)
        last_alerted_candles[symbol] = current_bar_time

# ==============================================================================
# MAIN EXECUTION LOOP
# ==============================================================================
if __name__ == "__main__":
    if not mt5.initialize(path=MT5_PATH):
        print(f"MetaTrader5 Initialization Failed! Error Code: {mt5.last_error()}")
        sys.exit()

    print("--- 3-Candle Doji Breakout Monitor Started [XAUUSD ONLY] ---")
    send_telegram_alert("🟢 *3-Candle Doji Breakout Monitor online for XAUUSD.*")

    telegram_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    telegram_thread.start()

    try:
        while True:
            for symbol in SYMBOLS:
                mt5.symbol_select(symbol, True)
                check_3candle_doji_setup(symbol)

            time.sleep(60)

    except KeyboardInterrupt:
        print("\nStopping Monitor...")
        mt5.shutdown()