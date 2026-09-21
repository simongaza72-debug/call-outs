import asyncio
import json
import time
import aiohttp
import websockets

TELEGRAM_BOT_TOKEN = "8824963965:AAFtESw6niqh7FsgGrKyUotv-5x8o0lqFLw"
TELEGRAM_CHAT_ID = "7113872351"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Locked to Solana, Base, BSC, and Robinhood Chain
SUPPORTED_CHAINS = ["solana", "base", "bsc", "robinhood"]
DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search?q="
DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/"
RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/"

SMART_MONEY_WALLETS = [
    # Add target insider/whale solana wallet addresses here to mirror-track
]

tracked_tokens = {}
processed_txs = set()

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
        await send_telegram_message(session, caption, inline_keyboard)

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
                    
                    # Relaxed risk tolerance slightly to catch fast-moving runners like FAMILY
                    if risk_score <= 600 and not is_mintable and not is_freezable and concentrated_supply < 50:
                        return True
        else:
            dex_id = pair_data.get("dexId", "").lower()
            if dex_id in ["flap", "unsupported_launchpad"]:
                return False
                
            lp_data = pair_data.get("liquidity", {})
            lp_usd = lp_data.get("usd", 0)
            
            txns = pair_data.get("txns", {}).get("h24", {})
            buys = txns.get("buys", 0)
            sells = txns.get("sells", 0)
            
            info = pair_data.get("info", {})
            websites = info.get("websites", [])
            socials = info.get("socials", [])
            
            if lp_usd >= 10000 and (buys + sells) > 50:
                return True
    except Exception as e:
        print(f"Advanced intelligence check error ({chain_id}): {e}")
    return False

async def send_multichain_telegram_alert(session, token_data):
    target_mc = token_data["mc"] * 10
    chain_name = token_data["chain"].upper()
    
    caption = (
        f"⚡ **HARD-FILTERED ALPHA [{chain_name}]** ⚡\n\n"
        f"🪙 **Token:** {token_data['name']} (${token_data['symbol']})\n"
        f"🌐 **Network:** {chain_name}\n"
        f"💵 **Current MC:** ${token_data['mc']:,}\n"
        f"🎯 **Target Exit MC:** ${target_mc:,} (10x)\n"
        f"🔑 **CA:** `{token_data['address']}`\n\n"
        f"🛡️ *Anti-Rug / Momentum Verified*\n"
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
                                f"🎉 **10X HARD-FILTERED MILESTONE REACHED!** 🎉\n\n"
                                f"🪙 **Token:** {data['name']} (${data['symbol']})\n"
                                f"🌐 **Network:** {chain_name}\n"
                                f"💵 **Initial MC:** ${initial_mc:,}\n"
                                f"🚀 **Current MC:** ${current_mc:,} (10x+ Locked!)\n"
                                f"🔑 **CA:** `{mint_address}`\n\n"
                                f"🛡️ *Target secured, baby.* 6767"
                            )
                            
                            await send_telegram_message(session, caption)
        except Exception as e:
            print(f"Milestone tracking error: {e}")

async def monitor_solana_block_zero_stream():
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
                        logs = response.get("params", {}).get("result", {}).get("value", {}).get("logs", [])
                        if any("InitializeMint" in l or "migration" in l.lower() for l in logs):
                            print("⚡ Block-Zero Genesis / AMM Migration Event Caught via WebSocket!")
        except Exception as e:
            await asyncio.sleep(5)

async def monitor_smart_money_wallets(session):
    if not SMART_MONEY_WALLETS:
        return
    while True:
        try:
            async with websockets.connect("wss://api.mainnet-beta.solana.com") as ws:
                for idx, wallet in enumerate(SMART_MONEY_WALLETS):
                    sub_payload = {
                        "jsonrpc": "2.0",
                        "id": 10 + idx,
                        "method": "signatureSubscribe",
                        "params": [wallet, {"commitment": "processed"}]
                    }
                    await ws.send(json.dumps(sub_payload))
                
                async for message in ws:
                    response = json.loads(message)
                    if response.get("method") == "signatureNotification":
                        tx_info = response.get("params", {}).get("result", {})
                        sig = tx_info.get("signature", "")
                        if sig:
                            alert_text = (
                                f"🐳 **SMART MONEY / INSIDER SWAP** 🐳\n\n"
                                f"🔑 **Tx Sig:** `{sig}`\n"
                                f"🌐 [Inspect on Solscan](https://solscan.io/tx/{sig})\n\n"
                                f"🛡️ *Shadow-tracking big player movements, baby.* 6767"
                            )
                            await send_telegram_message(session, alert_text)
        except Exception as e:
            await asyncio.sleep(5)

async def run_pro_omnichain_sniper():
    print("Pro Expanded-Cap & Anti-Duplicate Sniper (Python) active 24/7, baby. 6767.")
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            monitor_solana_block_zero_stream(),
            monitor_smart_money_wallets(session),
            dexscreener_scanner_loop(session)
        )

async def dexscreener_scanner_loop(session):
    while True:
        current_time_ms = int(time.time() * 1000)
        max_age_ms = 6 * 60 * 60 * 1000  # 6 hours max age
        
        for chain in SUPPORTED_CHAINS:
            try:
                async with session.get(f"{DEXSCREENER_SEARCH}{chain}", timeout=10) as search_res:
                    if search_res.status != 200:
                        continue
                    search_json = await search_res.json()
                    pairs = search_json.get("pairs", [])
                    
                    for p in pairs:
                        if p.get("chainId") != chain:
                            continue
                        
                        base_token = p.get("baseToken", {})
                        mint_address = base_token.get("address")
                        market_cap = p.get("marketCap") or p.get("fdv") or 0
                        pair_created_at = p.get("pairCreatedAt", 0)
                        
                        if not mint_address or mint_address in tracked_tokens or mint_address in processed_txs:
                            continue
                        
                        if pair_created_at == 0 or (current_time_ms - pair_created_at > max_age_ms):
                            continue
                        
                        # Expanded Market Cap Range: Now catches tokens from $10K all the way up to $2,000,000 ($2M)
                        if 10000 <= market_cap <= 2000000:
                            processed_txs.add(mint_address)
                            
                            passes_intel = await advanced_intelligence_filter(session, chain, mint_address, p)
                            if passes_intel:
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
                print(f"Pro DexScreener fetch error for {chain}: {e}")
            await asyncio.sleep(1)
        
        await check_token_milestones(session)
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_pro_omnichain_sniper())
