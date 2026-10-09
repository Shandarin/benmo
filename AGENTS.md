# Benmo repository instructions

## Deployment contract

- Production is deployed to AWS only through the single GitHub Actions workflow after a successful push
  to `master`. Do not add manual, local, fallback, or parallel deployment paths.
- The production AWS region is fixed to United States (N. Virginia), `us-east-1`. Keep ACM, CDK bootstrap,
  ECR, Secrets Manager, and the application stack in this region; do not add a region override.
- Use GitHub OIDC and an AWS IAM role. Never add long-lived AWS access keys to the repository or workflow.
- Reuse an externally managed GitHub OIDC deployment role through `AWS_DEPLOY_ROLE_ARN`, matching the
  `ppt-copilot` deployment pattern. Do not add or require a repository-managed bootstrap template upload.
- Frontend, API, and worker images must be published to ECR with immutable full-commit-SHA tags. CDK must
  consume explicit image URIs; do not restore implicit local CDK asset builds for production.
- Runtime provider credentials belong in GitHub Actions secrets and AWS Secrets Manager, never in source,
  CloudFormation parameters, logs, or committed `.env` files.
- User registration, login, Cognito, and account verification are currently out of scope. Administrative
  endpoints continue to use the generated API key.
- `docs/deployment.md` is the source of truth for production deployment and operations. Do not add local
  deployment instructions to it.
- Keep `docs/deployment.md` as a concise operator checklist. Document only actions the user must perform,
  required values they must configure, and checks they must make. Do not include automated implementation
  details, internal resource descriptions, or steps handled entirely by GitHub Actions, CDK, CloudFormation,
  ECS, or other managed services.

## Required documentation update

Any change to the architecture, CDK/CloudFormation resources, GitHub Actions deployment, deployment
parameters, secrets, environment variables, database migration procedure, networking, observability,
rollback behavior, or production operating procedure must update `docs/deployment.md` in the same change.

Before completing an infrastructure change, run at least:

```text
npm --prefix infra run check
npm --prefix infra run synth
```
