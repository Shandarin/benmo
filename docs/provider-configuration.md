# Provider 采购与配置

供应商接入遵循三条边界：搜索结果只是候选线索；可公开证据必须重新抓取并冻结到 S3；任何密钥都不得进入源码、日志、任务输入或前端。

## 第一版建议顺序

1. 配置 OpenAI 作为当前 LLM provider。
2. 接入 SEC、FRED、BLS、BEA、EIA 等第一方数据；SEC 必须配置可联系的 `BENMO_SEC_USER_AGENT`。
3. 接入 Finnhub 与 Alpha Vantage，用于新闻候选、行情和日历发现。
4. 在覆盖率或授权需求出现后，再采购 Bigdata、RavenPack、Aiera、Quartr、Fiscal/S&P 等企业服务。

上线前应向供应商确认：生产并发与速率限制、历史回溯范围、原文/快照能否归档、引用能否公开展示、数据再分发权限、模型训练限制、审计日志保留和故障 SLA。

## 环境变量映射

| 类别 | 变量 | 说明 |
| --- | --- | --- |
| LLM | `OPENAI_API_KEY` | 当前唯一实现的 LLM provider；模型名使用 `BENMO_OPENAI_MODEL` |
| 新闻/行情 | `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY` | 第一版候选发现与便利数据层 |
| 官方经济数据 | `FRED_API_KEY`, `BLS_API_KEY`, `BEA_API_KEY`, `EIA_API_KEY` | 优先作为事实层 |
| SEC | `BENMO_SEC_USER_AGENT` | 不是密钥，但必须是可联系的产品/邮箱标识 |

生产密钥配置见 [deployment.md](deployment.md)。未启用的 provider 不应被 worker 选择。

## Secrets Manager

首次 `master` 发布会创建 `benmo-production/provider-credentials`。以后每次发布时，
GitHub Actions 使用仓库 Secrets 原子写入整个 JSON；不要在 AWS Console、命令行或源码中
维护另一份生产密钥。

Secret 至少保留这些字段，即使暂未使用也可保持 `replace-me`：

```json
{
  "OPENAI_API_KEY": "...",
  "FINNHUB_API_KEY": "...",
  "ALPHA_VANTAGE_API_KEY": "...",
  "FRED_API_KEY": "...",
  "BLS_API_KEY": "...",
  "EIA_API_KEY": "...",
  "BEA_API_KEY": "..."
}
```

生产 worker 固定运行 live provider mode。每次发布使用新的 commit-SHA task definition
滚动更新服务并读取最新 Secret 版本。

## 数据授权与证据冻结

- S3 key 使用 `sources/{source_id}/{retrieved_at}/raw.*`、`clean.txt`、`metadata.json`；数据库只保存 key、hash、content type 和抓取时间。
- 若条款不允许保存全文，只保存许可范围内的片段、hash 与可重取元数据，并把证据状态标记为受限。
- 新闻聚合商不自动升级为权威证据；关键边优先使用 SEC、公司披露或官方数据。
- Provider Web Search 给出的 URL 必须由 worker 重新访问，quote existence 和内容 hash 校验成功后才能绑定因果边。
