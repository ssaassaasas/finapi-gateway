# FinAPI Gateway

> Unified Financial Data API — FX rates, Crypto prices, China A-shares in one API

一个 API 获取汇率、加密货币、A 股行情，免费 1,000 次/天。

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Service starts at `http://localhost:8000`. API docs at `/docs`.

## API Endpoints

| Endpoint | Description | Example |
|----------|-------------|---------|
| `GET /fx` | 166 currency exchange rates | `/fx?base=CNY` |
| `GET /fx/convert` | Real-time currency conversion | `/fx/convert?amount=1000&from_curr=USD&to_curr=CNY` |
| `GET /crypto` | 10+ cryptocurrency prices | `/crypto?ids=bitcoin,ethereum,solana` |
| `GET /cn/stock` | China A-share market data | `/cn/stock?symbol=sh600519` |
| `GET /market` | Global market overview (all-in-one) | `/market` |
| `GET /market/widget` | Embeddable market widget | `/market/widget` |
| `GET /stats` | API usage statistics | `/stats` |
| `GET /health` | Health check | `/health` |

## Authentication

All API endpoints require an API Key in the `X-API-Key` header.

```bash
# Free API Key (1,000 calls/day)
curl -H "X-API-Key: finapi-free-2026" "http://localhost:8000/market"
```

## Data Sources

| Data | Source | Coverage |
|------|--------|----------|
| FX Rates | exchangerate-api.com | 166 currencies |
| Crypto | Gate.io | 10+ coins (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, DOT, LINK) |
| A-Shares | Sina Finance | Full market, real-time |

## Features

- **5-min cache** — Reduces latency and upstream API calls
- **CORS enabled** — Direct browser access from any origin
- **API Key auth** — Simple header-based authentication with daily limits
- **Embeddable widget** — Ready-to-use market overview via iframe
- **Swagger docs** — Auto-generated API documentation at `/docs`

## Try It

```bash
# Global market overview
curl -H "X-API-Key: finapi-free-2026" \
  "http://localhost:8000/market"

# Convert 1000 USD to CNY
curl -H "X-API-Key: finapi-free-2026" \
  "http://localhost:8000/fx/convert?amount=1000&from_curr=USD&to_curr=CNY"

# Get Bitcoin & Ethereum prices
curl -H "X-API-Key: finapi-free-2026" \
  "http://localhost:8000/crypto?ids=bitcoin,ethereum"

# Check Kweichow Moutai (茅台) stock price
curl -H "X-API-Key: finapi-free-2026" \
  "http://localhost:8000/cn/stock?symbol=sh600519"
```

## Embed Widget

Add a live market overview to any webpage:

```html
<iframe src="http://localhost:8000/market/widget" width="100%" height="320" frameborder="0"></iframe>
```

## Tech Stack

- **FastAPI** — High-performance async API framework
- **Uvicorn** — ASGI server
- **requests** — HTTP client for upstream APIs

## License

MIT
