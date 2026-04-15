# FinAPI Gateway - 免费统一金融数据API

## 一句话
一个API获取汇率、加密货币、A股行情，免费1,000次/天。

## 快速开始（30秒）

```bash
# 汇率转换：1000美元 = 多少人民币？
curl -H "X-API-Key: finapi-free-2026" \
     "https://8000-e4bee83e30864e8487d8959eb9b1bd97.e2b.bj9.sandbox.cloudstudio.club/fx/convert?amount=1000&from_curr=USD&to_curr=CNY"

# 加密货币价格
curl -H "X-API-Key: finapi-free-2026" \
     "https://8000-e4bee83e30864e8487d8959eb9b1bd97.e2b.bj9.sandbox.cloudstudio.club/crypto?ids=bitcoin,ethereum,solana"

# A股行情
curl -H "X-API-Key: finapi-free-2026" \
     "https://8000-e4bee83e30864e8487d8959eb9b1bd97.e2b.bj9.sandbox.cloudstudio.club/cn/stock?symbol=sh600519"

# 全球市场概览（一站式）
curl -H "X-API-Key: finapi-free-2026" \
     "https://8000-e4bee83e30864e8487d8959eb9b1bd97.e2b.bj9.sandbox.cloudstudio.club/market"
```

## 功能

| 端点 | 说明 | 数据源 |
|------|------|--------|
| GET /fx | 166种货币汇率 | exchangerate-api |
| GET /fx/convert | 实时货币转换 | exchangerate-api |
| GET /crypto | 10+加密货币价格 | Gate.io |
| GET /cn/stock | A股实时行情 | 新浪财经 |
| GET /market | 全球市场概览 | 聚合 |

## 免费

- API Key: `finapi-free-2026`
- 每日1,000次调用
- 5分钟缓存
- 无需注册

## 为什么用这个？

1. **一个API搞定三种数据** — 汇率+加密+A股，不用分别对接3个数据源
2. **国内可达** — Gate.io和新浪财经，不用翻墙
3. **统一格式** — 所有数据源输出一致的JSON结构
4. **5分钟缓存** — 减少延迟，降低上游压力
5. **零成本起步** — 免费Key每天1,000次

## API文档

https://8000-e4bee83e30864e8487d8959eb9b1bd97.e2b.bj9.sandbox.cloudstudio.club/docs

---

*如果觉得有用，欢迎反馈！想加什么数据源也可以提。*
