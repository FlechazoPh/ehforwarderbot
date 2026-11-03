## Agent skills

### 重新部署

要在其它机器上部署或排错，**先读 `docs/REDEPLOY.md`**。它包含容器组成、
`.env` 变量说明、构建与启动步骤、登录微信和验证方法。

密钥只存在于 `.env`（git-ignored）：先 `cp .env.example .env` 填写，
再运行 `python3 scripts/init_secrets.py` 渲染 `profiles/*/config.yaml`。

### Issue tracker

Issues and specs live as Markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

The repository uses a multi-context layout with a root `CONTEXT-MAP.md`, system-wide ADRs, and context-specific documentation. See `docs/agents/domain.md`.
