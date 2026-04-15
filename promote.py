"""FinAPI Gateway 推广文案生成"""
BASE_URL = "https://8000-e4bee83e30864e8487d8959eb9b1bd97.e2b.bj9.sandbox.cloudstudio.club"
API_KEY = "finapi-free-2026"

platforms = {
    "V2EX-分享创造": f"""免费金融数据API，一个接口搞定汇率+加密货币+A股

折腾了一圈金融数据API，发现国内开发者想要一个统一的接口挺难的——汇率要找exchangerate，加密货币要找CoinGecko（还经常被墙），A股要找新浪。于是写了个网关把它们聚合起来。

一个API Key，5个端点：
- /fx → 166种货币汇率
- /fx/convert → 实时货币转换
- /crypto → 10+加密货币（Gate.io源，国内可达）
- /cn/stock → A股实时行情
- /market → 全球市场概览

试一下：
```bash
curl -H "X-API-Key: {API_KEY}" "{BASE_URL}/market"
```

免费1,000次/天，5分钟缓存。API文档：{BASE_URL}/docs

有什么想加的数据源可以留言。""",

    "Reddit-r/algotrading": f"""FinAPI Gateway - Free unified financial data API (FX + Crypto + China A-shares)

One API for exchange rates (166 currencies), crypto prices (10+ coins via Gate.io), and China A-share market data.

```bash
curl -H "X-API-Key: {API_KEY}" "{BASE_URL}/market"
curl -H "X-API-Key: {API_KEY}" "{BASE_URL}/fx/convert?amount=1000&from_curr=USD&to_curr=CNY"
curl -H "X-API-Key: {API_KEY}" "{BASE_URL}/crypto?ids=bitcoin,ethereum,solana"
```

Free tier: 1,000 calls/day, 5-min cache.
Docs: {BASE_URL}/docs""",

    "知乎-想法": f"""做了一个免费金融数据API网关，聚合汇率(166种货币)+加密货币(BTC/ETH/SOL等)+A股实时行情，一个接口全搞定。

curl -H "X-API-Key: {API_KEY}" "{BASE_URL}/market"

免费1,000次/天，有API文档。开发者可以直接用，不用分别对接3个数据源。""",
}

for platform, content in platforms.items():
    print(f"\n{'='*60}")
    print(f"平台: {platform}")
    print(f"{'='*60}")
    print(content)
