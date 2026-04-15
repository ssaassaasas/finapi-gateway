"""
FinAPI Gateway v0.4.0 - 统一金融数据API网关
聚合多个免费数据源，统一输出格式
+ Gate.io加密货币源
+ API Key认证
+ 调用统计
+ 可嵌入市场概览Widget
+ 分享式Landing Page
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
    version="0.4.0",
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
        "version": "0.4.0",
        "endpoints": [
            "GET /fx - 汇率查询",
            "GET /fx/convert - 货币转换",
            "GET /crypto - 加密货币价格",
            "GET /cn/stock - A股行情",
            "GET /market - 全球市场概览",
            "GET /market/widget - 可嵌入Widget",
            "GET /stats - 调用统计",
            "GET /health - 健康检查",
            "GET /landing - 产品落地页",
        ],
        "auth": "所有API需要在Header中设置 X-API-Key。免费Key: finapi-free-2026",
        "docs": "/docs",
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
.cta{text-align:center;padding:40px 20px}
.cta-btn{display:inline-block;background:linear-gradient(90deg,#00d2ff,#7b2ff7);color:#fff;padding:14px 32px;border-radius:8px;font-size:1.1em;text-decoration:none;font-weight:600;transition:transform .2s}
.cta-btn:hover{transform:scale(1.05)}
.share-bar{text-align:center;padding:20px;background:#1a1a3e;margin-top:40px}
.share-bar h4{color:#888;margin-bottom:12px;font-weight:normal}
.share-btns{display:flex;justify-content:center;gap:12px;flex-wrap:wrap}
.share-btns a{display:inline-block;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600}
.share-twitter{background:#1da1f2;color:#fff}
.share-weibo{background:#e6162d;color:#fff}
.share-copy{background:#333;color:#fff;cursor:pointer}
.widget-preview{max-width:500px;margin:30px auto;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.5)}
.widget-preview iframe{width:100%;border:none}
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
<p>166种货币实时汇率，支持任意货币对转换。数据源: exchangerate-api</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/fx/convert?amount=1000&from_curr=USD&to_curr=CNY"</span></div>
</div>
<div class="feature">
<h3>₿ 加密货币价格</h3>
<p>BTC/ETH/SOL/BNB等10+主流币种，24h涨跌幅、成交量。数据源: Gate.io</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/crypto?ids=bitcoin,ethereum"</span></div>
</div>
<div class="feature">
<h3>📈 A股实时行情</h3>
<p>全市场A股实时行情，支持指数和个股查询。数据源: 新浪财经</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/cn/stock?symbol=sh600519"</span></div>
</div>
<div class="feature">
<h3>🌐 全球市场概览</h3>
<p>一站式查看汇率+加密+指数，可嵌入Widget。适合金融仪表盘和App</p>
<div class="code-block">curl -H <span class="str">"X-API-Key: finapi-free-2026"</span> <span class="url">"/market"</span></div>
</div>
</div>

<div class="widget-preview">
<iframe src="/market/widget" height="320" loading="lazy"></iframe>
</div>

<div class="cta">
<p style="color:#aaa;margin-bottom:16px">复制免费API Key，5行代码开始接入</p>
<div class="code-block" style="text-align:center;font-size:18px;max-width:400px;margin:0 auto">
<span class="key">X-API-Key:</span> <span class="str">finapi-free-2026</span>
</div>
<br>
<a class="cta-btn" href="/docs" target="_blank">查看完整API文档 →</a>
</div>

<div class="share-bar">
<h4>觉得有用？分享给更多开发者</h4>
<div class="share-btns">
<a class="share-twitter" href="https://twitter.com/intent/tweet?text=FinAPI%20Gateway%20-%20%E5%85%8D%E8%B4%B9%E9%87%91%E8%9E%8D%E6%95%B0%E6%8D%AEAPI%EF%BC%8C%E4%B8%80%E4%B8%AA%E6%8E%A5%E5%8F%A3%E6%90%9E%E5%AE%9A%E6%B1%87%E7%8E%87%2B%E5%8A%A0%E5%AF%86%E8%B4%A7%E5%B8%81%2BA%E8%82%A1&url=" onclick="this.href+=location.origin" target="_blank">Twitter</a>
<a class="share-copy" onclick="navigator.clipboard.writeText(location.origin+'/landing');this.textContent='已复制！';setTimeout(()=>this.textContent='📋 复制链接',2000)">📋 复制链接</a>
</div>
</div>

<footer>FinAPI Gateway v0.4.0 | 开源免费 | Powered by First Principles</footer>

</body>
</html>
"""

@app.get("/landing", response_class=HTMLResponse)
def landing():
    return LANDING_HTML

@app.get("/market/widget", response_class=HTMLResponse)
def market_widget():
    """可嵌入的市场概览Widget - 可直接用iframe嵌入任何网页"""
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
    // 汇率
    if(d.usd_cny) h += `<div style="background:#16213e;padding:12px;border-radius:8px">
      <div style="color:#888;font-size:12px">USD/CNY</div>
      <div style="font-size:24px;font-weight:bold">${d.usd_cny}</div></div>`;
    if(d.usd_eur) h += `<div style="background:#16213e;padding:12px;border-radius:8px">
      <div style="color:#888;font-size:12px">USD/EUR</div>
      <div style="font-size:24px;font-weight:bold">${d.usd_eur}</div></div>`;
    // 加密货币
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
    // 指数
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
