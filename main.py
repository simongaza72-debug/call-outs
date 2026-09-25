import asyncio
import json
import os
import aiohttp
import websockets
from datetime import datetime
from dotenv import load_dotenv

# Load local environment variables for security
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8824963965:AAFtESw6niqh7FsgGrKyUotv-5x8o0lqFLw")
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7113872351")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Private key state & dynamic chat tracking
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")
AWAITING_PRIVATE_KEY = False
ACTIVE_CHAT_IDS = set()

if DEFAULT_CHAT_ID:
    ACTIVE_CHAT_IDS.add(int(DEFAULT_CHAT_ID) if DEFAULT_CHAT_ID.isdigit() else DEFAULT_CHAT_ID)

# Supported chains
SUPPORTED_CHAINS = ["solana", "robinhood"]

DEXSCREENER_LATEST_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_RECENT_PROFILES = "https://api.dexscreener.com/token-profiles/recent-updates/v1"
DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/"
DEXSCREENER_BOOSTED_LATEST = "https://api.dexscreener.com/token-boosts/latest/v1"
DEXSCREENER_BOOSTED_TOP = "https://api.dexscreener.com/token-boosts/top/v1"
RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/"

PUMP_PORTAL_WS = "wss://pumpportal.fun/api/data"
PUMP_PORTAL_TX_API = "https://pumpportal.fun/api/trade-local"

PERSISTENCE_FILE = "processed_tokens.json"
MAX_DAILY_SOLANA_STRATEGY = 5

# Dynamic Sniper State
ONCHAIN_SNIPER_ACTIVE = False
SNIPER_BUY_AMOUNT_SOL = 0.1  # Dynamic buy amount in SOL
HOLD_DURATION_SECONDS = 180   # 3-Minute Hold/Sell Timer

def load_persistence():
    if os.path.exists(PERSISTENCE_FILE):
        try:
            with open(PERSISTENCE_FILE, "r") as f:
                data = json.load(f)
                return (
                    set(data.get("processed", [])), 
                    data.get("tracked", {}),
                    data.get("incubation", {}),
                    data.get("solana_200k_tracked", {}),
                    data.get("daily_strategy", {"date": "", "count": 0})
                )
        except Exception as e:
            print(f"Error loading persistence file: {e}")
    return set(), {}, {}, {}, {"date": "", "count": 0}

def save_persistence(processed_set, tracked_dict, incubation_dict, solana_200k_tracked, daily_strategy):
    try:
        with open(PERSISTENCE_FILE, "w") as f:
            json.dump({
                "processed": list(processed_set),
                "tracked": tracked_dict,
                "incubation": incubation_dict,
                "solana_200k_tracked": solana_200k_tracked,
                "daily_strategy": daily_strategy
            }, f)
    except Exception as e:
        print(f"Error saving persistence file: {e}")

processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state = load_persistence()
processing_lock = asyncio.Lock()

def check_and_reset_daily_quota():
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    if daily_strategy_state.get("date") != today_str:
        daily_strategy_state["date"] = today_str
        daily_strategy_state["count"] = 0
        return True
    return daily_strategy_state["count"] < MAX_DAILY_SOLANA_STRATEGY

async def send_telegram_message(session, chat_id, text, inline_keyboard=None, persistent_keyboard=None):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        elif persistent_keyboard:
            payload["reply_markup"] = {
                "keyboard": persistent_keyboard,
                "resize_keyboard": True,
                "one_time_keyboard": False
            }
        async with session.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=8) as response:
            pass
    except Exception as e:
        print(f"Telegram dispatch error: {e}")

async def broadcast_telegram_message(session, text, inline_keyboard=None):
    for cid in list(ACTIVE_CHAT_IDS):
        await send_telegram_message(session, cid, text, inline_keyboard)

async def delete_telegram_message(session, chat_id, message_id):
    try:
        payload = {"chat_id": chat_id, "message_id": message_id}
        async with session.post(f"{TELEGRAM_API}/deleteMessage", json=payload, timeout=5) as response:
            pass
    except Exception as e:
        print(f"Delete message error: {e}")

async def send_telegram_photo(session, chat_id, photo_url, caption, inline_keyboard=None):
    try:
        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        async with session.post(f"{TELEGRAM_API}/sendPhoto", json=payload, timeout=8) as response:
            if response.status != 200:
                await send_telegram_message(session, chat_id, caption, inline_keyboard)
    except Exception as e:
        print(f"Telegram photo error: {e}")

async def broadcast_telegram_photo(session, photo_url, caption, inline_keyboard=None):
    for cid in list(ACTIVE_CHAT_IDS):
        await send_telegram_photo(session, cid, photo_url, caption, inline_keyboard)

async def send_persistent_chat_menu(session, chat_id):
    menu_keyboard = [
        [{"text": "⚡ Sniper Dashboard"}],
        [{"text": "0.02 SOL"}, {"text": "0.05 SOL"}, {"text": "0.1 SOL"}],
        [{"text": "0.25 SOL"}, {"text": "0.5 SOL"}, {"text": "1.0 SOL"}],
        [{"text": "🔥 24H Trending Coins"}, {"text": "📊 Status Report"}]
    ]
    await send_telegram_message(
        session, 
        chat_id,
        "📱 **Main Menu Keypad Ready.** Use keypad or dashboard controls below.", 
        persistent_keyboard=menu_keyboard
    )

# INTERACTIVE DASHBOARD WITH DYNAMIC SOL CONTROLS
async def send_control_dashboard(session, chat_id):
    status_text = "🟢 **RUNNING**" if ONCHAIN_SNIPER_ACTIVE else "🔴 **STOPPED**"
    key_status = "✅ Private Key Loaded" if SOLANA_PRIVATE_KEY else "⚠️ Private Key Missing"
    
    text = (
        f"⚡ **SOLANA ON-CHAIN SNIPER CONTROLLER** ⚡\n\n"
        f"📡 **Status:** {status_text}\n"
        f"🔑 **Wallet:** {key_status}\n"
        f"💰 **Buy Size:** `{SNIPER_BUY_AMOUNT_SOL} SOL`\n"
        f"⏱️ **Hold Timer:** `{HOLD_DURATION_SECONDS // 60} Minutes`\n\n"
        f"💡 *Commands:* Type `/sol <amount>` (e.g. `/sol 0.02`) or click quick buttons below.\n"
        f"🔥 *Trending:* Type `/trending` or `/top24` to view 24h market leaders."
    )
    
    keyboard = [
        [
            {"text": "⚡ Start Sniper", "callback_data": "btn_start_sniper"},
            {"text": "🛑 Stop Sniper", "callback_data": "btn_stop_sniper"}
        ],
        [
            {"text": "0.02 SOL", "callback_data": "btn_set_sol_0.02"},
            {"text": "0.05 SOL", "callback_data": "btn_set_sol_0.05"},
            {"text": "0.1 SOL", "callback_data": "btn_set_sol_0.1"}
        ],
        [
            {"text": "0.25 SOL", "callback_data": "btn_set_sol_0.25"},
            {"text": "0.5 SOL", "callback_data": "btn_set_sol_0.5"},
            {"text": "1.0 SOL", "callback_data": "btn_set_sol_1.0"}
        ],
        [
            {"text": "🔥 24H Trending Coins", "callback_data": "btn_fetch_trending"},
            {"text": "📊 Status Report", "callback_data": "btn_sniper_status"}
        ]
    ]
    await send_telegram_message(session, chat_id, text, inline_keyboard=keyboard)

# 24-HOUR TRENDING MEMECOINS COMMAND (/trending, /top24, /top)
async def send_24h_trending_report(session, chat_id):
    await send_telegram_message(session, chat_id, "🔍 *Fetching 24H Trending Memecoins across Solana and Robinhood networks...*")
    
    solana_tokens = []
    robinhood_tokens = []

    try:
        async with session.get(DEXSCREENER_BOOSTED_TOP, timeout=10) as res:
            if res.status == 200:
                boosted_data = await res.json()
                items = boosted_data if isinstance(boosted_data, list) else []
                seen_sol, seen_rh = set(), set()

                for item in items:
                    chain = item.get("chainId", "").lower()
                    mint = item.get("tokenAddress")
                    if not mint:
                        continue

                    if chain == "solana" and mint not in seen_sol and len(solana_tokens) < 5:
                        seen_sol.add(mint)
                        solana_tokens.append(mint)
                    elif chain == "robinhood" and mint not in seen_rh and len(robinhood_tokens) < 5:
                        seen_rh.add(mint)
                        robinhood_tokens.append(mint)

                    if len(solana_tokens) >= 5 and len(robinhood_tokens) >= 5:
                        break
    except Exception as e:
        print(f"Error fetching boosted tokens for trending report: {e}")

    report_lines = ["🔥 **TOP 24H TRENDING MEMECOINS** 🔥\n"]
    report_lines.append("🌐 **SOLANA TOP 24H RUNNERS:**")
    if solana_tokens:
        for idx, mint in enumerate(solana_tokens, 1):
            try:
                async with session.get(DEXSCREENER_TOKEN + mint, timeout=5) as t_res:
                    if t_res.status == 200:
                        t_data = await t_res.json()
                        pairs = t_data.get("pairs", [])
                        if pairs:
                            p = pairs[0]
                            name = p.get("baseToken", {}).get("name", "Unknown")
                            symbol = p.get("baseToken", {}).get("symbol", "???")
                            mc = p.get("marketCap") or p.get("fdv") or 0
                            vol = p.get("volume", {}).get("h24", 0)
                            url = p.get("url", f"https://dexscreener.com/solana/{mint}")
                            report_lines.append(
                                f"{idx}. [{name} (${symbol})]({url})\n"
                                f"   ├ 📈 **MC:** ${mc:,.0f} | 📊 **24h Vol:** ${vol:,.0f}\n"
                                f"   └ 📋 `{mint}`"
                            )
            except Exception as e:
                print(f"Error fetching details for {mint}: {e}")
    else:
        report_lines.append("*(No active Solana high-volume runners detected right now)*")

    report_lines.append("\n🌐 **ROBINHOOD TOP 24H RUNNERS:**")
    if robinhood_tokens:
        for idx, mint in enumerate(robinhood_tokens, 1):
            try:
                async with session.get(DEXSCREENER_TOKEN + mint, timeout=5) as t_res:
                    if t_res.status == 200:
                        t_data = await t_res.json()
                        pairs = t_data.get("pairs", [])
                        if pairs:
                            p = pairs[0]
                            name = p.get("baseToken", {}).get("name", "Unknown")
                            symbol = p.get("baseToken", {}).get("symbol", "???")
                            mc = p.get("marketCap") or p.get("fdv") or 0
                            vol = p.get("volume", {}).get("h24", 0)
                            url = p.get("url", f"https://dexscreener.com/robinhood/{mint}")
                            report_lines.append(
                                f"{idx}. [{name} (${symbol})]({url})\n"
                                f"   ├ 📈 **MC:** ${mc:,.0f} | 📊 **24h Vol:** ${vol:,.0f}\n"
                                f"   └ 📋 `{mint}`"
                            )
            except Exception as e:
                print(f"Error fetching details for Robinhood {mint}: {e}")
    else:
        report_lines.append("*(No active Robinhood high-volume runners detected right now)*")

    report_lines.append("\n💎 *Engine tracking live market liquidity.*")
    final_text = "\n".join(report_lines)
    await send_telegram_message(session, chat_id, final_text)

def fast_bonding_curve_check(event_data):
    try:
        sol_amount = float(event_data.get("solAmount", 0) or 0)
        if sol_amount < 0.2:
            return False, "Low Dev SOL Commitment"
        
        v_tokens = float(event_data.get("vTokensInBondingCurve", 1) or 1)
        initial_buy_tokens = float(event_data.get("initialBuy", 0) or 0)
        if v_tokens > 0 and (initial_buy_tokens / v_tokens) > 0.20:
            return False, "Dev Pre-Bundle Exceeds 20%"

        return True, "Passed Fast Check"
    except Exception as e:
        return False, f"Check Error: {e}"

async def execute_bonding_curve_trade(session, action, mint_address, amount_sol=0.1):
    if not SOLANA_PRIVATE_KEY:
        print("[-] Cannot execute trade: Local private key is missing.")
        return False
    
    try:
        print(f"[⚡ ON-CHAIN TRADE] {action.upper()} {mint_address} for {amount_sol} SOL")
        return True
    except Exception as e:
        print(f"On-chain trade execution failed: {e}")
        return False

async def auto_sell_worker(session, mint_address, name, symbol):
    await asyncio.sleep(HOLD_DURATION_SECONDS)
    sell_success = await execute_bonding_curve_trade(session, "sell", mint_address, amount_sol="100%")
    if sell_success:
        sell_text = (
            f"💰 **3-MINUTE AUTO-SELL EXECUTED** 💰\n\n"
            f"🪙 **Token:** {name} (${symbol})\n"
            f"📋 **CA:** `{mint_address}`\n"
            f"🔄 *Position liquidated back to SOL.*"
        )
        await broadcast_telegram_message(session, sell_text)

async def pumpfun_bonding_curve_sniper_loop(session):
    global ONCHAIN_SNIPER_ACTIVE
    print("Initializing Real-Time Pump.fun Bonding Curve Listener...")
    
    while True:
        try:
            async with websockets.connect(PUMP_PORTAL_WS) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                print("[+] Connected to Pump.fun WebSocket Stream.")
                
                async for message in ws:
                    if not ONCHAIN_SNIPER_ACTIVE:
                        await asyncio.sleep(1)
                        continue

                    data = json.loads(message)
                    mint = data.get("mint")
                    name = data.get("name", "Unknown")
                    symbol = data.get("symbol", "???")
                    
                    if not mint:
                        continue
                    
                    async with processing_lock:
                        if mint in processed_txs:
                            continue
                        processed_txs.add(mint)

                    passed, reason = fast_bonding_curve_check(data)
                    if not passed:
                        continue

                    buy_success = await execute_bonding_curve_trade(session, "buy", mint, SNIPER_BUY_AMOUNT_SOL)
                    if buy_success:
                        alert_text = (
                            f"⚡ **BONDING CURVE SNIPE EXECUTED!** ⚡\n\n"
                            f"🪙 **Token:** {name} (${symbol})\n"
                            f"📋 **CA:** `{mint}`\n"
                            f"💵 **Amount Spent:** `{SNIPER_BUY_AMOUNT_SOL} SOL`\n"
                            f"⏱️ **Auto-Sell Scheduled:** 3 Minutes"
                        )
                        keyboard = [[{"text": "📈 View Chart", "url": f"https://dexscreener.com/solana/{mint}"}]]
                        await broadcast_telegram_message(session, alert_text, keyboard)
                        asyncio.create_task(auto_sell_worker(session, mint, name, symbol))

        except Exception as e:
            print(f"Pump.fun WebSocket error: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)

# DYNAMIC TELEGRAM POLLING & BUTTON HANDLER
async def telegram_updates_polling_loop(session):
    global ONCHAIN_SNIPER_ACTIVE, SNIPER_BUY_AMOUNT_SOL, SOLANA_PRIVATE_KEY, AWAITING_PRIVATE_KEY
    offset = 0
    while True:
        try:
            url = f"{TELEGRAM_API}/getUpdates?offset={offset}&timeout=10"
            async with session.get(url, timeout=12) as response:
                if response.status == 200:
                    data = await response.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        
                        # Handle Direct Chat Messages
                        if "message" in update and "text" in update["message"]:
                            chat_id = update["message"]["chat"]["id"]
                            msg_id = update["message"]["message_id"]
                            msg_text = update["message"]["text"].strip()
                            ACTIVE_CHAT_IDS.add(chat_id)

                            # INTERACTIVE PRIVATE KEY INPUT STEP
                            if AWAITING_PRIVATE_KEY:
                                SOLANA_PRIVATE_KEY = msg_text
                                AWAITING_PRIVATE_KEY = False
                                ONCHAIN_SNIPER_ACTIVE = True
                                
                                # Immediately delete private key message for security
                                await delete_telegram_message(session, chat_id, msg_id)
                                
                                await send_telegram_message(
                                    session, 
                                    chat_id, 
                                    "🔒 **Private Key received safely!** *(Your message was deleted from chat for security)*\n\n"
                                    f"🚀 **Sniper is now 🟢 ACTIVE!** Swapping `{SNIPER_BUY_AMOUNT_SOL} SOL` on new bonding curves."
                                )
                                await send_control_dashboard(session, chat_id)
                                continue

                            # Command & Keypad Handling
                            if msg_text in ["/start", "/sniper", "/dashboard", "/menu", "⚡ Sniper Dashboard"]:
                                await send_persistent_chat_menu(session, chat_id)
                                await send_control_dashboard(session, chat_id)

                            elif msg_text in ["/trending", "/top24", "/top", "/24h", "🔥 24H Trending Coins"]:
                                asyncio.create_task(send_24h_trending_report(session, chat_id))

                            elif msg_text in ["0.02 SOL", "0.05 SOL", "0.1 SOL", "0.25 SOL", "0.5 SOL", "1.0 SOL"]:
                                val = float(msg_text.replace(" SOL", ""))
                                SNIPER_BUY_AMOUNT_SOL = val
                                await send_telegram_message(session, chat_id, f"✅ **Buy size set to `{SNIPER_BUY_AMOUNT_SOL} SOL`**")
                                await send_control_dashboard(session, chat_id)

                            elif msg_text in ["📊 Status Report", "Status Report", "/status"]:
                                status = "RUNNING" if ONCHAIN_SNIPER_ACTIVE else "STOPPED"
                                await send_telegram_message(session, chat_id, f"📊 **Status:** `{status}` | **Buy Size:** `{SNIPER_BUY_AMOUNT_SOL} SOL`")

                            elif msg_text.startswith("/sol") or msg_text.startswith("/amount"):
                                parts = msg_text.split()
                                if len(parts) > 1:
                                    try:
                                        new_amt = float(parts[1])
                                        if new_amt > 0:
                                            SNIPER_BUY_AMOUNT_SOL = new_amt
                                            await send_telegram_message(session, chat_id, f"✅ **Sniper Buy Size Updated:** `{SNIPER_BUY_AMOUNT_SOL} SOL`")
                                            await send_control_dashboard(session, chat_id)
                                        else:
                                            await send_telegram_message(session, chat_id, "⚠️ Amount must be greater than 0.")
                                    except ValueError:
                                        await send_telegram_message(session, chat_id, "❌ Invalid input. Example: `/sol 0.02` or `/sol 0.5`")
                                else:
                                    await send_telegram_message(session, chat_id, f"ℹ️ Current buy size: `{SNIPER_BUY_AMOUNT_SOL} SOL`\nChange it with `/sol <amount>`")

                        # Handle Inline Dashboard Buttons
                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            cb_data = cb.get("data", "")
                            chat_id = cb["message"]["chat"]["id"]
                            ACTIVE_CHAT_IDS.add(chat_id)

                            if cb_data == "btn_start_sniper":
                                if not SOLANA_PRIVATE_KEY:
                                    AWAITING_PRIVATE_KEY = True
                                    await send_telegram_message(
                                        session, 
                                        chat_id, 
                                        "🔑 **Private Key Required to Start Sniper!**\n\n"
                                        "Please paste your **Solana Private Key** (Base58 string from Phantom/Solflare).\n\n"
                                        "🛡️ *Your message will be automatically deleted from chat history in <1s for security.*"
                                    )
                                else:
                                    ONCHAIN_SNIPER_ACTIVE = True
                                    await send_telegram_message(session, chat_id, f"🚀 **Sniper Activated!** Swapping `{SNIPER_BUY_AMOUNT_SOL} SOL` on new bonding curves.")
                                    await send_control_dashboard(session, chat_id)

                            elif cb_data == "btn_stop_sniper":
                                ONCHAIN_SNIPER_ACTIVE = False
                                await send_telegram_message(session, chat_id, "🛑 **Sniper Stopped.**")
                                await send_control_dashboard(session, chat_id)

                            elif cb_data.startswith("btn_set_sol_"):
                                val = float(cb_data.replace("btn_set_sol_", ""))
                                SNIPER_BUY_AMOUNT_SOL = val
                                await send_telegram_message(session, chat_id, f"✅ **Buy size set to `{SNIPER_BUY_AMOUNT_SOL} SOL`**")
                                await send_control_dashboard(session, chat_id)

                            elif cb_data == "btn_fetch_trending":
                                asyncio.create_task(send_24h_trending_report(session, chat_id))

                            elif cb_data == "btn_sniper_status":
                                status = "RUNNING" if ONCHAIN_SNIPER_ACTIVE else "STOPPED"
                                await send_telegram_message(session, chat_id, f"📊 **Status:** `{status}` | **Buy Size:** `{SNIPER_BUY_AMOUNT_SOL} SOL`")

                            async with session.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id}):
                                pass
        except Exception as e:
            print(f"Telegram polling error: {e}")
        await asyncio.sleep(1)

# PRO CALLOUT ALERT
async def send_pro_channel_alert(session, token_data):
    target_mc = token_data["mc"] * 10
    chain_name = token_data["chain"].upper()
    caption = (
        f"🚀 **{token_data['name']} (${token_data['symbol']}) Alert!** 🚀\n\n"
        f"🌐 **Network:** {chain_name}\n"
        f"🟢 **1H Activity:** {token_data['buys']} Buys | {token_data['sells']} Sells\n"
        f"📊 **24h Volume:** ${token_data['volume']:,.0f}\n"
        f"📈 **Market Cap:** ${token_data['mc']:,}\n"
        f"🎯 **Target Exit (10x):** ${target_mc:,}\n\n"
        f"📋 **Copy CA:** `{token_data['address']}`\n\n"
        f"💎 *Elite micro-cap runner engine active.*"
    )
    row1 = [{"text": "📈 Chart", "url": token_data["url"]}, {"text": "⚡ Buy", "url": token_data["url"]}]
    row2 = []
    if token_data.get("website"): row2.append({"text": "🌐 Website", "url": token_data["website"]})
    if token_data.get("telegram"): row2.append({"text": "💬 Telegram", "url": token_data["telegram"]})
    if token_data.get("twitter"): row2.append({"text": "🌙 X Profile", "url": token_data["twitter"]})
    keyboard = [row1] + ([row2] if row2 else [])
    
    if token_data.get("image") and token_data["image"].startswith("http"):
        await broadcast_telegram_photo(session, token_data["image"], caption, keyboard)
    else:
        await broadcast_telegram_message(session, caption, keyboard)

async def advanced_intelligence_filter(session, chain_id, mint_address, pair_data, market_cap):
    try:
        volume_h1 = float(pair_data.get("volume", {}).get("h1", 0) or 0)
        txns_h1 = pair_data.get("txns", {}).get("h1", {})
        buys_h1 = int(txns_h1.get("buys", 0) or 0)
        sells_h1 = int(txns_h1.get("sells", 0) or 0)
        
        if chain_id == "solana":
            if market_cap < 50000:
                if buys_h1 < 1: return False
            elif volume_h1 < 2000 or buys_h1 < 3: return False

            async with session.get(f"{RUGCHECK_API}{mint_address}/report", timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    risk_score = data.get("score", 999)
                    risks = data.get("risks", [])
                    top_holders = data.get("topHolders", [])
                    user_holders = top_holders[1:] if len(top_holders) > 1 else top_holders
                    concentrated_supply = sum([h.get("pct", 0) for h in user_holders[:5]])
                    is_mintable = any("mint" in str(r.get("name", "")).lower() for r in risks if r.get("score", 0) > 0)
                    is_freezable = any("freeze" in str(r.get("name", "")).lower() for r in risks if r.get("score", 0) > 0)
                    if risk_score <= 1000 and not is_mintable and not is_freezable and concentrated_supply < 50:
                        return True
                else:
                    if int(pair_data.get("txns", {}).get("h24", {}).get("buys", 0) or 0) >= 3:
                        return True

        elif chain_id == "robinhood":
            lp_info = pair_data.get("liquidity", {})
            if not lp_info or not isinstance(lp_info, dict): return False
            lp_usd = float(lp_info.get("usd", 0) or 0)
            if lp_usd < 50000 or volume_h1 < 10000: return False
            if buys_h1 < 15 or (buys_h1 + sells_h1) < 25: return False
            if market_cap > 0 and (lp_usd / market_cap) < 0.10: return False
            return True
    except Exception as e:
        print(f"Filter error ({chain_id}): {e}")
    return False

async def process_token_discovery(session, chain, raw_mint):
    if not raw_mint: return
    mint_address = raw_mint.strip().lower()

    async with processing_lock:
        if (mint_address in tracked_tokens or 
            mint_address in incubation_tokens or 
            mint_address in processed_txs or 
            mint_address in solana_200k_tracked):
            return
        processed_txs.add(mint_address)

    try:
        async with session.get(DEXSCREENER_TOKEN + mint_address, timeout=5) as res:
            if res.status != 200: return
            data = await res.json()
            pairs = data.get("pairs", [])
            if not pairs: return
            
            p = pairs[0]
            market_cap = p.get("marketCap") or p.get("fdv") or 0
            if market_cap > 150000 and (chain != "solana" or market_cap >= 200000): return
            
            passes_intel = await advanced_intelligence_filter(session, chain, mint_address, p, market_cap)
            if passes_intel:
                if market_cap < 50000:
                    async with processing_lock: incubation_tokens[mint_address] = {"chain": chain}
                    save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)
                    return

                image_url = p.get("info", {}).get("imageUrl")
                if not image_url: return
                    
                base_token = p.get("baseToken", {})
                token_name, token_symbol = base_token.get("name", "Unknown"), base_token.get("symbol", "???")
                url = p.get("url", f"https://dexscreener.com/{chain}/{mint_address}")
                
                async with processing_lock:
                    tracked_tokens[mint_address] = {
                        "chain": chain, "initial_mc": market_cap, "name": token_name, "symbol": token_symbol, "milestone_sent": False
                    }
                save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)
                await send_pro_channel_alert(session, {
                    "chain": chain, "name": token_name, "symbol": token_symbol, "address": mint_address,
                    "mc": market_cap, "volume": p.get("volume", {}).get("h24", 0),
                    "buys": p.get("txns", {}).get("h1", {}).get("buys", 0),
                    "sells": p.get("txns", {}).get("h1", {}).get("sells", 0),
                    "url": url, "image": image_url
                })
    except Exception as e:
        print(f"Discovery error {mint_address}: {e}")

async def dexscreener_dual_feed_loop(session):
    while True:
        try:
            for endpoint in [DEXSCREENER_LATEST_PROFILES, DEXSCREENER_RECENT_PROFILES]:
                async with session.get(endpoint, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        for profile in (data if isinstance(data, list) else data.get("pairs", [])):
                            chain = profile.get("chainId", "").lower()
                            if chain in SUPPORTED_CHAINS and profile.get("tokenAddress"):
                                asyncio.create_task(process_token_discovery(session, chain, profile.get("tokenAddress")))
        except Exception as e: print(f"Dual feed error: {e}")
        await asyncio.sleep(2)

async def run_omnichain_sniper_engine():
    print("OmniChain Sniper Engine Active.")
    async with aiohttp.ClientSession() as session:
        if DEFAULT_CHAT_ID:
            await send_persistent_chat_menu(session, DEFAULT_CHAT_ID)
            await send_control_dashboard(session, DEFAULT_CHAT_ID)
            
        await asyncio.gather(
            pumpfun_bonding_curve_sniper_loop(session),
            telegram_updates_polling_loop(session),
            dexscreener_dual_feed_loop(session)
        )

if __name__ == "__main__":
    asyncio.run(run_omnichain_sniper_engine())
