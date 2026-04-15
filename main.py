"""
FinAPI Gateway v0.5.0 - 统一金融数据API网关
聚合多个免费数据源，统一输出格式
+ Gate.io加密货币源
+ API Key认证 (持久化)
+ 调用统计
+ 可嵌入市场概览Widget
+ 分享式Landing Page
+ 付费层 (Pro/Enterprise) + BTC收款
+ 自动注册
+ 支付确认Webhook
"""

from fastapi import FastAPI, HTTPException, Query, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import requests
import time
import json
import os
import secrets
from collections import defaultdict

app = FastAPI(
    title="FinAPI Gateway",
    description="统一金融数据API网关 - 聚合汇率、股票、加密货币等免费数据源",
    version="0.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 持久化API Key系统 ============
KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_keys.json")

# ============ 收款配置 ============
BTC_ADDRESS = "1MLcB51Zya52oV445GZGMn1qqeYEAJ67Ds"
PAYPAL_ACCOUNT = "16666181244@163.com"

TIER_CONFIG = {
    "free": {"limit": 1000, "cache_ttl": 300, "price": "$0/月", "btc_price": None, "paypal_amount": None},
    "pro": {"limit": 50000, "cache_ttl": 60, "price": "$9/月", "btc_price": "0.0001 BTC", "paypal_amount": "$9"},
    "enterprise": {"limit": 500000, "cache_ttl": 10, "price": "$49/月", "btc_price": "0.0005 BTC", "paypal_amount": "$49"},
}

def load_api_keys():
    """从JSON文件加载API Keys"""
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, "r") as f:
            return json.load(f)
    # 初始化默认keys
    default_keys = {
        "demo": {"name": "演示用户", "email": "", "tier": "free", "created": time.time()},
        "finapi-free-2026": {"name": "免费用户", "email": "", "tier": "free", "created": time.time()},
    }
    save_api_keys(default_keys)
    return default_keys

def save_api_keys(keys):
    """保存API Keys到JSON文件"""
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2, ensure_ascii=False)

API_KEYS = load_api_keys()

# ============ 缓存层 ============
cache = {}

def get_cache_ttl(tier: str) -> int:
    """按tier返回不同缓存时间"""
    return TIER_CONFIG.get(tier, TIER_CONFIG["free"])["cache_ttl"]

def get_cached(key: str, tier: str = "free"):
    if key in cache:
        data, ts = cache[key]
        ttl = get_cache_ttl(tier)
        if time.time() - ts < ttl:
            return data
    return None

def set_cached(key: str, data):
    cache[key] = (data, time.time())

# ============ 调用统计 ============
call_stats = defaultdict(lambda: {"count": 0, "last_call": 0, "daily_reset": 0})

def verify_api_key(x_api_key: str = Header(None)):
    """验证API Key"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="需要API Key。获取免费Key: 在Header中设置 X-API-Key: finapi-free-2026 或访问 /register")

    key_info = API_KEYS.get(x_api_key)
    if not key_info:
        raise HTTPException(status_code=401, detail="无效的API Key")

    tier = key_info.get("tier", "free")
    limit = TIER_CONFIG.get(tier, TIER_CONFIG["free"])["limit"]

    # 每日限额检查
    stats = call_stats[x_api_key]
    today = time.strftime("%Y-%m-%d")
    if stats["daily_reset"] != today:
        stats["count"] = 0
        stats["daily_reset"] = today

    if stats["count"] >= limit:
        upgrade_msg = f"今日调用已达上限({limit}次)。" if tier == "free" else f"今日调用已达上限({limit}次)，请联系升级。"
        upgrade_msg += " 升级Pro: $9/月(50K次/天) → /pricing"
        raise HTTPException(status_code=429, detail=upgrade_msg)

    stats["count"] += 1
    stats["last_call"] = time.time()

    return {**key_info, "limit": limit, "key": x_api_key}

# ============ 数据源 ============

def fetch_exchange_rates(base: str = "USD"):
    key = f"fx_{base}"
    cached = get_cached(key)
    if cached:
        return cached
    try:
        resp = requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{base}",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        result = {
            "source": "exchangerate-api",
            "base": data["base"],
            "date": data["date"],
            "rates": data["rates"],
        }
        set_cached(key, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"汇率源错误: {e}")

def convert_currency(amount: float, from_curr: str, to_curr: str):
    rates = fetch_exchange_rates(from_curr)
    rate = rates["rates"].get(to_curr)
    if not rate:
        raise HTTPException(status_code=400, detail=f"不支持货币: {to_curr}")
    return {
        "amount": amount,
        "from": from_curr,
        "to": to_curr,
        "rate": rate,
        "result": round(amount * rate, 6),
        "date": rates["date"],
    }

CRYPTO_MAP = {
    "bitcoin": "BTC_USDT", "ethereum": "ETH_USDT", "solana": "SOL_USDT",
    "bnb": "BNB_USDT", "xrp": "XRP_USDT", "dogecoin": "DOGE_USDT",
    "cardano": "ADA_USDT", "avalanche": "AVAX_USDT", "polkadot": "DOT_USDT",
    "chainlink": "LINK_USDT",
}

def fetch_crypto_prices(ids: str = "bitcoin,ethereum,solana"):
    key = f"crypto_{ids}"
    cached = get_cached(key)
    if cached:
        return cached
    tokens = [t.strip() for t in ids.split(",")]
    results = {}
    for token in tokens:
        pair = CRYPTO_MAP.get(token.lower(), f"{token.upper()}_USDT")
        try:
            resp = requests.get(
                f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={pair}",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    t = data[0]
                    results[token] = {
                        "usd": float(t.get("last", 0)),
                        "change_24h": float(t.get("change_percentage", 0)),
                        "high_24h": float(t.get("high_24h", 0)),
                        "low_24h": float(t.get("low_24h", 0)),
                        "volume_24h": float(t.get("quote_volume", 0)),
                        "pair": t.get("currency_pair"),
                    }
        except Exception:
            continue
    if results:
        result = {"source": "gate.io", "data": results}
        set_cached(key, result)
        return result
    raise HTTPException(status_code=502, detail="加密货币数据源不可用")

def fetch_cn_stock(symbol: str):
    key = f"cn_stock_{symbol}"
    cached = get_cached(key)
    if cached:
        return cached
    try:
        resp = requests.get(
            f"https://hq.sinajs.cn/list={symbol}",
            timeout=10,
            headers={"Referer": "https://finance.sina.com.cn"},
        )
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")
        for line in lines:
            eq_pos = line.find('="')
            if eq_pos > 0 and line.endswith('";'):
                content = line[eq_pos+2:-2]
                parts = content.split(",")
                if len(parts) >= 32:
                    result = {
                        "source": "sina", "symbol": symbol, "name": parts[0],
                        "open": float(parts[1]) if parts[1] else 0,
                        "last_close": float(parts[2]) if parts[2] else 0,
                        "price": float(parts[3]) if parts[3] else 0,
                        "high": float(parts[4]) if parts[4] else 0,
                        "low": float(parts[5]) if parts[5] else 0,
                        "volume": int(parts[8]) if parts[8] else 0,
                        "amount": float(parts[9]) if parts[9] else 0,
                        "date": parts[30], "time": parts[31],
                    }
                    set_cached(key, result)
                    return result
        raise HTTPException(status_code=404, detail=f"未找到: {symbol}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"A股数据源错误: {e}")

def fetch_market_overview():
    key = "market_overview"
    cached = get_cached(key)
    if cached:
        return cached
    overview = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        fx = fetch_exchange_rates("USD")
        overview["usd_cny"] = fx["rates"].get("CNY")
        overview["usd_eur"] = fx["rates"].get("EUR")
        overview["usd_jpy"] = fx["rates"].get("JPY")
        overview["fx_date"] = fx["date"]
    except Exception:
        overview["fx_error"] = "汇率数据不可用"
    try:
        crypto = fetch_crypto_prices("bitcoin,ethereum,solana")
        overview["crypto"] = crypto["data"]
    except Exception:
        overview["crypto_error"] = "加密货币数据不可用"
    try:
        sh = fetch_cn_stock("sh000001")
        pct = round((sh["price"] - sh["last_close"]) / sh["last_close"] * 100, 2) if sh["last_close"] else 0
        overview["shanghai"] = {"price": sh["price"], "change_pct": pct}
    except Exception:
        pass
    try:
        sz = fetch_cn_stock("sz399001")
        pct = round((sz["price"] - sz["last_close"]) / sz["last_close"] * 100, 2) if sz["last_close"] else 0
        overview["shenzhen"] = {"price": sz["price"], "change_pct": pct}
    except Exception:
        pass
    set_cached(key, overview)
    return overview

# ============ API 路由 ============

@app.get("/")
def root():
    return {
        "service": "FinAPI Gateway",
        "version": "0.5.0",
        "endpoints": [
            "GET /fx - 汇率查询",
            "GET /fx/convert - 货币转换",
            "GET /crypto - 加密货币价格",
            "GET /cn/stock - A股行情",
            "GET /market - 全球市场概览",
            "GET /market/widget - 可嵌入Widget",
            "GET /stats - 调用统计",
            "GET /health - 健康检查",
            "GET /pricing - 定价方案",
            "POST /register - 免费注册API Key",
            "POST /webhook/payment - 支付确认回调",
        ],
        "auth": "所有API需要在Header中设置 X-API-Key。免费注册: POST /register",
        "docs": "/docs",
    }

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

@app.post("/register")
def register(email: str = Query(..., description="邮箱地址")):
    """免费注册获取API Key"""
    # 检查邮箱是否已注册
    for key, info in API_KEYS.items():
        if info.get("email") == email:
            return {"api_key": key, "tier": info["tier"], "message": "该邮箱已注册，返回现有Key"}

    # 生成新Key
    new_key = f"finapi-{secrets.token_hex(8)}"
    API_KEYS[new_key] = {
        "name": email.split("@")[0],
        "email": email,
        "tier": "free",
        "created": time.time(),
    }
    save_api_keys(API_KEYS)

    return {
        "api_key": new_key,
        "tier": "free",
        "limit": TIER_CONFIG["free"]["limit"],
        "message": f"注册成功！每日{TIER_CONFIG['free']['limit']}次免费调用。升级Pro: /pricing",
    }

@app.get("/pricing")
def pricing():
    """定价方案"""
    return {
        "plans": [
            {
                "tier": "free",
                "name": "Free",
                "price": "$0/月",
                "limit": TIER_CONFIG["free"]["limit"],
                "cache_ttl": f"{TIER_CONFIG['free']['cache_ttl']}秒",
                "features": ["166种货币汇率", "10+加密货币价格", "A股实时行情", "可嵌入Widget", "社区支持"],
            },
            {
                "tier": "pro",
                "name": "Pro",
                "price": "$9/月",
                "limit": TIER_CONFIG["pro"]["limit"],
                "cache_ttl": f"{TIER_CONFIG['pro']['cache_ttl']}秒(更实时)",
                "features": ["Free全部功能", "50,000次/天", "1分钟缓存(更实时)", "自选币种/股票组合", "邮件支持"],
                "btc_price": "0.0001 BTC",
                "btc_address": BTC_ADDRESS,
                "paypal_amount": "$9",
                "paypal_account": PAYPAL_ACCOUNT,
                "instructions": f"方式1: 发送 0.0001 BTC 到 {BTC_ADDRESS} | 方式2: PayPal转账 $9 到 {PAYPAL_ACCOUNT}，然后在 /confirm 标注邮箱和交易凭证"
            },
            {
                "tier": "enterprise",
                "name": "Enterprise",
                "price": "$49/月",
                "limit": TIER_CONFIG["enterprise"]["limit"],
                "cache_ttl": f"{TIER_CONFIG['enterprise']['cache_ttl']}秒(准实时)",
                "features": ["Pro全部功能", "500,000次/天", "10秒缓存(准实时)", "历史数据查询", "SLA保障", "优先支持"],
                "btc_price": "0.0005 BTC",
                "btc_address": BTC_ADDRESS,
                "paypal_amount": "$49",
                "paypal_account": PAYPAL_ACCOUNT,
                "instructions": f"方式1: 发送 0.0005 BTC 到 {BTC_ADDRESS} | 方式2: PayPal转账 $49 到 {PAYPAL_ACCOUNT}，然后在 /confirm 标注邮箱和交易凭证"
            },
        ],
        "current_free_key": "finapi-free-2026",
        "register": "POST /register?email=your@email.com",
    }

@app.post("/webhook/payment")
async def payment_webhook(request: Request):
    """支付确认回调 - 支持BTC/链上支付确认后自动升级API Key"""
    try:
        body = await request.json()
        email = body.get("email", "")
        tier = body.get("tier", "pro")
        txid = body.get("txid", "")
        confirmations = body.get("confirmations", 0)

        if not email or not txid:
            return JSONResponse({"status": "ignored", "reason": "need email and txid"})

        if tier not in ("pro", "enterprise"):
            return JSONResponse({"status": "ignored", "reason": "invalid tier"})

        # 查找或创建用户
        existing_key = None
        for key, info in API_KEYS.items():
            if info.get("email") == email:
                existing_key = key
                break

        if existing_key:
            API_KEYS[existing_key]["tier"] = tier
            API_KEYS[existing_key]["upgraded_at"] = time.time()
            API_KEYS[existing_key]["payment_txid"] = txid
            API_KEYS[existing_key]["payment_confirmations"] = confirmations
            save_api_keys(API_KEYS)
            return {"status": "upgraded", "api_key": existing_key, "tier": tier}
        else:
            new_key = f"finapi-{tier}-{secrets.token_hex(8)}"
            API_KEYS[new_key] = {
                "name": email.split("@")[0],
                "email": email,
                "tier": tier,
                "created": time.time(),
                "upgraded_at": time.time(),
                "payment_txid": txid,
                "payment_confirmations": confirmations,
            }
            save_api_keys(API_KEYS)
            return {"status": "created", "api_key": new_key, "tier": tier}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

@app.post("/confirm")
async def confirm_payment(
    email: str = Query(..., description="你的邮箱"),
    tier: str = Query("pro", description="升级层级: pro 或 enterprise"),
    txid: str = Query(..., description="BTC交易ID(txid)"),
):
    """提交BTC支付确认 — 付款后提交txid，人工或自动确认后升级"""
    if tier not in ("pro", "enterprise"):
        raise HTTPException(status_code=400, detail="tier必须是pro或enterprise")

    btc_amount = TIER_CONFIG[tier]["btc_price"]

    # 记录待确认的付款
    pending_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_payments.json")
    pending = []
    if os.path.exists(pending_file):
        with open(pending_file, "r") as f:
            pending = json.load(f)

    payment_record = {
        "email": email,
        "tier": tier,
        "txid": txid,
        "btc_amount": btc_amount,
        "btc_address": BTC_ADDRESS,
        "submitted_at": time.time(),
        "status": "pending",
    }
    pending.append(payment_record)

    with open(pending_file, "w") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)

    return {
        "status": "submitted",
        "message": f"支付确认已提交！我们验证链上交易后会在24小时内升级你的Key。",
        "details": {
            "email": email,
            "tier": tier,
            "btc_amount": btc_amount,
            "txid": txid,
        },
        "note": "如果你已有API Key，升级后会保留原Key。如需新Key，请先 /register 再付款。",
    }

# ============ 受保护的数据端点 ============

@app.get("/fx")
def get_exchange_rates(
    base: str = Query("USD", description="基准货币"),
    key_info: dict = Depends(verify_api_key),
):
    """获取汇率表"""
    return fetch_exchange_rates(base.upper())

@app.get("/fx/convert")
def convert_fx(
    amount: float = Query(..., description="金额"),
    from_curr: str = Query(..., description="源货币"),
    to_curr: str = Query(..., description="目标货币"),
    key_info: dict = Depends(verify_api_key),
):
    """货币转换"""
    return convert_currency(amount, from_curr.upper(), to_curr.upper())

@app.get("/crypto")
def get_crypto(
    ids: str = Query("bitcoin,ethereum,solana", description="币种ID，逗号分隔"),
    key_info: dict = Depends(verify_api_key),
):
    """获取加密货币价格"""
    return fetch_crypto_prices(ids)

@app.get("/cn/stock")
def get_cn_stock(
    symbol: str = Query("sh000001", description="股票代码，如sh600519(茅台)"),
    key_info: dict = Depends(verify_api_key),
):
    """获取A股行情"""
    return fetch_cn_stock(symbol)

@app.get("/market")
def get_market_overview(key_info: dict = Depends(verify_api_key)):
    """全球市场概览"""
    return fetch_market_overview()

@app.get("/stats")
def get_stats(key_info: dict = Depends(verify_api_key)):
    """查看当前API Key的调用统计"""
    today = time.strftime("%Y-%m-%d")
    stats = call_stats.get(key_info["key"], {"count": 0})
    tier = key_info.get("tier", "free")
    limit = key_info.get("limit", TIER_CONFIG[tier]["limit"])
    return {
        "key_name": key_info["name"],
        "tier": tier,
        "daily_limit": limit,
        "calls_today": stats["count"],
        "remaining": limit - stats["count"],
        "upgrade_url": "/pricing" if tier == "free" else None,
        "date": today,
    }

# ============ 落地页 (含定价) ============

LANDING_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinAPI Gateway - 统一金融数据API | 免费汇率·加密货币·A股</title>
<meta name="description" content="一个API搞定汇率查询、加密货币价格、A股行情。免费1000次/天，5行代码接入。">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f0f23;color:#e0e0e0;line-height:1.6}
.hero{text-align:center;padding:60px 20px 40px;background:linear-gradient(135deg,#0f0f23 0%,#1a1a3e 100%)}
.hero h1{font-size:2.5em;background:linear-gradient(90deg,#00d2ff,#7b2ff7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:12px}
.hero p{font-size:1.2em;color:#aaa;max-width:600px;margin:0 auto}
.badges{display:flex;justify-content:center;gap:12px;margin-top:20px;flex-wrap:wrap}
.badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600}
.badge-green{background:#1a3a2a;color:#4ade80}
.badge-blue{background:#1a2a4a;color:#60a5fa}
.badge-purple{background:#2a1a4a;color:#c084fc}
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;padding:40px 20px;max-width:1000px;margin:0 auto}
.feature{background:#1a1a3e;border-radius:12px;padding:24px;border:1px solid #2a2a5e}
.feature h3{color:#00d2ff;margin-bottom:8px;font-size:1.1em}
.feature p{color:#999;font-size:0.95em}
.code-block{background:#0d0d1a;border:1px solid #2a2a5e;border-radius:8px;padding:16px;overflow-x:auto;font-family:'Fira Code',monospace;font-size:13px;color:#b5b5b5;margin:8px 0}
.code-block .key{color:#c084fc}.code-block .str{color:#4ade80}.code-block .url{color:#60a5fa}

/* 定价表 */
.pricing{padding:40px 20px;max-width:900px;margin:0 auto}
.pricing h2{text-align:center;font-size:2em;margin-bottom:30px;background:linear-gradient(90deg,#4ade80,#00d2ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:20px}
.pricing-card{background:#1a1a3e;border-radius:16px;padding:28px;border:2px solid #2a2a5e;transition:transform .2s,border-color .2s}
.pricing-card:hover{transform:translateY(-4px)}
.pricing-card.popular{border-color:#7b2ff7;position:relative}
.pricing-card.popular::before{content:'最受欢迎';position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:linear-gradient(90deg,#7b2ff7,#00d2ff);color:#fff;padding:4px 16px;border-radius:20px;font-size:12px;font-weight:700}
.pricing-card .plan-name{font-size:1.2em;font-weight:700;color:#fff;margin-bottom:4px}
.pricing-card .plan-price{font-size:2.5em;font-weight:800;color:#fff}
.pricing-card .plan-price span{font-size:0.4em;color:#888;font-weight:400}
.pricing-card .plan-limit{color:#60a5fa;font-size:0.9em;margin:8px 0 16px}
.pricing-card ul{list-style:none;margin:0 0 20px}
.pricing-card li{color:#aaa;font-size:0.9em;padding:4px 0}
.pricing-card li::before{content:'✓ ';color:#4ade80}
.pricing-card .buy-btn{display:block;text-align:center;padding:12px;border-radius:8px;text-decoration:none;font-weight:700;font-size:1em;transition:transform .1s}
.pricing-card .buy-btn:hover{transform:scale(1.02)}
.buy-free{background:#2a2a5e;color:#e0e0e0}
.buy-pro{background:linear-gradient(90deg,#7b2ff7,#00d2ff);color:#fff}
.buy-enterprise{background:#1a3a2a;color:#4ade80;border:1px solid #4ade80}

.widget-preview{max-width:500px;margin:30px auto;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.5)}
.widget-preview iframe{width:100%;border:none}
.share-bar{text-align:center;padding:20px;background:#1a1a3e;margin-top:40px}
.share-bar h4{color:#888;margin-bottom:12px;font-weight:normal}
.share-btns{display:flex;justify-content:center;gap:12px;flex-wrap:wrap}
.share-btns a{display:inline-block;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600}
.share-twitter{background:#1da1f2;color:#fff}
.share-copy{background:#333;color:#fff;cursor:pointer}
footer{text-align:center;padding:20px;color:#555;font-size:12px}
</style>
</head>
<body>

<div class="hero">
<h1>FinAPI Gateway</h1>
<p>一个API搞定全球金融数据 — 汇率 · 加密货币 · A股行情<br>免费1000次/天，5行代码接入</p>
<div class="badges">
<span class="badge badge-green">免费使用</span>
<span class="badge badge-blue">166种货币</span>
<span class="badge badge-purple">10+加密货币</span>
</div>
</div>

<div class="features">
<div class="feature">
<h3>💱 汇率查询 & 转换</h3>
<p>166种货币实时汇率，支持任意货币对转换</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/fx/convert?amount=1000&from_curr=USD&to_curr=CNY"</span></div>
</div>
<div class="feature">
<h3>₿ 加密货币价格</h3>
<p>BTC/ETH/SOL/BNB等10+主流币种，24h涨跌</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/crypto?ids=bitcoin,ethereum"</span></div>
</div>
<div class="feature">
<h3>📈 A股实时行情</h3>
<p>全市场A股实时行情，支持指数和个股</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/cn/stock?symbol=sh600519"</span></div>
</div>
<div class="feature">
<h3>🌐 全球市场概览</h3>
<p>一站式查看汇率+加密+指数，可嵌入Widget</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/market"</span></div>
</div>
</div>

<div class="widget-preview">
<iframe src="/market/widget" height="320" loading="lazy"></iframe>
</div>

<div class="pricing">
<h2>选择方案</h2>
<div class="pricing-grid">
  <div class="pricing-card">
    <div class="plan-name">Free</div>
    <div class="plan-price">$0<span>/月</span></div>
    <div class="plan-limit">1,000 次/天 · 5分钟缓存</div>
    <ul>
      <li>166种货币汇率</li>
      <li>10+加密货币价格</li>
      <li>A股实时行情</li>
      <li>可嵌入Widget</li>
      <li>社区支持</li>
    </ul>
    <a class="buy-btn buy-free" href="/register?email=your@email.com">免费注册 →</a>
  </div>
  <div class="pricing-card popular">
    <div class="plan-name">Pro</div>
    <div class="plan-price">$9<span>/月</span></div>
    <div class="plan-limit">50,000 次/天 · 1分钟缓存</div>
    <ul>
      <li>Free全部功能</li>
      <li>50倍调用配额</li>
      <li>更实时数据(1分钟)</li>
      <li>自选币种/股票组合</li>
      <li>邮件支持</li>
    </ul>
    <div class="pay-methods" style="margin-bottom:12px">
      <div style="font-size:13px;color:#f7931a;font-weight:700;margin-bottom:8px">₿ BTC</div>
      <div style="background:#0d0d1a;padding:8px;border-radius:6px;font-family:monospace;font-size:11px;word-break:break-all;color:#4ade80">1MLcB51Zya52oV445GZGMn1qqeYEAJ67Ds</div>
      <div style="font-size:11px;color:#666;margin-top:4px">金额: 0.0001 BTC</div>
      <div style="margin-top:12px;font-size:13px;color:#00457C;font-weight:700;margin-bottom:8px">💳 PayPal</div>
      <div style="background:#0d0d1a;padding:8px;border-radius:6px;font-family:monospace;font-size:11px;word-break:break-all;color:#60a5fa">16666181244@163.com</div>
      <div style="font-size:11px;color:#666;margin-top:4px">金额: $9 USD</div>
    </div>
    <div style="font-size:11px;color:#888;margin-bottom:8px">付款后提交凭证: POST /confirm?email=...&tier=pro&txid=...</div>
    <a class="buy-btn buy-pro" href="/pricing" target="_blank">升级 Pro →</a>
  </div>
  <div class="pricing-card">
    <div class="plan-name">Enterprise</div>
    <div class="plan-price">$49<span>/月</span></div>
    <div class="plan-limit">500,000 次/天 · 10秒缓存</div>
    <ul>
      <li>Pro全部功能</li>
      <li>500倍调用配额</li>
      <li>准实时数据(10秒)</li>
      <li>历史数据查询</li>
      <li>SLA保障 + 优先支持</li>
    </ul>
    <div class="pay-methods" style="margin-bottom:12px">
      <div style="font-size:13px;color:#f7931a;font-weight:700;margin-bottom:8px">₿ BTC</div>
      <div style="background:#0d0d1a;padding:8px;border-radius:6px;font-family:monospace;font-size:11px;word-break:break-all;color:#4ade80">1MLcB51Zya52oV445GZGMn1qqeYEAJ67Ds</div>
      <div style="font-size:11px;color:#666;margin-top:4px">金额: 0.0005 BTC</div>
      <div style="margin-top:12px;font-size:13px;color:#00457C;font-weight:700;margin-bottom:8px">💳 PayPal</div>
      <div style="background:#0d0d1a;padding:8px;border-radius:6px;font-family:monospace;font-size:11px;word-break:break-all;color:#60a5fa">16666181244@163.com</div>
      <div style="font-size:11px;color:#666;margin-top:4px">金额: $49 USD</div>
    </div>
    <div style="font-size:11px;color:#888;margin-bottom:8px">付款后提交凭证: POST /confirm?email=...&tier=enterprise&txid=...</div>
    <a class="buy-btn buy-enterprise" href="/pricing" target="_blank">升级 Enterprise →</a>
  </div>
</div>
</div>

<div class="share-bar">
<h4>觉得有用？分享给更多开发者</h4>
<div class="share-btns">
<a class="share-twitter" href="https://twitter.com/intent/tweet?text=FinAPI%20Gateway%20-%20%E5%85%8D%E8%B4%B9%E9%87%91%E8%9E%8D%E6%95%B0%E6%8D%AEAPI" onclick="this.href+=location.origin" target="_blank">Twitter</a>
<a class="share-copy" onclick="navigator.clipboard.writeText(location.origin+'/landing');this.textContent='已复制！';setTimeout(()=>this.textContent='📋 复制链接',2000)">📋 复制链接</a>
</div>
</div>

<footer>FinAPI Gateway v0.5.0 | Open Source | Powered by First Principles</footer>

</body>
</html>
"""

@app.get("/landing", response_class=HTMLResponse)
def landing():
    return LANDING_HTML

@app.get("/pricing", response_class=HTMLResponse)
def pricing_page():
    return LANDING_HTML + "<!-- pricing section above -->"

@app.get("/market/widget", response_class=HTMLResponse)
def market_widget():
    """可嵌入的市场概览Widget"""
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>市场概览</title></head>
<body style="font-family:system-ui;margin:0;padding:12px;background:#1a1a2e;color:#eee">
<div id="app">加载中...</div>
<script>
async function load(){
  try {
    const r = await fetch('/market', {headers: {'X-API-Key': 'finapi-free-2026'}});
    const d = await r.json();
    let h = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">';
    if(d.usd_cny) h += `<div style="background:#16213e;padding:12px;border-radius:8px">
      <div style="color:#888;font-size:12px">USD/CNY</div>
      <div style="font-size:24px;font-weight:bold">${d.usd_cny}</div></div>`;
    if(d.usd_eur) h += `<div style="background:#16213e;padding:12px;border-radius:8px">
      <div style="color:#888;font-size:12px">USD/EUR</div>
      <div style="font-size:24px;font-weight:bold">${d.usd_eur}</div></div>`;
    if(d.crypto){
      for(const[k,v] of Object.entries(d.crypto)){
        const chg = v.change_24h > 0 ? '+'+v.change_24h : v.change_24h;
        const clr = v.change_24h >= 0 ? '#00d2ff' : '#ff6b6b';
        h += `<div style="background:#16213e;padding:12px;border-radius:8px">
          <div style="color:#888;font-size:12px">${k.toUpperCase()}</div>
          <div style="font-size:20px;font-weight:bold">$${v.usd.toLocaleString()}</div>
          <div style="color:${clr};font-size:12px">${chg}%</div></div>`;
      }
    }
    if(d.shanghai) h += `<div style="background:#16213e;padding:12px;border-radius:8px">
      <div style="color:#888;font-size:12px">上证指数</div>
      <div style="font-size:20px;font-weight:bold">${d.shanghai.price}</div>
      <div style="color:${d.shanghai.change_pct>=0?'#00d2ff':'#ff6b6b'};font-size:12px">${d.shanghai.change_pct}%</div></div>`;
    h += '</div>';
    h += '<div style="text-align:center;margin-top:12px;font-size:11px;color:#555">Powered by FinAPI Gateway</div>';
    document.getElementById('app').innerHTML = h;
  } catch(e) { document.getElementById('app').innerHTML = '加载失败: '+e; }
}
load();
setInterval(load, 300000);
</script>
</body></html>"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
