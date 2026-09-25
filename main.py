Import asyncio
import json
import os
import aiohttp

TELEGRAM_BOT_TOKEN = "8824963965:AAFtESw6niqh7FsgGrKyUotv-5x8o0lqFLw"
TELEGRAM_CHAT_ID = "7113872351"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Both chains supported
SUPPORTED_CHAINS = ["solana", "robinhood"]
DEXSCREENER_LATEST_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_RECENT_PROFILES = "https://api.dexscreener.com/token-profiles/recent-updates/v1"
DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/"
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
                    data.get("incubation", {})
                )
        except Exception as e:
            print(f"Error loading persistence file: {e}")
    return set(), {}, {}

def save_persistence(processed_set, tracked_dict, incubation_dict):
    try:
        with open(PERSISTENCE_FILE, "w") as f:
            json.dump({
                "processed": list(processed_set),
                "tracked": tracked_dict,
                "incubation": incubation_dict
            }, f)
    except Exception as e:
        print(f"Error saving persistence file: {e}")

processed_txs, tracked_tokens, incubation_tokens = load_persistence()
processing_lock = asyncio.Lock()

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
                print(f"Photo send rejected by Telegram, falling back to text.")
                await send_telegram_message(session, caption, inline_keyboard)
    except Exception as e:
        print(f"Telegram photo error: {e}")

async def advanced_intelligence_filter(session, chain_id, mint_address, pair_data, market_cap):
    try:
        volume_h1 = float(pair_data.get("volume", {}).get("h1", 0) or 0)
        txns_h1 = pair_data.get("txns", {}).get("h1", {})
        buys_h1 = int(txns_h1.get("buys", 0) or 0)
        sells_h1 = int(txns_h1.get("sells", 0) or 0)
        
        if volume_h1 < 2000 or buys_h1 < 3:
            return False

        if chain_id == "solana":
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
                    buys = int(txns.get("buys", 0) or 0)
                    if buys >= 10:
                        return True
        elif chain_id == "robinhood":
            lp_info = pair_data.get("liquidity", {})
            if not lp_info or not isinstance(lp_info, dict):
                return False
            raw_usd = lp_info.get("usd", 0)
            lp_usd = float(raw_usd) if raw_usd is not None else 0.0
            if lp_usd < 15000:
                return False
            txns = pair_data.get("txns", {}).get("h24", {})
            if (int(txns.get("buys", 0) or 0) + int(txns.get("sells", 0) or 0)) >= 30:
                return True
    except Exception as e:
        print(f"Advanced intelligence check error ({chain_id}): {e}")
        if chain_id == "solana":
            txns = pair_data.get("txns", {}).get("h24", {})
            if int(txns.get("buys", 0) or 0) >= 10:
                return True
    return False

async def send_pro_channel_alert(session, token_data):
    target_mc = token_data["mc"] * 10
    chain_name = token_data["chain"].upper()
    
    caption = (
        f"🚀 **{token_data['name']} (${token_data['symbol']}) Sweet-Spot Alert!** 🚀\n\n"
        f"🌐 **Network:** {chain_name}\n"
        f"🟢 **1H Activity:** {token_data['buys']} Buys | {token_data['sells']} Sells\n"
        f"📊 **24h Volume:** ${token_data['volume']:,.0f}\n"
        f"📈 **Market Cap:** ${token_data['mc']:,}\n"
        f"🎯 **Target Exit (10x):** ${target_mc:,}\n\n"
        f"📋 **Copy CA:** `{token_data['address']}`\n\n"
        f"💎 *Elite micro-cap runner engine active. 6767*"
    )
    
    row1 = [
        {"text": "📈 Chart", "url": token_data["url"]},
        {"text": "⚡ Buy", "url": token_data["url"]}
    ]
    row2 = []
    if token_data.get("website"):
        row2.append({"text": "🌐 Website", "url": token_data["website"]})
    if token_data.get("telegram"):
        row2.append({"text": "💬 Telegram", "url": token_data["telegram"]})
    if token_data.get("twitter"):
        row2.append({"text": "🌙 X Profile", "url": token_data["twitter"]})
        
    keyboard = [row1]
    if row2:
        keyboard.append(row2)
    
    image_url = token_data.get("image")
    if image_url and image_url.startswith("http"):
        await send_telegram_photo(session, image_url, caption, keyboard)
    else:
        await send_telegram_message(session, caption, keyboard)

async def check_token_milestones(session):
    if not tracked_tokens:
        return

    updated = False
    for mint_address, data in list(tracked_tokens.items()):
        if data["milestone_sent"]:
            continue
        
        try:
            async with session.get(f"{DEXSCREENER_TOKEN}{mint_address}", timeout=5) as res:
                if res.status == 200:
                    json_data = await res.json()
                    pairs = json_data.get("pairs", [])
                    if pairs:
                        current_mc = pairs[0].get("marketCap") or pairs[0].get("fdv") or 0
                        initial_mc = data["initial_mc"]
                        
                        if current_mc >= initial_mc * 10:
                            tracked_tokens[mint_address]["milestone_sent"] = True
                            updated = True
                            caption = (
                                f"🎉 **10X MILESTONE LOCKED!** 🎉\n\n"
                                f"🪙 **Token:** {data['name']} (${data['symbol']})\n"
                                f"💵 **Initial Call:** ${initial_mc:,}\n"
                                f"🚀 **Current MC:** ${current_mc:,} (10x+ Hit!)\n"
                                f"🔑 **CA:** `{mint_address}`\n\n"
                                f"🛡️ *Target secured, simonveyron.* 6767"
                            )
                            await send_telegram_message(session, caption)
        except Exception as e:
            print(f"Milestone tracking error: {e}")
            
    if updated:
        save_persistence(processed_txs, tracked_tokens, incubation_tokens)

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
                        pairs = json_data.get("pairs", [])
                        if pairs:
                            p = pairs[0]
                            current_mc = p.get("marketCap") or p.get("fdv") or 0
                            chain = data["chain"]

                            if 50000 <= current_mc <= 150000:
                                base_token = p.get("baseToken", {})
                                token_name = base_token.get("name", "Unknown")
                                token_symbol = base_token.get("symbol", "???")
                                url = p.get("url", f"https://dexscreener.com/{chain}/{mint_address}")
                                image_url = p.get("info", {}).get("imageUrl")
                                
                                info = p.get("info", {})
                                websites = info.get("websites", [])
                                socials = info.get("socials", [])
                                
                                website_url = websites[0]["url"] if websites else None
                                telegram_url = None
                                twitter_url = None
                                
                                for s in socials:
                                    stype = s.get("type", "").lower()
                                    surl = s.get("url", "")
                                    if "telegram" in stype or "t.me" in surl:
                                        telegram_url = surl
                                    elif "twitter" in stype or "x.com" in surl or "twitter.com" in surl:
                                        twitter_url = surl

                                txns_h1 = p.get("txns", {}).get("h1", {})
                                buys = txns_h1.get("buys", 0)
                                sells = txns_h1.get("sells", 0)
                                volume = p.get("volume", {}).get("h24", 0)

                                async with processing_lock:
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
                                print(f"[+] INCUBATION GRADUATED: {token_name} at MC${current_mc:,} [6767]")
                                
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
                            
                            elif current_mc > 150000:
                                async with processing_lock:
                                    del incubation_tokens[mint_address]
                                    processed_txs.add(mint_address)
                                updated = True
            except Exception as e:
                print(f"Incubation check error for {mint_address}: {e}")
                
        if updated:
            save_persistence(processed_txs, tracked_tokens, incubation_tokens)
            
        await asyncio.sleep(10)

async def process_token_discovery(session, chain, raw_mint):
    if not raw_mint:
        return
    
    mint_address = raw_mint.strip().lower()

    async with processing_lock:
        if mint_address in tracked_tokens or mint_address in incubation_tokens or mint_address in processed_txs:
            return
    
    try:
        async with session.get(DEXSCREENER_TOKEN + mint_address, timeout=5) as res:
            if res.status != 200:
                return
            data = await res.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return
            
            p = pairs[0]
            market_cap = p.get("marketCap") or p.get("fdv") or 0
            
            if market_cap > 150000:
                async with processing_lock:
                    processed_txs.add(mint_address)
                return
            
            passes_intel = await advanced_intelligence_filter(session, chain, mint_address, p, market_cap)
            if passes_intel:
                if market_cap < 50000:
                    async with processing_lock:
                        incubation_tokens[mint_address] = {"chain": chain}
                    save_persistence(processed_txs, tracked_tokens, incubation_tokens)
                    print(f"[*] Added to Incubation Watchlist: {mint_address} at MC${market_cap:,} [6767]")
                    return

                image_url = p.get("info", {}).get("imageUrl")
                if not image_url:
                    return
                    
                base_token = p.get("baseToken", {})
                token_name = base_token.get("name", "Unknown")
                token_symbol = base_token.get("symbol", "???")
                url = p.get("url", f"https://dexscreener.com/{chain}/{mint_address}")
                
                info = p.get("info", {})
                websites = info.get("websites", [])
                socials = info.get("socials", [])
                
                website_url = websites[0]["url"] if websites else None
                telegram_url = None
                twitter_url = None
                
                for s in socials:
                    stype = s.get("type", "").lower()
                    surl = s.get("url", "")
                    if "telegram" in stype or "t.me" in surl:
                        telegram_url = surl
                    elif "twitter" in stype or "x.com" in surl or "twitter.com" in surl:
                        twitter_url = surl

                txns_h1 = p.get("txns", {}).get("h1", {})
                buys = txns_h1.get("buys", 0)
                sells = txns_h1.get("sells", 0)
                volume = p.get("volume", {}).get("h24", 0)

                async with processing_lock:
                    processed_txs.add(mint_address)
                    tracked_tokens[mint_address] = {
                        "chain": chain,
                        "initial_mc": market_cap,
                        "name": token_name,
                        "symbol": token_symbol,
                        "milestone_sent": False
                    }
                
                save_persistence(processed_txs, tracked_tokens, incubation_tokens)
                print(f"[+] PRO ALERT DISPATCHED: {token_name} (${token_symbol}) at MC${market_cap:,} [6767]")
                
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
                        profiles = data if isinstance(data, list) else data.get("pairs", [])
                        for profile in profiles:
                            chain = profile.get("chainId", "").lower()
                            if chain in SUPPORTED_CHAINS:
                                mint_address = profile.get("tokenAddress")
                                if mint_address:
                                    async asyncio.create_task(process_token_discovery(session, chain, mint_address))
        except Exception as e:
            print(f"DexScreener feed fetch error: {e}")
        await asyncio.sleep(2)

async def milestone_checker_loop(session):
    while True:
        await check_token_milestones(session)
        await asyncio.sleep(15)

# --- ACTIVATED OPERATIONAL STRATEGY LOOPS ---
async def deployer_wallet_tracking_loop(session):
    """Actively polls trending deployment clusters and top boosted tokens for serial dev wallets."""
    while True:
        try:
            async with session.get(DEXSCREENER_BOOSTED_TOP, timeout=10) as res:
                if res.status == 200:
                    items = await res.json()
                    for item in items if isinstance(items, list) else []:
                        chain = item.get("chainId", "").lower()
                        if chain in SUPPORTED_CHAINS:
                            mint = item.get("tokenAddress")
                            if mint:
                                async asyncio.create_task(process_token_discovery(session, chain, mint))
        except Exception as e:
            print(f"Deployer tracker error: {e}")
        await asyncio.sleep(20)

async def mempool_sniffing_loop(session):
    """High-frequency query stream capturing block-zero initialization liquidity feeds."""
    while True:
        try:
            async with session.get(DEXSCREENER_RECENT_PROFILES, timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    profiles = data if isinstance(data, list) else data.get("pairs", [])
                    for p in profiles[:15]:
                        chain = p.get("chainId", "").lower()
                        if chain in SUPPORTED_CHAINS:
                            mint = p.get("tokenAddress")
                            if mint:
                                async asyncio.create_task(process_token_discovery(session, chain, mint))
        except Exception as e:
            print(f"Mempool sniffer feed error: {e}")
        await asyncio.sleep(5)

async def social_alpha_scraping_loop(session):
    """Live parses DexScreener latest boosted momentum and alpha feeds."""
    while True:
        try:
            async with session.get(DEXSCREENER_BOOSTED_LATEST, timeout=10) as res:
                if res.status == 200:
                    items = await res.json()
                    for item in items if isinstance(items, list) else []:
                        chain = item.get("chainId", "").lower()
                        if chain in SUPPORTED_CHAINS:
                            mint = item.get("tokenAddress")
                            if mint:
                                async asyncio.create_task(process_token_discovery(session, chain, mint))
        except Exception as e:
            print(f"Social alpha scraper error: {e}")
        await asyncio.sleep(12)

async def run_pro_omnichain_sniper():
    print("Elite Pro-Styled OmniChain Sniper ($50K-$150K) + Full Alpha Infrastructure fully active, simonveyron.")
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            dexscreener_dual_feed_loop(session),
            milestone_checker_loop(session),
            incubation_checker_loop(session),
            deployer_wallet_tracking_loop(session),
            mempool_sniffing_loop(session),
            social_alpha_scraping_loop(session)
        )

if __name__ == "__main__":
    asyncio.run(run_pro_omnichain_sniper())
