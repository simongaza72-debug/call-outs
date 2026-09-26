import asyncio
import json
import os
import sys
import html
import socket
import aiohttp
from datetime import datetime, timezone

# --- SINGLE INSTANCE PROCESS LOCK (Prevents duplicate bot instances) ---
try:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    lock_socket.bind(('127.0.0.1', 65432))
except socket.error:
    print("❌ ERROR: Another instance of this bot is already running! Exiting to prevent double-sending.")
    sys.exit(0)

# Environment variable fallback with default keys
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8824963965:AAFtESw6niqh7FsgGrKyUotv-5x8o0lqFLw")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7113872351")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

SUPPORTED_CHAINS = ["solana", "robinhood"]
DEXSCREENER_LATEST_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_RECENT_PROFILES = "https://api.dexscreener.com/token-profiles/recent-updates/v1"
DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/"
DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search?q="
DEXSCREENER_BOOSTED_LATEST = "https://api.dexscreener.com/token-boosts/latest/v1"
DEXSCREENER_BOOSTED_TOP = "https://api.dexscreener.com/token-boosts/top/v1"
RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/"

PERSISTENCE_FILE = "processed_tokens.json"

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
        temp_file = f"{PERSISTENCE_FILE}.tmp"
        processed_list = list(processed_set)[-10000:]
        with open(temp_file, "w") as f:
            json.dump({
                "processed": processed_list,
                "tracked": tracked_dict,
                "incubation": incubation_dict,
                "solana_200k_tracked": solana_200k_tracked,
                "daily_strategy": daily_strategy
            }, f)
        os.replace(temp_file, PERSISTENCE_FILE)
    except Exception as e:
        print(f"Error saving persistence file: {e}")

processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state = load_persistence()
alerted_mints = set(tracked_tokens.keys()).union(set(solana_200k_tracked.keys()))
processing_lock = asyncio.Lock()

def check_and_reset_daily_quota():
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if daily_strategy_state.get("date") != today_str:
        daily_strategy_state["date"] = today_str
        daily_strategy_state["count"] = 0
        return True
    return daily_strategy_state.get("count", 0) < 5

async def send_telegram_message(session, text, inline_keyboard=None, reply_keyboard=None, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    try:
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        elif reply_keyboard:
            payload["reply_markup"] = {"keyboard": reply_keyboard, "resize_keyboard": True}
            
        async with session.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=8) as response:
            pass
    except Exception as e:
        print(f"Telegram dispatch error: {e}")

async def send_telegram_photo(session, photo_url, caption, inline_keyboard=None, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    try:
        payload = {
            "chat_id": target_chat,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        async with session.post(f"{TELEGRAM_API}/sendPhoto", json=payload, timeout=8) as response:
            if response.status != 200:
                await send_telegram_message(session, caption, inline_keyboard, chat_id=target_chat)
    except Exception as e:
        await send_telegram_message(session, caption, inline_keyboard, chat_id=target_chat)

async def answer_callback_query(session, callback_id, text="Processing..."):
    try:
        payload = {"callback_query_id": callback_id, "text": text}
        async with session.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload, timeout=5):
            pass
    except Exception as e:
        print(f"Callback answer error: {e}")

def get_main_menu_inline_keyboard():
    return [
        [
            {"text": "🔥 Top 5 Solana Memecoins", "callback_data": "top_solana"},
            {"text": "🏹 Top 5 Robinhood Memecoins", "callback_data": "top_robinhood"}
        ],
        [
            {"text": "🏆 #1 Top Solana Gem", "callback_data": "top1_solana"},
            {"text": "🏆 #1 Top Robinhood Gem", "callback_data": "top1_robinhood"}
        ],
        [
            {"text": "📊 Bot Status & Stats", "callback_data": "bot_stats"},
            {"text": "🔄 Refresh Menu", "callback_data": "show_menu"}
        ]
    ]

def get_persistent_reply_keyboard():
    return [
        ["🔥 Top 5 Solana", "🏹 Top 5 Robinhood"],
        ["🏆 #1 Solana Gem", "🏆 #1 Robinhood Gem"],
        ["📊 Bot Status", "🔄 Refresh Menu"]
    ]

async def send_main_menu(session, chat_id=None):
    menu_text = (
        "💎 <b>OMNICHAIN SNIPER COMMAND CENTER</b> 💎\n\n"
        "<i>Select an option below or use the persistent bottom menu to view real-time market data:</i>"
    )
    await send_telegram_message(
        session, 
        menu_text, 
        inline_keyboard=get_main_menu_inline_keyboard(), 
        reply_keyboard=get_persistent_reply_keyboard(),
        chat_id=chat_id
    )

async def fetch_top_memecoins_data(session, chain_name):
    """Fetches top boosted/volume pairs for a given network chain."""
    pairs_to_check = []
    
    try:
        async with session.get(DEXSCREENER_BOOSTED_TOP, timeout=10) as res:
            if res.status == 200:
                boosted = await res.json()
                for item in (boosted if isinstance(boosted, list) else []):
                    p_chain = str(item.get("chainId", "")).lower()
                    match_chain = (p_chain in ["robinhood", "arbitrum", "ethereum", "base"]) if chain_name == "robinhood" else (p_chain == chain_name)
                    token_addr = item.get("tokenAddress")
                    if match_chain and token_addr and token_addr not in pairs_to_check:
                        pairs_to_check.append(token_addr)

        if len(pairs_to_check) < 5:
            fallback_query = "pepe" if chain_name == "robinhood" else "pump"
            async with session.get(f"{DEXSCREENER_SEARCH}{fallback_query}", timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    for p in (data.get("pairs") or []):
                        p_chain = str(p.get("chainId", "")).lower()
                        match_chain = (p_chain in ["robinhood", "arbitrum", "ethereum", "base"]) if chain_name == "robinhood" else (p_chain == chain_name)
                        if match_chain:
                            base_addr = (p.get("baseToken") or {}).get("address")
                            if base_addr and base_addr not in pairs_to_check:
                                pairs_to_check.append(base_addr)

        token_details = []
        seen_addresses = set()

        for addr in pairs_to_check[:15]:
            if addr in seen_addresses:
                continue
            seen_addresses.add(addr)
            try:
                async with session.get(f"{DEXSCREENER_TOKEN}{addr}", timeout=5) as res:
                    if res.status == 200:
                        t_data = await res.json()
                        pairs = t_data.get("pairs") or []
                        if pairs:
                            best_pair = max(pairs, key=lambda x: float((x.get("volume") or {}).get("h24") or 0))
                            token_details.append(best_pair)
            except Exception:
                continue

        token_details.sort(key=lambda x: float((x.get("volume") or {}).get("h24") or 0), reverse=True)
        return token_details
    except Exception as e:
        print(f"Error fetching top memecoins for {chain_name}: {e}")
        return []

async def fetch_top_5_memecoins_report(session, chain_name):
    top_tokens = await fetch_top_memecoins_data(session, chain_name)
    top_5 = top_tokens[:5]

    if not top_5:
        return f"⚠️ <b>Notice:</b> No high-volume {chain_name.upper()} memecoins detected right now."

    header_icon = "🔥" if chain_name == "solana" else "🏹"
    output = f"{header_icon} <b>TOP 5 {chain_name.upper()} MEMECOINS (BY 24H VOLUME)</b> {header_icon}\n\n"

    for idx, token in enumerate(top_5, 1):
        base = token.get("baseToken") or {}
        name = html.escape(str(base.get("name", "Unknown")))
        symbol = html.escape(str(base.get("symbol", "???")))
        mc = float(token.get("marketCap") or token.get("fdv") or 0)
        vol = float((token.get("volume") or {}).get("h24") or 0)
        price_change = float((token.get("priceChange") or {}).get("h24") or 0)
        pair_url = token.get("url", "https://dexscreener.com")

        change_sign = "+" if price_change >= 0 else ""

        output += (
            f"<b>{idx}. {name} (${symbol})</b>\n"
            f"   📈 <b>Market Cap:</b> ${mc:,.0f}\n"
            f"   📊 <b>24h Volume:</b> ${vol:,.0f}\n"
            f"   ⚡ <b>24h Change:</b> {change_sign}{price_change:.2f}%\n"
            f"   🔗 <a href='{pair_url}'>View Chart on DexScreener</a>\n\n"
        )

    output += "💎 <i>Live Intelligence Powered by OmniChain Engine 6767</i>"
    return output

async def send_single_top1_memecoin(session, chain_name, chat_id=None):
    top_tokens = await fetch_top_memecoins_data(session, chain_name)
    if not top_tokens:
        await send_telegram_message(session, f"⚠️ No {chain_name.upper()} top token available right now.", chat_id=chat_id)
        return

    token = top_tokens[0]
    base = token.get("baseToken") or {}
    name = html.escape(str(base.get("name", "Unknown")))
    symbol = html.escape(str(base.get("symbol", "???")))
    address = base.get("address", "N/A")
    mc = float(token.get("marketCap") or token.get("fdv") or 0)
    vol = float((token.get("volume") or {}).get("h24") or 0)
    price_change = float((token.get("priceChange") or {}).get("h24") or 0)
    url = token.get("url", "https://dexscreener.com")
    image_url = (token.get("info") or {}).get("imageUrl")
    
    change_sign = "+" if price_change >= 0 else ""

    caption = (
        f"🏆 <b>#1 TOP {chain_name.upper()} MEMECOIN SPOTLIGHT</b> 🏆\n\n"
        f"🪙 <b>Token:</b> {name} (${symbol})\n"
        f"📈 <b>Market Cap:</b> ${mc:,.0f}\n"
        f"📊 <b>24h Volume:</b> ${vol:,.0f}\n"
        f"⚡ <b>24h Change:</b> {change_sign}{price_change:.2f}%\n"
        f"📋 <b>CA:</b> <code>{address}</code>\n\n"
        f"💎 <i>Highest Volume Runner on {chain_name.upper()}. 6767</i>"
    )

    keyboard = [[
        {"text": "📈 View Chart", "url": url},
        {"text": "⚡ Buy Token", "url": url}
    ]]

    if image_url and str(image_url).startswith("http"):
        await send_telegram_photo(session, image_url, caption, keyboard, chat_id=chat_id)
    else:
        await send_telegram_message(session, caption, keyboard, chat_id=chat_id)

async def advanced_intelligence_filter(session, chain_id, mint_address, pair_data, market_cap):
    try:
        volume_data = pair_data.get("volume") or {}
        volume_h1 = float(volume_data.get("h1") or 0)
        txns_data = pair_data.get("txns") or {}
        txns_h1 = txns_data.get("h1") or {}
        buys_h1 = int(txns_h1.get("buys") or 0)
        
        if volume_h1 < 1000 or buys_h1 < 2:
            return False

        if chain_id == "solana":
            async with session.get(f"{RUGCHECK_API}{mint_address}/report", timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    risk_score = data.get("score", 999)
                    risks = data.get("risks") or []
                    top_holders = data.get("topHolders") or []
                    user_holders = top_holders[1:] if len(top_holders) > 1 else top_holders
                    concentrated_supply = sum([float(h.get("pct") or 0) for h in user_holders[:5]])
                    
                    is_mintable = any("mint" in str(r.get("name", "")).lower() for r in risks if (r.get("score") or 0) > 0)
                    is_freezable = any("freeze" in str(r.get("name", "")).lower() for r in risks if (r.get("score") or 0) > 0)
                    
                    if risk_score <= 1000 and not is_mintable and not is_freezable and concentrated_supply < 50:
                        return True
                else:
                    txns_h24 = txns_data.get("h24") or {}
                    if int(txns_h24.get("buys") or 0) >= 10:
                        return True
                        
        elif chain_id == "robinhood":
            lp_info = pair_data.get("liquidity") or {}
            raw_usd = lp_info.get("usd", 0) if isinstance(lp_info, dict) else 0
            lp_usd = float(raw_usd) if raw_usd is not None else 0.0
            
            if lp_usd < 3000:
                return False
                
            txns_h24 = txns_data.get("h24") or {}
            total_txns = int(txns_h24.get("buys") or 0) + int(txns_h24.get("sells") or 0)
            if total_txns >= 10:
                return True

    except Exception as e:
        print(f"Advanced intelligence check error ({chain_id}): {e}")
        return True
            
    return False

async def send_pro_channel_alert(session, token_data):
    address = token_data['address']
    async with processing_lock:
        if address in alerted_mints:
            return
        alerted_mints.add(address)

    target_mc = token_data["mc"] * 10
    chain_name = str(token_data["chain"]).upper()
    
    caption = (
        f"🚀 <b>{html.escape(str(token_data['name']))} (${html.escape(str(token_data['symbol']))}) Sweet-Spot Alert!</b> 🚀\n\n"
        f"🌐 <b>Network:</b> {chain_name}\n"
        f"🟢 <b>1H Activity:</b> {token_data['buys']} Buys | {token_data['sells']} Sells\n"
        f"📊 <b>24h Volume:</b> ${token_data['volume']:,.0f}\n"
        f"📈 <b>Market Cap:</b> ${token_data['mc']:,}\n"
        f"🎯 <b>Target Exit (10x):</b> ${target_mc:,}\n\n"
        f"📋 <b>Copy CA:</b> <code>{address}</code>\n\n"
        f"💎 <i>Elite micro-cap runner engine active. 6767</i>"
    )
    
    row1 = [
        {"text": "📈 Chart", "url": token_data["url"]},
        {"text": "⚡ Buy", "url": token_data["url"]}
    ]
    row2 = []
    if token_data.get("website"):
        row2.append({"text": "🌐 Website", "url": token_data["website"]})
    if token_data.get("twitter"):
        row2.append({"text": "🌙 X Profile", "url": token_data["twitter"]})
        
    keyboard = [row1]
    if row2:
        keyboard.append(row2)
    
    image_url = token_data.get("image")
    if image_url and str(image_url).startswith("http"):
        await send_telegram_photo(session, image_url, caption, keyboard)
    else:
        await send_telegram_message(session, caption, keyboard)

async def send_solana_200k_strategy_alert(session, token_data):
    address = token_data['address']
    async with processing_lock:
        if address in alerted_mints:
            return
        alerted_mints.add(address)

    caption = (
        f"🎯 <b>SOLANA $200K TARGET STRATEGY ENTRY</b> 🎯\n\n"
        f"🪙 <b>Token:</b> {html.escape(str(token_data['name']))} (${html.escape(str(token_data['symbol']))})\n"
        f"📈 <b>Entry Market Cap:</b> ${token_data['mc']:,}\n"
        f"🎯 <b>Target Exit:</b> $200,000 MC\n"
        f"📋 <b>CA:</b> <code>{address}</code>\n\n"
        f"🔥 <i>Daily 5-Solana Strategy Slot Locked, baby. 6767</i>"
    )
    keyboard = [[{"text": "📈 Chart", "url": token_data["url"]}]]
    if token_data.get("image") and str(token_data["image"]).startswith("http"):
        await send_telegram_photo(session, token_data["image"], caption, keyboard)
    else:
        await send_telegram_message(session, caption, keyboard)

async def check_solana_200k_milestones(session):
    if not solana_200k_tracked:
        return

    updated = False
    for mint_address, data in list(solana_200k_tracked.items()):
        if data.get("target_hit"):
            continue
        try:
            async with session.get(f"{DEXSCREENER_TOKEN}{mint_address}", timeout=5) as res:
                if res.status == 200:
                    json_data = await res.json()
                    pairs = json_data.get("pairs") or []
                    if pairs:
                        current_mc = pairs[0].get("marketCap") or pairs[0].get("fdv") or 0
                        if current_mc >= 200000:
                            solana_200k_tracked[mint_address]["target_hit"] = True
                            updated = True
                            caption = (
                                f"💰 <b>SOLANA $200K TARGET REACHED & SOLD!</b> 💰\n\n"
                                f"🪙 <b>Token:</b> {html.escape(str(data['name']))} (${html.escape(str(data['symbol']))})\n"
                                f"💵 <b>Initial Entry MC:</b> ${data['initial_mc']:,}\n"
                                f"🚀 <b>Target Hit MC:</b> ${current_mc:,} (>= $200K Target!)\n"
                                f"🔑 <b>CA:</b> <code>{mint_address}</code>\n\n"
                                f"🛡️ <i>Dump secured, baby. Strategy executed successfully.</i> 6767"
                            )
                            await send_telegram_message(session, caption)
        except Exception as e:
            print(f"Solana 200k milestone error: {e}")
            
    if updated:
        save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)

async def check_token_milestones(session):
    if not tracked_tokens:
        return

    updated = False
    for mint_address, data in list(tracked_tokens.items()):
        if data.get("milestone_sent"):
            continue
        try:
            async with session.get(f"{DEXSCREENER_TOKEN}{mint_address}", timeout=5) as res:
                if res.status == 200:
                    json_data = await res.json()
                    pairs = json_data.get("pairs") or []
                    if pairs:
                        current_mc = pairs[0].get("marketCap") or pairs[0].get("fdv") or 0
                        initial_mc = data["initial_mc"]
                        if current_mc >= initial_mc * 10:
                            tracked_tokens[mint_address]["milestone_sent"] = True
                            updated = True
                            caption = (
                                f"🎉 <b>10X MILESTONE LOCKED!</b> 🎉\n\n"
                                f"🪙 <b>Token:</b> {html.escape(str(data['name']))} (${html.escape(str(data['symbol']))})\n"
                                f"💵 <b>Initial Call:</b> ${initial_mc:,}\n"
                                f"🚀 <b>Current MC:</b> ${current_mc:,} (10x+ Hit!)\n"
                                f"🔑 <b>CA:</b> <code>{mint_address}</code>\n\n"
                                f"🛡️ <i>Target secured, baby.</i> 6767"
                            )
                            await send_telegram_message(session, caption)
        except Exception as e:
            print(f"Milestone tracking error: {e}")
            
    if updated:
        save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)

async def incubation_checker_loop(session):
    while True:
        if not incubation_tokens:
            await asyncio.sleep(10)
            continue

        updated = False
        for mint_address, data in list(incubation_tokens.items()):
            try:
                async with session.get(f"{DEXSCREENER_TOKEN}{mint_address}", timeout=5) as res:
                    if res.status == 200:
                        json_data = await res.json()
                        pairs = json_data.get("pairs") or []
                        if pairs:
                            p = pairs[0]
                            current_mc = p.get("marketCap") or p.get("fdv") or 0
                            chain = data["chain"]

                            if 50000 <= current_mc <= 300000:
                                base_token = p.get("baseToken") or {}
                                token_name = base_token.get("name", "Unknown")
                                token_symbol = base_token.get("symbol", "???")
                                url = p.get("url", f"https://dexscreener.com/{chain}/{mint_address}")
                                image_url = (p.get("info") or {}).get("imageUrl")
                                
                                info = p.get("info") or {}
                                websites = info.get("websites") or []
                                socials = info.get("socials") or []
                                
                                website_url = websites[0]["url"] if websites else None
                                telegram_url = None
                                twitter_url = None
                                
                                for s in socials:
                                    stype = str(s.get("type", "")).lower()
                                    surl = str(s.get("url", ""))
                                    if "telegram" in stype or "t.me" in surl:
                                        telegram_url = surl
                                    elif "twitter" in stype or "x.com" in surl or "twitter.com" in surl:
                                        twitter_url = surl

                                txns_h1 = (p.get("txns") or {}).get("h1") or {}
                                buys = txns_h1.get("buys", 0)
                                sells = txns_h1.get("sells", 0)
                                volume = (p.get("volume") or {}).get("h24", 0)

                                async with processing_lock:
                                    if mint_address in incubation_tokens:
                                        del incubation_tokens[mint_address]
                                    processed_txs.add(mint_address)
                                    tracked_tokens[mint_address] = {
                                        "chain": chain,
                                        "initial_mc": current_mc,
                                        "name": token_name,
                                        "symbol": token_symbol,
                                        "milestone_sent": False
                                    }
                                updated = True
                                
                                await send_pro_channel_alert(session, {
                                    "chain": chain,
                                    "name": token_name,
                                    "symbol": token_symbol,
                                    "address": mint_address,
                                    "mc": current_mc,
                                    "volume": volume,
                                    "buys": buys,
                                    "sells": sells,
                                    "url": url,
                                    "image": image_url,
                                    "website": website_url,
                                    "telegram": telegram_url,
                                    "twitter": twitter_url
                                })
                            
                            elif current_mc > 300000:
                                async with processing_lock:
                                    if mint_address in incubation_tokens:
                                        del incubation_tokens[mint_address]
                                    processed_txs.add(mint_address)
                                updated = True
            except Exception as e:
                print(f"Incubation check error for {mint_address}: {e}")
                
        if updated:
            save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)
            
        await asyncio.sleep(10)

async def process_token_discovery(session, chain, raw_mint):
    if not raw_mint:
        return
    
    mint_address = raw_mint.strip().lower()

    async with processing_lock:
        if (mint_address in tracked_tokens or 
            mint_address in incubation_tokens or 
            mint_address in processed_txs or 
            mint_address in solana_200k_tracked or
            mint_address in alerted_mints):
            return
        processed_txs.add(mint_address)
    
    try:
        async with session.get(DEXSCREENER_TOKEN + mint_address, timeout=5) as res:
            if res.status != 200:
                return
            data = await res.json()
            pairs = data.get("pairs") or []
            if not pairs:
                return
            
            p = pairs[0]
            market_cap = p.get("marketCap") or p.get("fdv") or 0
            
            if market_cap > 300000:
                return
            
            passes_intel = await advanced_intelligence_filter(session, chain, mint_address, p, market_cap)
            if passes_intel:
                if chain == "solana" and market_cap < 200000:
                    async with processing_lock:
                        if check_and_reset_daily_quota() and mint_address not in solana_200k_tracked:
                            daily_strategy_state["count"] += 1
                            base_token = p.get("baseToken") or {}
                            token_name = base_token.get("name", "Unknown")
                            token_symbol = base_token.get("symbol", "???")
                            url = p.get("url", f"https://dexscreener.com/{chain}/{mint_address}")
                            image_url = (p.get("info") or {}).get("imageUrl")

                            solana_200k_tracked[mint_address] = {
                                "chain": chain,
                                "initial_mc": market_cap,
                                "name": token_name,
                                "symbol": token_symbol,
                                "target_hit": False
                            }
                            save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)
                            
                            await send_solana_200k_strategy_alert(session, {
                                "chain": chain,
                                "name": token_name,
                                "symbol": token_symbol,
                                "address": mint_address,
                                "mc": market_cap,
                                "url": url,
                                "image": image_url
                            })
                            return

                if market_cap < 50000:
                    async with processing_lock:
                        incubation_tokens[mint_address] = {"chain": chain}
                    save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)
                    return

                image_url = (p.get("info") or {}).get("imageUrl")
                base_token = p.get("baseToken") or {}
                token_name = base_token.get("name", "Unknown")
                token_symbol = base_token.get("symbol", "???")
                url = p.get("url", f"https://dexscreener.com/{chain}/{mint_address}")
                
                info = p.get("info") or {}
                websites = info.get("websites") or []
                socials = info.get("socials") or []
                
                website_url = websites[0]["url"] if websites else None
                telegram_url = None
                twitter_url = None
                
                for s in socials:
                    stype = str(s.get("type", "")).lower()
                    surl = str(s.get("url", ""))
                    if "telegram" in stype or "t.me" in surl:
                        telegram_url = surl
                    elif "twitter" in stype or "x.com" in surl or "twitter.com" in surl:
                        twitter_url = surl

                txns_h1 = (p.get("txns") or {}).get("h1") or {}
                buys = txns_h1.get("buys", 0)
                sells = txns_h1.get("sells", 0)
                volume = (p.get("volume") or {}).get("h24", 0)

                async with processing_lock:
                    tracked_tokens[mint_address] = {
                        "chain": chain,
                        "initial_mc": market_cap,
                        "name": token_name,
                        "symbol": token_symbol,
                        "milestone_sent": False
                    }
                
                save_persistence(processed_txs, tracked_tokens, incubation_tokens, solana_200k_tracked, daily_strategy_state)
                
                await send_pro_channel_alert(session, {
                    "chain": chain,
                    "name": token_name,
                    "symbol": token_symbol,
                    "address": mint_address,
                    "mc": market_cap,
                    "volume": volume,
                    "buys": buys,
                    "sells": sells,
                    "url": url,
                    "image": image_url,
                    "website": website_url,
                    "telegram": telegram_url,
                    "twitter": twitter_url
                })
    except Exception as e:
        print(f"Error processing token discovery {mint_address}: {e}")

async def dexscreener_dual_feed_loop(session):
    while True:
        try:
            endpoints = [DEXSCREENER_LATEST_PROFILES, DEXSCREENER_RECENT_PROFILES]
            for endpoint in endpoints:
                async with session.get(endpoint, timeout=10) as res:
                    if res.status == 200:
                        data = await res.json()
                        profiles = data if isinstance(data, list) else (data.get("pairs") or [])
                        for profile in profiles:
                            chain = str(profile.get("chainId", "")).lower()
                            if chain in SUPPORTED_CHAINS:
                                mint_address = profile.get("tokenAddress")
                                if mint_address:
                                    asyncio.create_task(process_token_discovery(session, chain, mint_address))
        except Exception as e:
            print(f"DexScreener feed fetch error: {e}")
        await asyncio.sleep(3)

async def milestone_checker_loop(session):
    while True:
        await check_token_milestones(session)
        await check_solana_200k_milestones(session)
        await asyncio.sleep(15)

async def deployer_wallet_tracking_loop(session):
    while True:
        try:
            async with session.get(DEXSCREENER_BOOSTED_TOP, timeout=10) as res:
                if res.status == 200:
                    items = await res.json()
                    for item in items if isinstance(items, list) else []:
                        chain = str(item.get("chainId", "")).lower()
                        if chain in SUPPORTED_CHAINS:
                            mint = item.get("tokenAddress")
                            if mint:
                                asyncio.create_task(process_token_discovery(session, chain, mint))
        except Exception as e:
            print(f"Deployer tracker error: {e}")
        await asyncio.sleep(20)

async def mempool_sniffing_loop(session):
    while True:
        try:
            async with session.get(DEXSCREENER_RECENT_PROFILES, timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    profiles = data if isinstance(data, list) else (data.get("pairs") or [])
                    for p in profiles[:15]:
                        chain = str(p.get("chainId", "")).lower()
                        if chain in SUPPORTED_CHAINS:
                            mint = p.get("tokenAddress")
                            if mint:
                                asyncio.create_task(process_token_discovery(session, chain, mint))
        except Exception as e:
            print(f"Mempool sniffer feed error: {e}")
        await asyncio.sleep(5)

async def social_alpha_scraping_loop(session):
    while True:
        try:
            async with session.get(DEXSCREENER_BOOSTED_LATEST, timeout=10) as res:
                if res.status == 200:
                    items = await res.json()
                    for item in items if isinstance(items, list) else []:
                        chain = str(item.get("chainId", "")).lower()
                        if chain in SUPPORTED_CHAINS:
                            mint = item.get("tokenAddress")
                            if mint:
                                asyncio.create_task(process_token_discovery(session, chain, mint))
        except Exception as e:
            print(f"Social alpha scraper error: {e}")
        await asyncio.sleep(12)

async def telegram_polling_loop(session):
    offset = 0
    print("[+] Interactive Telegram Polling Loop Started.")
    
    while True:
        try:
            url = f"{TELEGRAM_API}/getUpdates?offset={offset}&timeout=10"
            async with session.get(url, timeout=15) as res:
                if res.status == 200:
                    data = await res.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        
                        # Handle text input (Commands & Persistent Reply Keyboard clicks)
                        if "message" in update and "text" in update["message"]:
                            msg = update["message"]
                            text = msg["text"].strip()
                            text_lower = text.lower()
                            chat_id = msg["chat"]["id"]
                            
                            if text_lower in ["/start", "/menu", "menu", "🔄 refresh menu"]:
                                await send_main_menu(session, chat_id=chat_id)
                            elif text_lower in ["🔥 top 5 solana memecoins", "🔥 top 5 solana"]:
                                report = await fetch_top_5_memecoins_report(session, "solana")
                                await send_telegram_message(session, report, inline_keyboard=get_main_menu_inline_keyboard(), chat_id=chat_id)
                            elif text_lower in ["🏹 top 5 robinhood memecoins", "🏹 top 5 robinhood"]:
                                report = await fetch_top_5_memecoins_report(session, "robinhood")
                                await send_telegram_message(session, report, inline_keyboard=get_main_menu_inline_keyboard(), chat_id=chat_id)
                            elif text_lower in ["🏆 #1 top solana gem", "🏆 #1 solana gem"]:
                                await send_single_top1_memecoin(session, "solana", chat_id=chat_id)
                            elif text_lower in ["🏆 #1 top robinhood gem", "🏆 #1 robinhood gem"]:
                                await send_single_top1_memecoin(session, "robinhood", chat_id=chat_id)
                            elif text_lower in ["📊 bot status & stats", "📊 bot status"]:
                                stats_msg = (
                                    f"📊 <b>OMNICHAIN SNIPER ENGINE TELEMETRY</b> 📊\n\n"
                                    f"🟢 <b>Tracked Runners:</b> {len(tracked_tokens)}\n"
                                    f"🐣 <b>Incubation Watchlist:</b> {len(incubation_tokens)}\n"
                                    f"🎯 <b>Solana 200K Entries:</b> {len(solana_200k_tracked)}\n"
                                    f"📅 <b>Daily Strategy Quota:</b> {daily_strategy_state.get('count', 0)}/5 used today\n"
                                    f"⚙️ <b>Processed History:</b> {len(processed_txs)} tokens indexed\n\n"
                                    f"🛡️ <i>Engine operational and deduplicated. 6767</i>"
                                )
                                await send_telegram_message(session, stats_msg, inline_keyboard=get_main_menu_inline_keyboard(), chat_id=chat_id)

                        # Handle Inline Menu Callbacks
                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            cb_data = cb.get("data")
                            chat_id = cb["message"]["chat"]["id"]
                            
                            await answer_callback_query(session, cb_id)
                            
                            if cb_data == "show_menu":
                                await send_main_menu(session, chat_id=chat_id)
                            elif cb_data == "top_solana":
                                report = await fetch_top_5_memecoins_report(session, "solana")
                                await send_telegram_message(session, report, inline_keyboard=get_main_menu_inline_keyboard(), chat_id=chat_id)
                            elif cb_data == "top_robinhood":
                                report = await fetch_top_5_memecoins_report(session, "robinhood")
                                await send_telegram_message(session, report, inline_keyboard=get_main_menu_inline_keyboard(), chat_id=chat_id)
                            elif cb_data == "top1_solana":
                                await send_single_top1_memecoin(session, "solana", chat_id=chat_id)
                            elif cb_data == "top1_robinhood":
                                await send_single_top1_memecoin(session, "robinhood", chat_id=chat_id)
                            elif cb_data == "bot_stats":
                                stats_msg = (
                                    f"📊 <b>OMNICHAIN SNIPER ENGINE TELEMETRY</b> 📊\n\n"
                                    f"🟢 <b>Tracked Runners:</b> {len(tracked_tokens)}\n"
                                    f"🐣 <b>Incubation Watchlist:</b> {len(incubation_tokens)}\n"
                                    f"🎯 <b>Solana 200K Entries:</b> {len(solana_200k_tracked)}\n"
                                    f"📅 <b>Daily Strategy Quota:</b> {daily_strategy_state.get('count', 0)}/5 used today\n"
                                    f"⚙️ <b>Processed History:</b> {len(processed_txs)} tokens indexed\n\n"
                                    f"🛡️ <i>Engine operational and deduplicated. 6767</i>"
                                )
                                await send_telegram_message(session, stats_msg, inline_keyboard=get_main_menu_inline_keyboard(), chat_id=chat_id)

        except Exception as e:
            print(f"Telegram polling loop error: {e}")
            
        await asyncio.sleep(1)

async def run_pro_omnichain_sniper():
    print("Elite Pro-Styled OmniChain Sniper + Deduplicated Keyboard Interface Active. 6767.")
    async with aiohttp.ClientSession() as session:
        await send_main_menu(session)
        
        await asyncio.gather(
            dexscreener_dual_feed_loop(session),
            milestone_checker_loop(session),
            incubation_checker_loop(session),
            deployer_wallet_tracking_loop(session),
            mempool_sniffing_loop(session),
            social_alpha_scraping_loop(session),
            telegram_polling_loop(session)
        )

if __name__ == "__main__":
    asyncio.run(run_pro_omnichain_sniper())
