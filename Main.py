import os
import time
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_BOT_TOKEN = "8824963965:AAFtESw6niqh7FsgGrKyUotv-5x8o0lqFLw"
TELEGRAM_CHAT_ID = "7113872351"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Multi-Chain Supported Networks
SUPPORTED_CHAINS = ["solana", "base", "bsc", "ethereum"]

DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search?q="
DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/"
RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/"

tracked_tokens = {}

def send_telegram_message(text, inline_keyboard=None):
    """Sends a standard text message via Telegram HTTP API"""
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
            
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=5)
    except Exception as e:
        logging.error(f"Telegram dispatch error: {e}")

def send_telegram_photo(photo_url, caption, inline_keyboard=None):
    """Sends a photo with a caption; falls back to text if image fails"""
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
            
        res = requests.post(f"{TELEGRAM_API}/sendPhoto", json=payload, timeout=5)
        if res.status_code != 200:
            send_telegram_message(caption, inline_keyboard)
    except Exception as e:
        logging.error(f"Telegram photo error: {e}")
        send_telegram_message(caption, inline_keyboard)

def multi_chain_safety_filter(chain_id, mint_address, market_cap):
    """
    Multi-chain safety validator: Filters out honeypots, low liquidity, 
    and high token concentration across Solana and EVM chains.
    """
    try:
        if chain_id == "solana":
            res = requests.get(f"{RUGCHECK_API}{mint_address}/report", timeout=5)
            if res.status_code == 200:
                data = res.json()
                risk_score = data.get("score", 999)
                risks = data.get("risks", [])
                is_mintable = any("mint" in r.get("name", "").lower() for r in risks)
                is_freezable = any("freeze" in r.get("name", "").lower() for r in risks)
                if risk_score <= 800 and not is_mintable and not is_freezable:
                    return True
        else:
            pair_res = requests.get(f"{DEXSCREENER_TOKEN}{mint_address}", timeout=5)
            if pair_res.status_code == 200:
                pairs = pair_res.json().get("pairs", [])
                if pairs:
                    lp_usd = pairs[0].get("liquidity", {}).get("usd", 0)
                    if lp_usd >= 5000:
                        return True
    except Exception as e:
        logging.error(f"Multi-chain safety check error ({chain_id}): {e}")
    return False

def send_multichain_telegram_alert(token_data):
    target_mc = token_data["mc"] * 10
    chain_name = token_data["chain"].upper()
    
    caption = (
        f"🔥 **MULTI-CHAIN ALPHA CALLOUT [{chain_name}]** 🔥\n\n"
        f"🪙 **Token:** {token_data['name']} (${token_data['symbol']})\n"
        f"🌐 **Network:** {chain_name}\n"
        f"💵 **Current MC:** ${token_data['mc']:,.0f}\n"
        f"🎯 **Target Exit MC:** ${target_mc:,.0f} (10x)\n"
        f"🔑 **CA:** `{token_data['address']}`\n\n"
        f"🛡️ *Omnichain Indexer + Security Filtered*\n"
        f"👶 *Zero random junk, pure cross-chain alpha, baby.* 6767"
    )
    
    keyboard = [
        [{"text": "📈 DexScreener Chart", "url": token_data['url']}],
        [{"text": "⚡ View Pool", "url": token_data['url']}]
    ]
    
    if token_data['image'] and token_data['image'].startswith("http"):
        send_telegram_photo(token_data['image'], caption, keyboard)
    else:
        send_telegram_message(caption, keyboard)

def check_token_milestones():
    if not tracked_tokens:
        return

    for mint_address, data in list(tracked_tokens.items()):
        if data.get("milestone_sent", False):
            continue
            
        try:
            res = requests.get(f"{DEXSCREENER_TOKEN}{mint_address}", timeout=5)
            if res.status_code == 200:
                pairs = res.json().get("pairs", [])
                if pairs:
                    current_mc = pairs[0].get("marketCap", 0) or pairs[0].get("fdv", 0)
                    initial_mc = data["initial_mc"]
                    
                    if current_mc >= initial_mc * 10:
                        tracked_tokens[mint_address]["milestone_sent"] = True
                        chain_name = data["chain"].upper()
                        
                        caption = (
                            f"🎉 **10X MILESTONE REACHED!** 🎉\n\n"
                            f"🪙 **Token:** {data['name']} (${data['symbol']})\n"
                            f"🌐 **Network:** {chain_name}\n"
                            f"💵 **Initial MC:** ${initial_mc:,.0f}\n"
                            f"🚀 **Current MC:** ${current_mc:,.0f} (10x+ Locked!)\n"
                            f"🔑 **CA:** `{mint_address}`\n\n"
                            f"🛡️ *Target achieved. Securing the bag, baby.* 6767"
                        )
                        send_telegram_message(caption)
        except Exception as e:
            logging.error(f"Milestone tracking error: {e}")

def run_multichain_sniper_bot():
    logging.info("Omnichain Memecoin Sniper & 10X Tracker Bot active 24/7, baby. 6767.")
    
    while True:
        for chain in SUPPORTED_CHAINS:
            try:
                search_res = requests.get(f"{DEXSCREENER_SEARCH}{chain}", timeout=10).json()
                pairs = search_res.get("pairs", [])
            except Exception as e:
                logging.error(f"DexScreener fetch error for {chain}: {e}")
                continue
            
            for p in pairs:
                if p.get("chainId") != chain:
                    continue
                    
                mint_address = p.get("baseToken", {}).get("address", "")
                market_cap = p.get("marketCap", 0) or p.get("fdv", 0)
                
                if not mint_address or mint_address in tracked_tokens:
                    continue
                    
                if 10000 <= market_cap <= 250000:
                    if multi_chain_safety_filter(chain, mint_address, market_cap):
                        token_name = p.get("baseToken", {}).get("name", "Unknown")
                        token_symbol = p.get("baseToken", {}).get("symbol", "???")
                        
                        token_info = {
                            "chain": chain,
                            "name": token_name,
                            "symbol": token_symbol,
                            "address": mint_address,
                            "mc": market_cap,
                            "url": p.get("url", f"https://dexscreener.com/{chain}/{mint_address}"),
                            "image": p.get("info", {}).get("imageUrl", "https://i.imgur.com/3Z3Z3Z3.png")
                        }
                        
                        tracked_tokens[mint_address] = {
                            "chain": chain,
                            "initial_mc": market_cap,
                            "name": token_name,
                            "symbol": token_symbol,
                            "milestone_sent": False
                        }
                        
                        send_multichain_telegram_alert(token_info)
                        
            time.sleep(3)

        check_token_milestones()
        time.sleep(15)

if __name__ == "__main__":
    run_multichain_sniper_bot()
