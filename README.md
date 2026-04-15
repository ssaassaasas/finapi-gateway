# FinAPI Gateway

统一金融数据API网关 — 聚合汇率、加密货币、A股等免费数据源，统一JSON输出。

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

服务启动后访问 `http://localhost:8000/docs` 查看API文档。

## API端点

| 端点 | 说明 | 示例 |
|------|------|------|
| `GET /fx` | 汇率查询 | `/fx?base=CNY` |
| `GET /fx/convert` | 货币转换 | `/fx/convert?amount=100&from_curr=USD&to_curr=CNY` |
| `GET /crypto` | 加密货币价格 | `/crypto?ids=bitcoin,ethereum` |
| `GET /cn/stock` | A股行情 | `/cn/stock?symbol=sh600519` |
| `GET /market` | 全球市场概览 | `/market` |
| `GET /health` | 健康检查 | `/health` |

## 数据源

| 数据类型 | 来源 | 频率限制 |
|----------|------|----------|
| 汇率 | exchangerate-api.com | 免费1500次/月 |
| 加密货币 | CoinGecko / DexScreener | 免费30次/分钟 |
| A股 | 新浪财经 | 免费，实时 |

## 缓存

- 默认5分钟TTL
- 减少上游API调用
- 提高响应速度
