# 在其它服务器重新部署（面向 AI agent / 人工）

本文说明如何在一台全新机器上把这套 EFB（微信 ↔ Telegram 转发）跑起来。
仓库不含任何密钥，密钥只在 `.env` 和 git-ignored 的运行时配置里。

## 1. 这套系统由哪些容器组成

```
comwechat (Windows 微信 + hook) ─┐
                                 ├─> efb (EFB 主进程 + 中间件) ─> telegram_bot_api ─> proxy(mihomo) ─> Telegram
parsehub_service (图文/视频解析) ─┘
```

| 服务 | 作用 |
|---|---|
| `efb` | EFB 主进程，加载 slave/master 与所有中间件 |
| `comwechat` | 容器内 Windows 微信（ComWeChat Robot），提供 HTTP API |
| `telegram_bot_api` | 本地 Telegram Bot API Server，单文件上限 2GB |
| `proxy` | mihomo，为 Bot API Server 提供出站代理（TG 直连被墙时必需） |
| `parsehub_service` | 自建解析服务，供两个中间件解析抖音/快手/微博/小红书 |

自研中间件（独立仓库，按 commit 固定在 `Dockerfile` 的 ARG 里）：

- `flechazo.telegraph` — 所有链接存档到 Telegraph（即时预览），防盗链图片转存 GitHub
- `flechazo.video_parser` — 视频链接解析 → 下载 → 大视频分割 → 合并为一条消息发送

## 2. 前置条件

- Docker + Docker Compose v2
- 能访问 Docker Hub / GHCR（构建时要拉 `metacubex/mihomo`、`ghcr.io/jiz4oh/telegram-bot-api-server`）
- 一个 Telegram Bot token（BotFather）
- 一个 GitHub PAT（用于图片转存，需 `repo` 权限）
- 若服务器无法直连 Telegram：一个可用的代理订阅地址

## 3. 部署步骤

```bash
git clone https://github.com/FlechazoPh/ehforwarderbot.git
cd ehforwarderbot

# 1) 填配置：复制 .env.example 为 .env 并按注释填入真实值
cp .env.example .env
$EDITOR .env

# 2) 由 .env 渲染含密钥的运行时配置（config.yaml.example -> config.yaml）
python3 scripts/init_secrets.py

# 3) 若使用出站代理：把订阅转换成 mihomo 配置
python3 proxy/gen_config.py        # 生成 proxy/config.yaml（已 gitignore）

# 4) 构建自定义镜像（含 patches/patch_custom.py 里的补丁）
docker build -t ${EFB_IMAGE:-efb-custom:v3.1.0-plus} .

# 5) 启动
docker-compose up -d
```

> `COMPOSE_FILE` 已在 `.env` 中固定为 `compose.yaml:compose.override.yaml`。
> **不要再手动加 `-f compose.yaml`**，否则 override（代理服务）会被漏掉。

## 4. 登录微信

```bash
docker logs -f comwechat      # 或按 .env 里的密码用 VNC 连 comwechat 的 5900 端口
```

扫描日志中的二维码登录。登录状态保存在 `comwechat/Files/`，重启容器不需要重新扫码。

## 5. 验证

```bash
docker ps                                  # 5 个服务都应 Up
docker logs efb | grep 'All middlewares'   # 中间件全部初始化
docker logs telegram_bot_api               # 确认走代理
```

在微信里发一条消息、一张图、一个链接，确认 Telegram 侧都能收到。
发一个抖音链接，确认 Telegram 收到的是**视频本体**（大视频会自动分段但仍在同一条消息里）。

## 6. 配置在哪

| 文件 | 说明 |
|---|---|
| `.env` | 所有密钥与开关（唯一需要保密的文件） |
| `profiles/comwechat/config.yaml` | 启用的 slave / master / 中间件列表 |
| `profiles/comwechat/flechazo.telegraph/config.yaml` | 图文存档（支持 `${ENV}`） |
| `profiles/comwechat/flechazo.video_parser/config.yaml` | 视频解析（支持 `${ENV}`） |
| `profiles/comwechat/honus.comwechat/config.yaml` | 微信侧：主动下载、发送后删除、缓存清理 |
| `patches/patch_custom.py` | 镜像构建时打的补丁（构建期生效，改完要重新 build） |

改了 `profiles/` 下的配置后只需 `docker-compose restart efb`；
改了 `patches/` 或 `Dockerfile` 必须重新 `docker build`。

## 7. 升级自研中间件

两个中间件是独立仓库，按 commit hash 固定在 `Dockerfile`：

```dockerfile
ARG EFB_TELEGRAPH_MIDDLEWARE_REF=<sha>
ARG EFB_VIDEO_PARSER_MIDDLEWARE_REF=<sha>
```

升级流程：在对应仓库提交 → 取新 commit sha → 改 `Dockerfile` 的 ARG → 重新 build → 重启 efb。

## 8. 常见问题

**Telegram 收不到消息**：先看 `docker logs telegram_bot_api` 是否通过代理连上；
云端 Bot API 与本地 Bot API 互斥，切换前需在云端调用 `logOut` 并等待约 10 分钟。

**大文件/大视频超时**：本地 Bot API 是同步上传，2GB 约需半小时，
因此 ETM 的 `read_timeout` 设为 3600，不要改小，否则会重复投递。

**抖音/小红书解析失败**：这类站点需要 Cookie。在 `.env` 里填
`PARSEHUB_COOKIE_XHS` 等变量并重启 `parsehub_service`。

**代理节点失效**：订阅里多数节点可能不可用，用
`python3 proxy/gen_config.py && docker-compose restart proxy` 更新；
若固定 IP 失效，改 `.env` 里的 `PROXY_SERVER_IP` 与 `PROXY_SUB_RESOLVE`。

**回滚镜像**：`docker tag` 保留了历史版本，改 `.env` 的 `EFB_IMAGE` 后
`docker-compose up -d efb` 即可。
