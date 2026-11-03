# 重新部署指南（面向 AI agent）

本文件给自动化 agent 使用：在一台全新服务器上把本方案部署起来。人类读者也可参考。
**目标**：微信 ↔ Telegram 双向转发，含链接存档（Telegraph）、视频链接转视频消息、大文件（≤2GB）、
防盗链图片转存。

## 架构（谁依赖谁）

```
Telegram  ──MTProto──  telegram_bot_api(本地 Bot API, :8081)  ──socks/http──  proxy(mihomo)  ──VLESS──  境外
                                   │ 复用 /tmp(efb_tmp) 与 efb 交换大文件
efb(EhForwarderBot) ── network_mode: service:comwechat ── comwechat(wine 里的微信 + Hook :18888)
  └─ 中间件链：keyword_reply → message_merge → keyword_replace → map
                → voice_recog → search_msg → video_parser → telegraph
efb ──HTTP──> raw.githubusercontent.com   # telegraph 把防盗链图片转存到你的公开仓库
```

关键约束：
- `efb` 与 `comwechat` **共享网络命名空间**。重建 `comwechat` 会让微信掉线（需重新扫码）；
  改中间件/镜像时**只重建 efb**：`docker compose up -d --force-recreate --no-deps efb`。
- 本机直连 Telegram/境外视频站通常不通，**必须有 `proxy` 服务**（`compose.override.yaml`）。
- `flechazo.*`、`voice_recog`、`search_msg` 只在自建镜像里；用上游镜像须在 `config.yaml` 注释掉。

## 需要人类提供的秘密（agent 不要臆造）

写入 `.env`（见 `.env.example`）：

| 变量 | 来源 |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | https://my.telegram.org -> API development tools |
| `COMWECHAT_VNC_PASSWORD` | 自定义 |
| `blueset.telegram` 的 `token` / `admins` | @BotFather / @userinfobot（填进 profile 配置，非 .env） |
| `TELEGRAPH_IMAGE_REPO` + `TELEGRAPH_IMAGE_GITHUB_TOKEN` | 一个公开 GitHub 仓库 + 对它有 Contents:write 的 token |
| `PROXY_SUB_URL`（及必要时 `PROXY_SUB_RESOLVE` / `PROXY_SERVER_IP`） | 你的代理订阅 |

`TELEGRAPH_TOKEN` 可留空（首次运行自动建号并持久化到
`profiles/comwechat/flechazo.telegraph/telegraph_token`）。

## 部署步骤

```bash
# 1. 配置
cp .env.example .env && chmod 600 .env    # 按上表填写
for m in blueset.telegram flechazo.telegraph flechazo.video_parser; do
  f=profiles/comwechat/$m/config.yaml
  [ -f "$f" ] || cp "$f.example" "$f" 2>/dev/null || true
done
# 编辑 profiles/comwechat/blueset.telegram/config.yaml 填 token / admins

# 2. 代理（本机访问 Telegram/境外站受阻时必需）
python3 proxy/gen_config.py               # 读取 .env 的 PROXY_SUB_URL -> proxy/config.yaml
# 若订阅域名默认解析的 IP 不通：在 .env 设 PROXY_SUB_RESOLVE / PROXY_SERVER_IP 后重跑

# 3. 构建 + 启动
docker compose build
docker compose up -d

# 4. 扫码登录微信：VNC 连接 <host>:5905（密码 = COMWECHAT_VNC_PASSWORD）
# 5. Telegram 里对自己的 Bot 发 /extra 等完成绑定
```

> 目录内同时存在 `compose.yaml` 与旧的 `docker-compose.yaml`，`.env` 里已用 `COMPOSE_FILE`
> 指定加载 `compose.yaml:compose.override.yaml`，直接 `docker compose ...` 即可，别再加 `-f`。
> 若只有 `docker-compose`（v1）可用，把命令里的 `docker compose` 换成 `docker-compose`。

## 验证

```bash
docker compose ps                                   # efb / comwechat / telegram_bot_api / proxy 均 Up
docker compose logs --tail=40 efb | grep -i "All middlewares are initialized"
# 真机验证：微信里发 公众号链接 / B站链接(b23.tv) / 一段话里带网页链接，看 TG 是否出现
#   - 链接卡片 => 预览可“即时查看”(Telegraph)
#   - 视频链接 => 变成视频消息（大视频为一组相册）
#   - 文字链接 => 末尾追加 📰 https://telegra.ph/...
```

## 升级 / 调整

- 升级自研中间件：改 `Dockerfile` 顶部 `EFB_TELEGRAPH_MIDDLEWARE_REF` /
  `EFB_VIDEO_PARSER_MIDDLEWARE_REF` 为新 commit，然后
  `docker compose build && docker compose up -d --force-recreate --no-deps efb`。
- 两个中间件源码仓库（各自 README / config.example.yaml 有完整选项）：
  - https://github.com/FlechazoPh/efb-telegraph-middleware
  - https://github.com/FlechazoPh/efb-video-parser-middleware
- 抖音链接默认跳过；要支持需在 `flechazo.video_parser/config.yaml` 配
  `douyin_api`（部署 Douyin_TikTok_Download_API）或 `cookies_file`。

## 常见问题

- **EFB 启动即退出，日志 `pkg_resources ... VersionConflict` 或 `InvalidRequirement`**：
  用了上游镜像却没注释掉自建中间件；或 setuptools 版本漂移（自建镜像已锁 80.9.0）。
- **微信收到消息但 TG 不转发**：多半是 `comwechat` 里微信进程挂了。
  `docker exec comwechat sh -c "wget -qO- 'http://127.0.0.1:18888/api/?type=0'"` 看 `is_login`；
  掉了就 `docker compose up -d --force-recreate comwechat` 并重新扫码。
- **链接预览不是即时查看 / 图片裂**：确认 `.env` 的 `TELEGRAPH_IMAGE_REPO` 是**公开**仓库、
  token 有写权限；看 `docker compose logs efb | grep -i telegraph`。
- **视频转不过来**：确认 `proxy` 在跑；`docker compose logs efb | grep -i video_parser` 看报错；
  境外站需 `VIDEO_PARSER_PROXY` 指向 `proxy`。
