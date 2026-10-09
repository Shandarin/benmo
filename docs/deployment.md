# AWS 部署指南

完成一次性配置后，push `master` 即可自动部署。部署区域固定为
**United States (N. Virginia) / `us-east-1`**。

## 1. 准备域名证书

1. 将 AWS Console 切换到 **United States (N. Virginia)**；
2. 在 AWS Certificate Manager 申请公共证书；
3. 填写公开域名，例如 `research.example.com`；
4. 按 ACM 提示完成 DNS 验证；
5. 等待证书状态变为 `Issued`；
6. 复制证书 ARN。

## 2. 准备 GitHub OIDC Role

可以复用 `ppt-copilot` 已使用的 AWS Deployment Role，不需要上传 CloudFormation 模板。

确认该 Role：

1. 信任当前 Benmo GitHub 仓库的 `master` 分支；
2. 可以承担 `cdk-hnb659fds-*` CDK bootstrap roles；
3. 可以创建和推送 `benmo-backend`、`benmo-worker`、`benmo-frontend` 三个 ECR 仓库；
4. 可以创建和更新 `benmo-production/provider-credentials` Secret；
5. 可以读取 ACM 和 Fargate quota；
6. 可以读取 VPC、子网和路由表，以验证 Fargate 公网出口；
7. 可以运行 ECS 数据库迁移任务并执行所需的 `iam:PassRole`。

复制该 Role 的 ARN。

## 3. 初始化 CDK

在 AWS CloudShell 中执行一次：

```bash
export AWS_REGION=us-east-1
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
npx --yes aws-cdk@2.1132.0 bootstrap "aws://$ACCOUNT_ID/$AWS_REGION"
```

## 4. 配置 GitHub

打开：

`Settings → Secrets and variables → Actions`

在 **Secrets** 中添加：

| 名称 | 填写内容 |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | 第二步获得的 AWS Role ARN |
| `OPENAI_API_KEY` | OpenAI API Key |

按需添加：

- `FINNHUB_API_KEY`
- `ALPHA_VANTAGE_API_KEY`
- `FRED_API_KEY`
- `BLS_API_KEY`
- `EIA_API_KEY`
- `BEA_API_KEY`

在 **Variables** 中添加：

| 名称 | 填写内容 |
| --- | --- |
| `ACM_CERTIFICATE_ARN` | 第一步获得的证书 ARN |
| `SEC_USER_AGENT` | 例如 `Benmo/0.1 ops@example.com` |
| `SITE_URL` | 例如 `https://research.example.com`，末尾不带 `/` |

`SITE_URL` 的域名必须包含在第一步申请的 ACM 证书中。

## 5. 触发部署

```bash
git push origin master
```

打开 GitHub **Actions**，等待 **CI and deploy** 全部完成。

部署工作流按以下顺序执行：

1. 运行后端、worker、前端和 CDK 检查；
2. 通过 GitHub OIDC 获取临时 AWS 凭证；
3. 检查 ACM 证书和 Fargate quota；
4. 创建或复用三个 ECR 仓库；
5. 使用完整 Git commit SHA 构建并推送不可变镜像；
6. 通过 CDK 更新 `BenmoPlatformStack`；
7. 验证两个公共子网均有 Internet Gateway 默认路由且至少有 8 个可用 IPv4；
8. 在公共子网运行一次性 API Task 执行 Alembic 数据库迁移；
9. 通过 ALB 检查 API 和 SSR 前端健康状态。

## 6. 生产网络和任务模型

生产 VPC 跨两个可用区，仅创建两类子网：

- **public**：ALB、API、SSR 前端和 worker Fargate Task；
- **database**：不包含公网路由的 RDS 隔离子网。

原 application 子网使用的两个 `/24` CIDR 在 CDK 中保留但不再创建子网，避免升级已有
生产栈时数据库子网 CIDR 前移并与待删除的旧子网冲突。

生产环境不创建 NAT Gateway。API、SSR 前端、数据库迁移和 worker Task 均设置
`assignPublicIp=ENABLED`，通过公共子网的 Internet Gateway 拉取 ECR 镜像、发送
CloudWatch 日志并访问获准的外部数据提供商。公网 IP 不构成入站授权：

- API 安全组只允许 ALB、SSR 前端和 worker 访问 8000；
- SSR 前端安全组只允许 ALB 访问 3000；
- worker 安全组没有公网入站规则；
- RDS 保持在隔离子网，只允许 API 和 worker 安全组访问 5432。

API 和 SSR 前端各保持一个常驻 Task，并分别按 CPU 自动扩展到最多 10 和 5 个。
ALB 的 idle timeout 为 120 秒，以容纳带心跳的 SSE 进度连接。

Research Worker 的正常路径由 API 在成功写入 SQS 后立即调用 ECS `RunTask`，使用
`consume --worker research --once` 处理一次接收批次后退出。Verification Step Functions
同样在写入验证队列后启动一次性 Verification Task。三个 worker ECS Service 的期望容量和
最小容量均为 0，仅作为 SQS 重试兜底：队列出现可见积压时扩容，清空后自动缩回 0。
Document Worker 当前通过该队列积压兜底按需启动。

RDS 始终使用私有地址；Fargate Task 是否拥有公网 IP 不会让数据库公开。数据库使用
PostgreSQL 16、`db.t4g.micro`、Single-AZ 和 20 GB GP3，存储最多自动扩展到 100 GB。
保留存储加密、删除保护、7 天自动备份和删除时快照；不启用 Performance Insights 与
增强监控。20 GB 只适用于首次创建，RDS 不支持部署后缩小已分配存储。

## 7. 配置域名并检查

部署成功后：

1. 打开 CloudFormation 的 `BenmoPlatformStack`；
2. 从 Outputs 复制 `ApiLoadBalancerDnsName`；
3. 将 `SITE_URL` 的域名指向该地址：
   - Route 53 使用 Alias；
   - 其他 DNS 服务使用 CNAME；
4. 等待 DNS 生效；
5. 访问以下地址：

```text
https://research.example.com/health/live
https://research.example.com/health/ready
https://research.example.com/healthz
```

三个接口均正常后，部署完成。

以后更新代码或 API Key，只需再次 push `master`。

## 8. 失败和回滚

- ECS API、SSR 前端和 worker Service 均启用 deployment circuit breaker 自动回滚；
- SQS 消息处理失败时保留消息并按 visibility timeout 重试，五次后进入对应 DLQ；
- API 直接启动一次性 Research Task 失败时，请求会记录为可重试的 enqueue failure；
  SQS 中已写入的消息仍可由最小容量为 0 的 Research Worker Service 拉起处理；
- CDK 栈启用 termination protection，ALB 和 RDS 启用删除保护；
- S3 制品桶、管理密钥、运行日志和 DLQ 使用保留策略，RDS 删除时创建快照；
- 数据库迁移或健康检查失败会使 GitHub Actions 部署失败，不创建本地或手工部署旁路。
