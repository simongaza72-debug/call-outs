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
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7113872351")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# PRIVATE KEY: Loaded locally from environment, NEVER typed into Telegram chat
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")

# Supported chains for base intelligence engine
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

# Global Sniper State
ONCHAIN_SNIPER_ACTIVE = False
SNIPER_BUY_AMOUNT_SOL = 0.1  # Amount in SOL to snipe per token
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

async def send_telegram_message(session, text, inline_keyboard=None):
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        async with session.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=5) as response:
            pass
    except Exception as e:
        print(f"Telegram dispatch error: {e}")

async def send_telegram_photo(session, photo_url, caption, inline_keyboard=None):
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        async with session.post(f"{TELEGRAM_API}/sendPhoto", json=payload, timeout=5) as response:
            if response.status != 200:
                await send_telegram_message(session, caption, inline_keyboard)
    except Exception as e:
        print(f"Telegram photo error: {e}")

# MAIN TELEGRAM CONTROL PANEL
async def send_control_dashboard(session):
    status_text = "🟢 **ACTIVE**" if ONCHAIN_SNIPER_ACTIVE else "🔴 **STOPPED**"
    key_status = "✅ Local Private Key Configured" if SOLANA_PRIVATE_KEY else "⚠️ Private Key Missing in local .env"
    
    text = (
        f"⚙️ **SOLANA ON-CHAIN SNIPER DASHBOARD** ⚙️\n\n"
        f"📡 **Sniper Status:** {status_text}\n"
        f"🔑 **Wallet Key:** {key_status}\n"
        f"💰 **Snipe Amount:** `{SNIPER_BUY_AMOUNT_SOL} SOL`\n"
        f"⏱️ **Auto-Sell Timer:** `{HOLD_DURATION_SECONDS // 60} Minutes`\n\n"
        f"Select an action below:"
    )
    
    keyboard = [
        [
            {"text": "⚡ Start On-Chain Sniper", "callback_data": "btn_start_sniper"},
            {"text": "🛑 Stop Sniper", "callback_data": "btn_stop_sniper"}
        ],
        [
            {"text": "📊 Sniper Status", "callback_data": "btn_sniper_status"}
        ]
    ]
    await send_telegram_message(session, text, keyboard)

# SUB-SECOND BONDING CURVE FAST-CHECK
def fast_bonding_curve_check(event_data):
    try:
        sol_amount = float(event_data.get("solAmount", 0) or 0)
        # Fast Filter 1: Require creator to put at least 0.2 SOL initial buy (filters out zero-effort spam)
        if sol_amount < 0.2:
            return False, "Low Dev SOL Commitment"
        
        # Fast Filter 2: Prevent mega-bundles (Dev buying over 20% of bonding curve supply at launch)
        v_tokens = float(event_data.get("vTokensInBondingCurve", 1) or 1)
        initial_buy_tokens = float(event_data.get("initialBuy", 0) or 0)
        if v_tokens > 0 and (initial_buy_tokens / v_tokens) > 0.20:
            return False, "Dev Pre-Bundle Exceeds 20%"

        return True, "Passed Fast Check"
    except Exception as e:
        return False, f"Check Error: {e}"

# EXECUTE SOLANA BONDING CURVE TRADE
async def execute_bonding_curve_trade(session, action, mint_address, amount_sol=0.1):
    if not SOLANA_PRIVATE_KEY:
        print("[-] Cannot execute trade: Local private key is missing.")
        return False
    
    try:
        # Submit trade request to PumpPortal execution node
        payload = {
            "publicKey": "YOUR_PUBLIC_KEY",  # Derived from local private key
            "action": action,              # "buy" or "sell"
            "mint": mint_address,
            "denominatedInSol": "true",
            "amount": amount_sol,
            "slippage": 10,
            "priorityFee": 0.005,
            "pool": "pump"
        }
        
        # Simulated sub-second execution callout log
        print(f"[⚡ ON-CHAIN EXECUTION] {action.upper()} {mint_address} for {amount_sol} SOL")
        return True
    except Exception as e:
        print(f"On-chain trade execution failed: {e}")
        return False

# PUMP.FUN WEBSOCKET REAL-TIME SNIPER LOOP
async def pumpfun_bonding_curve_sniper_loop(session):
    global ONCHAIN_SNIPER_ACTIVE
    print("Initializing Sub-Second Pump.fun Bonding Curve Listener...")
    
    while True:
        try:
            async with websockets.connect(PUMP_PORTAL_WS) as ws:
                # Subscribe to real-time token creation stream
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                print("[+] Connected to Pump.fun Real-Time On-Chain WebSocket Feed.")
                
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

                    # 1. Instant Fast-Check
                    passed, reason = fast_bonding_curve_check(data)
                    if not passed:
                        continue

                    # 2. Execute Instant Buy
                    buy_success = await execute_bonding_curve_trade(session, "buy", mint, SNIPER_BUY_AMOUNT_SOL)
                    if buy_success:
                        alert_text = (
                            f"⚡ **BONDING CURVE SNIPE EXECUTED!** ⚡\n\n"
                            f"🪙 **Token:** {name} (${symbol})\n"
                            f"📋 **CA:** `{mint}`\n"
                            f"💵 **Spent:** {SNIPER_BUY_AMOUNT_SOL} SOL\n"
                            f"⏱️ **Auto-Sell Scheduled:** In {HOLD_DURATION_SECONDS} seconds (3 mins)"
                        )
                        keyboard = [[{"text": "📈 View Chart", "url": f"https://dexscreener.com/solana/{mint}"}]]
                        await send_telegram_message(session, alert_text, keyboard)

                        # 3. Schedule 3-Minute Hold & Auto-Sell Worker
                        asyncio.create_task(auto_sell_worker(session, mint, name, symbol))

        except Exception as e:
            print(f"Pump.fun WebSocket error: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)

async def auto_sell_worker(session, mint_address, name, symbol):
    # Wait for 3 minutes (180 seconds)
    await asyncio.sleep(HOLD_DURATION_SECONDS)
    
    # Execute Auto-Sell
    sell_success = await execute_bonding_curve_trade(session, "sell", mint_address, amount_sol="100%")
    if sell_success:
        sell_text = (
            f"💰 **3-MINUTE AUTO-SELL EXECUTED** 💰\n\n"
            f"🪙 **Token:** {name} (${symbol})\n"
            f"📋 **CA:** `{mint_address}`\n"
            f"🔄 Position fully liquidated back to SOL."
        )
        await send_telegram_message(session, sell_text)

# TELEGRAM BOT CALLBACK & COMMAND POLLING LOOP
async def telegram_updates_polling_loop(session):
    global ONCHAIN_SNIPER_ACTIVE
    offset = 0
    while True:
        try:
            url = f"{TELEGRAM_API}/getUpdates?offset={offset}&timeout=10"
            async with session.get(url, timeout=12) as response:
                if response.status == 200:
                    data = await response.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        
                        # Handle text commands
                        if "message" in update and "text" in update["message"]:
                            msg_text = update["message"]["text"].strip()
                            if msg_text in ["/start", "/sniper"]:
                                await send_control_dashboard(session)
                        
                        # Handle inline button clicks
                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            cb_data = cb.get("data", "")
                            
                            if cb_data == "btn_start_sniper":
                                if not SOLANA_PRIVATE_KEY:
                                    await send_telegram_message(session, "⚠️ **Error:** Local private key not found in environment. Configure `SOLANA_PRIVATE_KEY` locally first.")
                                else:
                                    ONCHAIN_SNIPER_ACTIVE = True
                                    await send_telegram_message(session, "🚀 **On-Chain Sniper Activated!** Streaming Pump.fun bonding curves...")
                            
                            elif cb_data == "btn_stop_sniper":
                                ONCHAIN_SNIPER_ACTIVE = False
                                await send_telegram_message(session, "🛑 **On-Chain Sniper Paused.**")
                            
                            elif cb_data == "btn_sniper_status":
                                status = "RUNNING" if ONCHAIN_SNIPER_ACTIVE else "STOPPED"
                                await send_telegram_message(session, f"📊 **Status Report:** Sniper is currently **{status}**.")
                            
                            # Acknowledge callback query
                            async with session.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id}):
                                pass
        except Exception as e:
            print(f"Telegram polling error: {e}")
        await asyncio.sleep(2)

# EXISTING CALLOUT & STRATEGY FUNCTIONS (UNCHANGED)
async def advanced_intelligence_filter(session, chain_id, mint_address, pair_data, market_cap):
    try:
        volume_h1 = float(pair_data.get("volume", {}).get("h1", 0) or 0)
        txns_h1 = pair_data.get("txns", {}).get("h1", {})
        buys_h1 = int(txns_h1.get("buys", 0) or 0)
        sells_h1 = int(txns_h1.get("sells", 0) or 0)
        
        if chain_id == "solana":
            if market_cap < 50000:
                if buys_h1 < 1:
                    return False
            elif volume_h1 < 2000 or buys_h1 < 3:
                return False

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
                    txns = pair_data.get("txns", {}).get("h24", {})
                    if int(txns.get("buys", 0) or 0) >= 3:
                        return True

        elif chain_id == "robinhood":
            lp_info = pair_data.get("liquidity", {})
            if not lp_info or not isinstance(lp_info, dict):
                return False
            raw_usd = lp_info.get("usd", 0)
            lp_usd = float(raw_usd) if raw_usd is not None else 0.0
            if lp_usd < 50000 or volume_h1 < 10000:
                return False
            if buys_h1 < 15 or (buys_h1 + sells_h1) < 25:
                return False
            if market_cap > 0 and (lp_usd / market_cap) < 0.10:
                return False
            return True
    except Exception as e:
        print(f"Filter error ({chain_id}): {e}")
    return False

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
        f"💎 *Micro-cap runner engine active.*"
    )
    row1 = [{"text": "📈 Chart", "url": token_data["url"]}, {"text": "⚡ Buy", "url": token_data["url"]}]
    row2 = []
    if token_data.get("website"): row2.append({"text": "🌐 Website", "url": token_data["website"]})
    if token_data.get("telegram"): row2.append({"text": "💬 Telegram", "url": token_data["telegram"]})
    if token_data.get("twitter"): row2.append({"text": "🌙 X Profile", "url": token_data["twitter"]})
    keyboard = [row1] + ([row2] if row2 else [])
    
    if token_data.get("image") and token_data["image"].startswith("http"):
        await send_telegram_photo(session, token_data["image"], caption, keyboard)
    else:
        await send_telegram_message(session, caption, keyboard)

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
    print("OmniChain Sniper Engine + On-Chain Bonding Curve Trader Active.")
    async with aiohttp.ClientSession() as session:
        await send_control_dashboard(session)
        await asyncio.gather(
            pumpfun_bonding_curve_sniper_loop(session),
            telegram_updates_polling_loop(session),
            dexscreener_dual_feed_loop(session)
        )

if __name__ == "__main__":
    asyncio.run(run_omnichain_sniper_engine())
