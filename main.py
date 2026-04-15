"""
FinAPI Gateway v0.2.0 - 统一金融数据API网关
聚合多个免费数据源，统一输出格式
+ Gate.io加密货币源
+ API Key认证
+ 调用统计
"""

from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import requests
import time
from collections import defaultdict

app = FastAPI(
    title="FinAPI Gateway",
    description="统一金融数据API网关 - 聚合汇率、股票、加密货币等免费数据源",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 缓存层 ============
cache = {}
CACHE_TTL = 300

def get_cached(key: str):
    if key in cache:
        data, ts = cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None

def set_cached(key: str, data):
    cache[key] = (data, time.time())

# ============ API Key认证 ============
# 最简方案：内存字典，不搞数据库
API_KEYS = {
    "demo": {"name": "演示用户", "tier": "free", "limit": 1000},  # 每日1000次
    "finapi-free-2026": {"name": "免费用户", "tier": "free", "limit": 1000},
    "finapi-pro-2026": {"name": "专业用户", "tier": "pro", "limit": 10000},
}

# 调用统计
call_stats = defaultdict(lambda: {"count": 0, "last_call": 0, "daily_reset": 0})

def verify_api_key(x_api_key: str = Header(None)):
    """验证API Key"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="需要API Key。获取免费Key: 在Header中设置 X-API-Key: finapi-free-2026")

    key_info = API_KEYS.get(x_api_key)
    if not key_info:
        raise HTTPException(status_code=401, detail="无效的API Key")

    # 每日限额检查
    stats = call_stats[x_api_key]
    today = time.strftime("%Y-%m-%d")
    if stats["daily_reset"] != today:
        stats["count"] = 0
        stats["daily_reset"] = today

    if stats["count"] >= key_info["limit"]:
        raise HTTPException(status_code=429, detail=f"今日调用已达上限({key_info['limit']}次)。升级请联系。")

    stats["count"] += 1
    stats["last_call"] = time.time()

    return key_info

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

# 加密货币 - 用Gate.io（国内可达）
CRYPTO_MAP = {
    "bitcoin": "BTC_USDT",
    "ethereum": "ETH_USDT",
    "solana": "SOL_USDT",
    "bnb": "BNB_USDT",
    "xrp": "XRP_USDT",
    "dogecoin": "DOGE_USDT",
    "cardano": "ADA_USDT",
    "avalanche": "AVAX_USDT",
    "polkadot": "DOT_USDT",
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
        pair = CRYPTO_MAP.get(token.lower())
        if not pair:
            # 尝试直接用token名构造
            pair = f"{token.upper()}_USDT"

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
                        "source": "sina",
                        "symbol": symbol,
                        "name": parts[0],
                        "open": float(parts[1]) if parts[1] else 0,
                        "last_close": float(parts[2]) if parts[2] else 0,
                        "price": float(parts[3]) if parts[3] else 0,
                        "high": float(parts[4]) if parts[4] else 0,
                        "low": float(parts[5]) if parts[5] else 0,
                        "volume": int(parts[8]) if parts[8] else 0,
                        "amount": float(parts[9]) if parts[9] else 0,
                        "date": parts[30],
                        "time": parts[31],
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
        "version": "0.2.0",
        "endpoints": [
            "GET /fx - 汇率查询",
            "GET /fx/convert - 货币转换",
            "GET /crypto - 加密货币价格",
            "GET /cn/stock - A股行情",
            "GET /market - 全球市场概览",
            "GET /stats - 调用统计",
            "GET /health - 健康检查",
        ],
        "auth": "所有API需要在Header中设置 X-API-Key。免费Key: finapi-free-2026",
    }

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

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
    """获取加密货币价格（支持: bitcoin, ethereum, solana, bnb, xrp, dogecoin, cardano, avalanche, polkadot, chainlink）"""
    return fetch_crypto_prices(ids)

@app.get("/cn/stock")
def get_cn_stock(
    symbol: str = Query("sh000001", description="股票代码，如sh600519(茅台)，sz000001(平安)"),
    key_info: dict = Depends(verify_api_key),
):
    """获取A股行情"""
    return fetch_cn_stock(symbol)

@app.get("/market")
def get_market_overview(key_info: dict = Depends(verify_api_key)):
    """全球市场概览 - 一站式查看汇率+加密+指数"""
    return fetch_market_overview()

@app.get("/stats")
def get_stats(key_info: dict = Depends(verify_api_key)):
    """查看当前API Key的调用统计"""
    today = time.strftime("%Y-%m-%d")
    return {
        "key_name": key_info["name"],
        "tier": key_info["tier"],
        "daily_limit": key_info["limit"],
        "calls_today": call_stats.get("finapi-free-2026", {}).get("count", 0) if key_info["tier"] == "free" else "unlimited",
        "date": today,
    }

# ============ 落地页 ============

@app.get("/landing", response_class=HTMLResponse)
def landing():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>FinAPI Gateway - 统一金融数据API</title></head>
    <body style="font-family:system-ui;max-width:720px;margin:40px auto;padding:0 20px;color:#333">
        <h1>FinAPI Gateway</h1>
        <p>统一金融数据API网关 — 一个接口获取汇率、加密货币、A股行情</p>

        <h2>快速开始</h2>
        <pre style="background:#f5f5f5;padding:16px;border-radius:8px;overflow-x:auto">
# 获取免费API Key
X-API-Key: finapi-free-2026

# 查询汇率
curl -H "X-API-Key: finapi-free-2026" \\
     "http://49.232.155.209:8000/fx?base=CNY"

# 货币转换
curl -H "X-API-Key: finapi-free-2026" \\
     "http://49.232.155.209:8000/fx/convert?amount=100&from_curr=USD&to_curr=CNY"

# 加密货币价格
curl -H "X-API-Key: finapi-free-2026" \\
     "http://49.232.155.209:8000/crypto?ids=bitcoin,ethereum,solana"

# A股行情
curl -H "X-API-Key: finapi-free-2026" \\
     "http://49.232.155.209:8000/cn/stock?symbol=sh600519"

# 全球市场概览
curl -H "X-API-Key: finapi-free-2026" \\
     "http://49.232.155.209:8000/market"
        </pre>

        <h2>API端点</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#f0f0f0"><th style="padding:8px;text-align:left">端点</th><th style="padding:8px;text-align:left">说明</th></tr>
            <tr><td style="padding:8px">GET /fx</td><td style="padding:8px">166种货币汇率</td></tr>
            <tr><td style="padding:8px">GET /fx/convert</td><td style="padding:8px">实时货币转换</td></tr>
            <tr><td style="padding:8px">GET /crypto</td><td style="padding:8px">10+加密货币价格(Gate.io)</td></tr>
            <tr><td style="padding:8px">GET /cn/stock</td><td style="padding:8px">A股实时行情(新浪)</td></tr>
            <tr><td style="padding:8px">GET /market</td><td style="padding:8px">全球市场概览(一站式)</td></tr>
        </table>

        <h2>免费额度</h2>
        <p>每日1,000次调用。5分钟数据缓存，减少延迟。</p>

        <h2>数据源</h2>
        <ul>
            <li>汇率: exchangerate-api.com (166种货币)</li>
            <li>加密货币: Gate.io (BTC/ETH/SOL/BNB等)</li>
            <li>A股: 新浪财经 (实时行情)</li>
        </ul>

        <p style="color:#999;margin-top:40px">FinAPI Gateway v0.2.0 | 由马斯克操作系统驱动</p>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
