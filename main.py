import asyncio
import json
import time
import aiohttp
import websockets

TELEGRAM_BOT_TOKEN = "8824963965:AAFtESw6niqh7FsgGrKyUotv-5x8o0lqFLw"
TELEGRAM_CHAT_ID = "7113872351"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Locked exclusively to Solana and Robinhood Chain
SUPPORTED_CHAINS = ["solana", "robinhood"]
DEXSCREENER_LATEST_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/"
RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/"

tracked_tokens = {}
processed_txs = set()
processing_lock = asyncio.Lock()  # Atomic lock prevents double-processing entirely

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
                print(f"Photo send rejected by Telegram, skipping photo to prevent duplicates.")
    except Exception as e:
        print(f"Telegram photo error: {e}")

async def advanced_intelligence_filter(session, chain_id, mint_address, pair_data):
    try:
        if chain_id == "solana":
            async with session.get(f"{RUGCHECK_API}{mint_address}/report", timeout=5) as res:
                if res.status == 200:
                    data = await res.json()
                    risk_score = data.get("score", 999)
                    risks = data.get("risks", [])
                    top_holders = data.get("topHolders", [])
                    concentrated_supply = sum([h.get("pct", 0) for h in top_holders[:5]])
                    
                    is_mintable = any(r.get("name", "").lower().find("mint") != -1 for r in risks)
                    is_freezable = any(r.get("name", "").lower().find("freeze") != -1 for r in risks)
                    
                    if risk_score <= 400 and not is_mintable and not is_freezable and concentrated_supply < 40:
                        return True
        elif chain_id == "robinhood":
            lp_info = pair_data.get("liquidity", {})
            if not lp_info or not isinstance(lp_info, dict):
                return False
            
            # Safely parse liquidity to avoid type errors or bypassed nulls
            raw_usd = lp_info.get("usd", 0)
            lp_usd = float(raw_usd) if raw_usd is not None else 0.0
            
            # Hard liquidity floor to block rugged or low-liquidity pools
            if lp_usd < 15000:
                return False
                
            txns = pair_data.get("txns", {}).get("h24", {})
            buys = int(txns.get("buys", 0) or 0)
            sells = int(txns.get("sells", 0) or 0)
            
            if (buys + sells) >= 30:
                return True
    except Exception as e:
        print(f"Advanced intelligence check error ({chain_id}): {e}")
    return False

async def send_multichain_telegram_alert(session, token_data):
    target_mc = token_data["mc"] * 10
    chain_name = token_data["chain"].upper()
    
    caption = (
        f"⚡ **SECURE SWEET-SPOT ALPHA [{chain_name}]** ⚡\n\n"
        f"🪙 **Token:** {token_data['name']} (${token_data['symbol']})\n"
        f"🌐 **Network:** {chain_name}\n"
        f"💵 **Current MC:** ${token_data['mc']:,}\n"
        f"🎯 **Target Exit MC:** ${target_mc:,} (10x)\n"
        f"🔑 **CA:** `{token_data['address']}`\n\n"
        f"🛡️ *Strict Liquidity & Safety Verified*\n"
        f"👶 *Pure runner energy, baby.* 6767"
    )
    
    keyboard = [
        [{"text": "📈 DexScreener Chart", "url": token_data["url"]}],
        [{"text": "⚡ View Pool", "url": token_data["url"]}]
    ]
    
    image_url = token_data.get("image")
    if image_url and image_url.startswith("http") and "imgur" not in image_url:
        await send_telegram_photo(session, image_url, caption, keyboard)
    else:
        await send_telegram_message(session, caption, keyboard)

async def check_token_milestones(session):
    if not tracked_tokens:
        return

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
                            chain_name = data["chain"].upper()
                            
                            caption = (
                                f"🎉 **10X SWEET-SPOT MILESTONE REACHED!** 🎉\n\n"
                                f"🪙 **Token:** {data['name']} (${data['symbol']})\n"
                                f"🌐 **Network:** {chain_name}\n"
                                f"💵 **Initial Call MC:** ${initial_mc:,}\n"
                                f"🚀 **Current MC:** ${current_mc:,} (10x+ Locked!)\n"
                                f"🔑 **CA:** `{mint_address}`\n\n"
                                f"🛡️ *Target secured, baby.* 6767"
                            )
                            
                            await send_telegram_message(session, caption)
        except Exception as e:
            print(f"Milestone tracking error: {e}")

async def process_token_discovery(session, chain, raw_mint):
    if not raw_mint:
        return
    
    # Normalize address to lowercase to completely prevent casing-based double sends
    mint_address = raw_mint.strip().lower()

    async with processing_lock:
        if mint_address in tracked_tokens or mint_address in processed_txs:
            return
        processed_txs.add(mint_address)
    
    try:
        async with session.get(f"{DEXSCREENER_TOKEN}{mint_address}", timeout=5) as res:
            if res.status != 200:
                return
            data = await res.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return
            
            p = pairs[0]
            market_cap = p.get("marketCap") or p.get("fdv") or 0
            
            # STRICT RANGE: $50K to $150K Market Cap
            if 50000 <= market_cap <= 150000:
                passes_intel = await advanced_intelligence_filter(session, chain, mint_address, p)
                if passes_intel:
                    base_token = p.get("baseToken", {})
                    token_name = base_token.get("name", "Unknown")
                    token_symbol = base_token.get("symbol", "???")
                    image_url = p.get("info", {}).get("imageUrl")
                    url = p.get("url", f"https://dexscreener.com/{chain}/{mint_address}")
                    
                    tracked_tokens[mint_address] = {
                        "chain": chain,
                        "initial_mc": market_cap,
                        "name": token_name,
                        "symbol": token_symbol,
                        "milestone_sent": False
                    }
                    
                    await send_multichain_telegram_alert(session, {
                        "chain": chain,
                        "name": token_name,
                        "symbol": token_symbol,
                        "address": mint_address,
                        "mc": market_cap,
                        "url": url,
                        "image": image_url
                    })
    except Exception as e:
        print(f"Error processing token discovery {mint_address}: {e}")

async def monitor_solana_block_zero_stream(session):
    while True:
        try:
            async with websockets.connect("wss://api.mainnet-beta.solana.com") as ws:
                sub_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": ["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"]},
                        {"commitment": "processed"}
                    ]
                }
                await ws.send(json.dumps(sub_payload))
                async for message in ws:
                    response = json.loads(message)
                    if response.get("method") == "logsNotification":
                        result = response.get("params", {}).get("result", {}).get("value", {})
                        logs = result.get("logs", [])
                        err = result.get("err")
                        if err is None and any("InitializeMint" in l or "Create" in l for l in logs):
                            sig = result.get("signature")
                            if sig:
                                async with session.get(f"https://api.mainnet-beta.solana.com", json={
                                    "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                                    "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                                }) as tx_res:
                                    if tx_res.status == 200:
                                        tx_data = await tx_res.json()
                                        account_keys = tx_data.get("result", {}).get("transaction", {}).get("message", {}).get("accountKeys", [])
                                        if account_keys:
                                            mint_addr = account_keys[0].get("pubkey") if isinstance(account_keys[0], dict) else account_keys[0]
                                            if mint_addr:
                                                asyncio.create_task(process_token_discovery(session, "solana", mint_addr))
        except Exception as e:
            print(f"Solana WS stream error: {e}")
            await asyncio.sleep(5)

async def dexscreener_profiles_loop(session):
    while True:
        try:
            async with session.get(DEXSCREENER_LATEST_PROFILES, timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    profiles = data if isinstance(data, list) else data.get("pairs", [])
                    for profile in profiles:
                        chain = profile.get("chainId", "").lower()
                        if chain in SUPPORTED_CHAINS:
                            mint_address = profile.get("tokenAddress")
                            if mint_address:
                                await process_token_discovery(session, chain, mint_address)
        except Exception as e:
            print(f"DexScreener profile fetch error: {e}")
        await asyncio.sleep(5)

async def milestone_checker_loop(session):
    while True:
        await check_token_milestones(session)
        await asyncio.sleep(15)

async def run_pro_omnichain_sniper():
    print("Fully Sanitized Sniper ($50K-$150K + Strict Liquidity Floor) active 24/7, baby. 6767.")
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            monitor_solana_block_zero_stream(session),
            dexscreener_profiles_loop(session),
            milestone_checker_loop(session)
        )

if __name__ == "__main__":
    asyncio.run(run_pro_omnichain_sniper())
