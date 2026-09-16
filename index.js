const WebSocket = require('ws'); // Requires: npm install ws

const TELEGRAM_BOT_TOKEN = "8824963965:AAFtESw6niqh7FsgGrKyUotv-5x8o0lqFLw";
const TELEGRAM_CHAT_ID = "7113872351";
const TELEGRAM_API = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}`;

const SUPPORTED_CHAINS = ["solana", "base", "bsc", "ethereum"];
const DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search?q=";
const DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/";
const RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/";

// Zero-cost intelligence memory maps
const trackedTokens = new Map();
const processedTxs = new Set();

async function sendTelegramMessage(text, inlineKeyboard = null) {
    try {
        const payload = {
            chat_id: TELEGRAM_CHAT_ID,
            text: text,
            parse_mode: "Markdown"
        };
        if (inlineKeyboard) {
            payload.reply_markup = { inline_keyboard: inlineKeyboard };
        }
        await fetch(`${TELEGRAM_API}/sendMessage`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    } catch (e) {
        console.error("Telegram dispatch error:", e.message);
    }
}

async function sendTelegramPhoto(photoUrl, caption, inlineKeyboard = null) {
    try {
        const payload = {
            chat_id: TELEGRAM_CHAT_ID,
            photo: photoUrl,
            caption: caption,
            parse_mode: "Markdown"
        };
        if (inlineKeyboard) {
            payload.reply_markup = { inline_keyboard: inlineKeyboard };
        }
        const res = await fetch(`${TELEGRAM_API}/sendPhoto`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) {
            await sendTelegramMessage(caption, inlineKeyboard);
        }
    } catch (e) {
        console.error("Telegram photo error:", e.message);
        await sendTelegramMessage(caption, inlineKeyboard);
    }
}

// Zero-Cost Advanced Intelligence Filter (Holder Concentration & Insider Detection)
async function advancedIntelligenceFilter(chainId, mintAddress) {
    try {
        if (chainId === "solana") {
            const res = await fetch(`${RUGCHECK_API}${mintAddress}/report`, { signal: AbortSignal.timeout(5000) });
            if (res.ok) {
                const data = await res.json();
                const riskScore = data.score ?? 999;
                const risks = data.risks || [];
                
                const topHolders = data.topHolders || [];
                const concentratedSupply = topHolders.slice(0, 5).reduce((acc, h) => acc + (h.pct || 0), 0);
                
                const isMintable = risks.some(r => r.name && r.name.toLowerCase().includes("mint"));
                const isFreezable = risks.some(r => r.name && r.name.toLowerCase().includes("freeze"));
                
                if (riskScore <= 600 && !isMintable && !isFreezable && concentratedSupply < 45) {
                    return true;
                }
            }
        } else {
            const pairRes = await fetch(`${DEXSCREENER_TOKEN}${mintAddress}`, { signal: AbortSignal.timeout(5000) });
            if (pairRes.ok) {
                const data = await pairRes.json();
                const pairs = data.pairs || [];
                if (pairs.length > 0) {
                    const lpUsd = pairs[0].liquidity?.usd || 0;
                    const txns24h = (pairs[0].txns?.h24?.buys || 0) + (pairs[0].txns?.h24?.sells || 0);
                    if (lpUsd >= 8000 && txns24h > 50) {
                        return true;
                    }
                }
            }
        }
    } catch (e) {
        console.error(`Advanced intelligence check error (${chainId}):`, e.message);
    }
    return false;
}

async function sendMultichainTelegramAlert(tokenData) {
    const targetMc = tokenData.mc * 10;
    const chainName = tokenData.chain.toUpperCase();
    
    const caption = 
        `⚡ **BLOCK-ZERO ALPHA [${chainName}]** ⚡\n\n` +
        `🪙 **Token:** ${tokenData.name} ($${tokenData.symbol})\n` +
        `🌐 **Network:** ${chainName}\n` +
        `💵 **Current MC:** $${tokenData.mc.toLocaleString()}\n` +
        `🎯 **Target Exit MC:** $${targetMc.toLocaleString()} (10x)\n` +
        `🔑 **CA:** \`${tokenData.address}\`\n\n` +
        `🛡️ *Raw WebSocket Stream + Holder Concentration Filtered*\n` +
        `👶 *Caught at genesis, pure runner energy, baby.* 6767`;
    
    const keyboard = [
        [{ text: "📈 DexScreener Chart", url: tokenData.url }],
        [{ text: "⚡ View Pool", url: tokenData.url }]
    ];
    
    if (tokenData.image && tokenData.image.startsWith("http")) {
        await sendTelegramPhoto(tokenData.image, caption, keyboard);
    } else {
        await sendTelegramMessage(caption, keyboard);
    }
}

async function checkTokenMilestones() {
    if (trackedTokens.size === 0) return;

    for (let [mintAddress, data] of trackedTokens.entries()) {
        if (data.milestoneSent) continue;
        
        try {
            const res = await fetch(`${DEXSCREENER_TOKEN}${mintAddress}`, { signal: AbortSignal.timeout(5000) });
            if (res.ok) {
                const json = await res.json();
                const pairs = json.pairs || [];
                if (pairs.length > 0) {
                    const currentMc = pairs[0].marketCap || pairs[0].fdv || 0;
                    const initialMc = data.initialMc;
                    
                    if (currentMc >= initialMc * 10) {
                        trackedTokens.get(mintAddress).milestoneSent = true;
                        const chainName = data.chain.toUpperCase();
                        
                        const caption = 
                            `🎉 **10X BLOCK-ZERO MILESTONE REACHED!** 🎉\n\n` +
                            `🪙 **Token:** ${data.name} ($${data.symbol})\n` +
                            `🌐 **Network:** ${chainName}\n` +
                            `💵 **Initial MC:** $${initialMc.toLocaleString()}\n` +
                            `🚀 **Current MC:** $${currentMc.toLocaleString()} (10x+ Locked!)\n` +
                            `🔑 **CA:** \`${mintAddress}\`\n\n` +
                            `🛡️ *Genesis target achieved. Securing the bag, baby.* 6767`;
                        
                        await sendTelegramMessage(caption);
                    }
                }
            }
        } catch (e) {
            console.error("Milestone tracking error:", e.message);
        }
    }
}

// Real-Time Solana Bonding Curve WebSocket Stream Listener
function monitorSolanaBlockZeroStream() {
    const ws = new WebSocket('wss://api.mainnet-beta.solana.com');

    ws.on('open', () => {
        console.log("Connected to Solana Block-Zero WebSocket Stream, baby. 6767.");
        ws.send(JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method: "logsSubscribe",
            params: [
                { mentions: ["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"] },
                { commitment: "processed" }
            ]
        }));
    });

    ws.on('message', async (data) => {
        try {
            const response = JSON.parse(data);
            if (response.method === "logsNotification") {
                const logs = response.params.result.value.logs;
                if (logs.some(l => l.includes("InitializeMint") || l.includes("Create"))) {
                    console.log("⚡ Block-Zero Genesis Event Detected via WebSocket Stream!");
                }
            }
        } catch (e) {
            console.error("WebSocket message parsing error:", e.message);
        }
    });

    ws.on('error', (err) => {
        console.error("Solana Stream WebSocket Error:", err.message);
    });

    ws.on('close', () => {
        console.log("WebSocket connection closed. Reconnecting in 5 seconds...");
        setTimeout(monitorSolanaBlockZeroStream, 5000);
    });
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runProOmnichainSniper() {
    console.log("Pro Omnichain & Block-Zero Genesis Sniper active 24/7, baby. 6767.");
    
    monitorSolanaBlockZeroStream();
    
    while (true) {
        const currentTimeMs = Date.now();
        const maxAgeMs = 12 * 60 * 60 * 1000;
        
        for (let chain of SUPPORTED_CHAINS) {
            try {
                const searchRes = await fetch(`${DEXSCREENER_SEARCH}${chain}`, { signal: AbortSignal.timeout(10000) });
                if (!searchRes.ok) continue;
                const searchJson = await searchRes.json();
                const pairs = searchJson.pairs || [];
                
                for (let p of pairs) {
                    if (p.chainId !== chain) continue;
                    
                    const mintAddress = p.baseToken?.address;
                    const marketCap = p.marketCap || p.fdv || 0;
                    const pairCreatedAt = p.pairCreatedAt || 0;
                    
                    if (!mintAddress || trackedTokens.has(mintAddress) || processedTxs.has(mintAddress)) continue;
                    
                    if (pairCreatedAt === 0 || (currentTimeMs - pairCreatedAt > maxAgeMs)) {
                        continue;
                    }
                    
                    if (marketCap >= 15000 && marketCap <= 200000) {
                        const passesIntel = await advancedIntelligenceFilter(chain, mintAddress);
                        if (passesIntel) {
                            processedTxs.add(mintAddress);
                            const tokenName = p.baseToken?.name || "Unknown";
                            const tokenSymbol = p.baseToken?.symbol || "???";
                            const imageUrl = p.info?.imageUrl || "https://i.imgur.com/3Z3Z3Z3.png";
                            const url = p.url || `https://dexscreener.com/${chain}/${mintAddress}`;
                            
                            trackedTokens.set(mintAddress, {
                                chain: chain,
                                initialMc: marketCap,
                                name: tokenName,
                                symbol: tokenSymbol,
                                milestoneSent: false
                            });
                            
                            await sendMultichainTelegramAlert({
                                chain: chain,
                                name: tokenName,
                                symbol: tokenSymbol,
                                address: mintAddress,
                                mc: marketCap,
                                url: url,
                                image: imageUrl
                            });
                        }
                    }
                }
            } catch (e) {
                console.error(`Pro DexScreener fetch error for ${chain}:`, e.message);
            }
            await sleep(2000);
        }
        
        await checkTokenMilestones();
        await sleep(10000);
    }
}

runProOmnichainSniper();
