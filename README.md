# EFB Docker 部署方案（改进版）

基于 [jiz4oh/ehforwarderbot](https://github.com/jiz4oh/ehforwarderbot) 的 **EH Forwarder Bot（EFB）** Docker 化部署方案，通过
**ComWeChat + Telegram** 实现微信与 Telegram 之间的消息双向转发。

上游引入文章：<https://jiz4oh.com/2023/01/run-efb-in-docker>

本仓库在上游基础上做了一系列**兼容性修复与稳定性增强**（详见下方「本仓库的改动」），
适合希望开箱即用、少踩坑的使用者。

> ⚠️ **安全提示**：本仓库所有配置均为**脱敏模板**，不含任何真实凭据。
> 部署前你需要填入自己的 Telegram Bot Token、管理员 ID 等，详见「配置说明」。
> **请勿**把填好的真实配置提交到公开仓库。

---

## 目录结构

```
.
├── Dockerfile                 # EFB 镜像构建（含版本锁定与补丁）
├── compose.yaml               # 主部署编排（efb + comwechat + telegram_bot_api）
├── compose.override.yaml      # 本机覆盖（mihomo 代理等，不提交）
├── docker-compose.web.yaml    # Web 场景编排
├── docker-compose.windows.yaml# Windows/WSL 场景编排
├── entrypoint.sh              # 容器入口
├── run2.py                    # comwechat 容器内的启动脚本（VNC + 微信 + Hook）
├── cleanup.sh                 # 定期清理脚本
├── proxy/gen_config.py        # 从订阅生成 mihomo 配置（proxy/config.yaml 不提交）
├── patches/                   # 对上游 Python 包的补丁脚本
│   └── patch_custom.py
├── .env.example               # 环境变量模板（密钥集中于此）
└── profiles/                  # EFB profile（master/slave/middleware 配置）
    └── comwechat/
```

---

## 本仓库的改动

相对上游，主要做了以下修复与增强：

### 1. 修复 `setuptools` / `pkg_resources` 依赖死结

- 新版 `efb-telegram-master` 要求 `setuptools>=82`，而 `setuptools>=81` 不再自带 `pkg_resources`；
- 但 `ehforwarderbot 2.1.1` 运行时必须 `import pkg_resources`，二者形成死结，导致 EFB 无法启动。
- **处理**：将 `setuptools` 锁定在 `80.9.0`（最后一个仍自带 `pkg_resources` 的版本），
  并把 `efb-telegram-master` 锁定在引入该约束之前的提交 `5e48545`。

### 2. 插件版本锁定与兼容性说明

`python-comwechatrobot-http` 与 `efb-wechat-comwechat-slave` 锁定在互相匹配的组合
（`3df22af` + `bf54943`）。

原因：新版 `python-comwechatrobot-http` 改为通过独立的 **bridge 服务（`:19088` / `/v1/messages/pull`）**
拉取消息，而 `comwechat` 镜像并不提供该服务，会**导致消息完全收不到**。

### 3. 行为补丁（`patches/patch_custom.py`）

构建镜像时对已安装的插件打补丁（找不到目标片段时只告警、不中断构建）：

1. **群发送者名字**：恢复「备注 (微信名)」格式，但去掉无法渲染（会显示成方块）的字符，
   且备注与微信名相同时只显示一个；并去掉上游给括号名字加的 `tg-spoiler` 遮罩。
2. **微信图片下载超时**：群原图是**延迟下载**的（`extrainfo` 中 `cdnbigimgurl_pd_pri="30"`），
   等待时间 5s → **60s**，超时后**回退用微信已下载的缩略图**，而不是显示「下载超时」。
3. **EFB 重启后旧「重试」按钮仍可用**：从 slave 的 `media_retry` 库恢复过期回调。
4. **媒体主动下载 + 缓存清理**：收到图片/视频/文件后主动触发微信下载原文件，
   转发成功后删除其全部磁盘副本（原文件、重复副本、缩略图、解码图、Temp 副本），
   并每小时清理超过 N 天的旧媒体缓存（避免微信目录无限增长）。

### 4. 修复 Telegram 大文件被重复投递 / 50MB 上限

- 默认经公共 Bot API 上传大文件易超时触发 ETM「无限重试」而重复投递，单文件还受 50MB 限制。
- **处理**：`compose.override.yaml` 起一个 **本地 Bot API Server**（上限 2GB），
  经 **mihomo 代理** 连 Telegram；`blueset.telegram/config.yaml` 打开
  `api_base_url` / `api_base_file_url` / `local_tdlib_api` 并把 `read_timeout` 放宽到 3600。

### 5. 新增四个中间件

| 中间件 | 作用 | 备注 |
|---|---|---|
| `catbaron.voice_recog` | 微信语音消息转文字 | 需自行开通云服务（如腾讯云 ASR） |
| `catbaron.search_msg` | 按中文关键词搜索历史消息 | TG 对中文不分词，此中间件可补全 |
| [`flechazo.telegraph`](https://github.com/FlechazoPh/efb-telegraph-middleware) | **所有链接**存档到 Telegraph，Telegram 里即时预览 | 防盗链图片自动转存到你的 GitHub 仓库 |
| [`flechazo.video_parser`](https://github.com/FlechazoPh/efb-video-parser-middleware) | 视频链接下载为**视频消息**，超限无损分段并合并为一条相册 | B 站/小红书/YouTube/X 等；抖音需配 API 或 cookies |

并修复了 `efb-search_msg-middleware` 元数据中的畸形依赖声明
（`python-telegram-bot (>=10.0.0<12.0.0)`，缺逗号会导致 `pkg_resources` 抛 `InvalidRequirement`）。

`flechazo.telegraph` 取代了只处理公众号的 `catbaron.mp_instantview`（已停用）。

### 6. 其他

- 启用 `jiz4oh.map` 地图中间件；
- 补齐 `docker-compose` 中 `comwechat.zip` 的挂载。

---

## 快速开始

### 前置条件

1. 一台可运行 Docker 的 Linux 服务器（建议 2C4G 以上，微信容器较吃资源）；
2. 一个 Telegram Bot Token（向 [@BotFather](https://t.me/BotFather) 申请）；
3. 你的 Telegram 数字 ID（可通过 [@userinfobot](https://t.me/userinfobot) 获取）；
4. Docker 与 Docker Compose。

### 部署步骤

```bash
# 1. 克隆仓库
git clone <你的仓库地址> ehforwarderbot
cd ehforwarderbot

# 2. 准备环境变量（集中存放所有密钥，profile 配置用 ${...} 引用）
cp .env.example .env
#   填入 TELEGRAM_API_ID / TELEGRAM_API_HASH / COMWECHAT_VNC_PASSWORD
#   如用 flechazo.telegraph：TELEGRAPH_IMAGE_REPO / TELEGRAPH_IMAGE_GITHUB_TOKEN
#   如需代理：PROXY_SUB_URL 等
chmod 600 .env

# 3. 准备各 channel / 中间件配置（示例复制为正式配置）
cp profiles/comwechat/blueset.telegram/config.yaml.example \
   profiles/comwechat/blueset.telegram/config.yaml   # 填 token / admins
cp profiles/comwechat/flechazo.telegraph/config.yaml.example \
   profiles/comwechat/flechazo.telegraph/config.yaml
cp profiles/comwechat/flechazo.video_parser/config.yaml.example \
   profiles/comwechat/flechazo.video_parser/config.yaml
# 语音转文字（可选）：cp catbaron.voice_recog/config.yaml.example 为 config.yaml

# 4. 如需出站代理：从订阅生成 mihomo 配置
python3 proxy/gen_config.py            # 读取 .env 的 PROXY_SUB_URL -> proxy/config.yaml

# 5. 构建镜像并启动
docker compose build
docker compose up -d

# 6. 通过 VNC 连接 5905 端口扫码登录微信（密码为 .env 里的 COMWECHAT_VNC_PASSWORD）

# 7. 在 Telegram 里与自己的 Bot 对话，用 /extra 等命令完成绑定
```

> `flechazo.*`、`voice_recog`、`search_msg` 中间件只在自建镜像 `efb-custom:v3.1.0-plus` 里。
> 若改用上游预构建镜像 `ghcr.io/jiz4oh/efb:v3.1.0`，必须在 `config.yaml` 里注释掉它们，否则 EFB 无法启动。

> 若你的 Docker 是 v1 插件形式（`docker compose` 不可用），请使用 `docker-compose` 命令。

### 常用运维

```bash
docker compose logs -f efb          # 查看 EFB 日志
docker compose restart efb          # 仅重启 EFB（不影响微信登录态）
docker compose ps                   # 查看状态
```

**注意**：`efb` 使用 `network_mode: "service:comwechat"`，两者共享网络命名空间。
重建 `comwechat` 会导致微信掉线需重新扫码；**只重启 efb 不会影响微信登录态**。

---

## 配置说明

密钥集中放在 `.env`，profile 下的 `config.yaml` 用 `${VAR}` 引用（`compose.yaml` 负责把变量传入 efb 容器）。

| 变量（`.env`） | 说明 |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | 本地 Bot API Server 必需，[my.telegram.org](https://my.telegram.org) 获取 |
| `COMWECHAT_VNC_PASSWORD` | VNC 扫码登录密码，务必修改 |
| `TELEGRAPH_TOKEN` | 留空则 `flechazo.telegraph` 自动建号 |
| `TELEGRAPH_IMAGE_REPO` / `TELEGRAPH_IMAGE_GITHUB_TOKEN` | 防盗链图片转存的公开仓库与写权限 token |
| `VIDEO_PARSER_PROXY` | 视频中间件访问境外站点的代理 |
| `PROXY_SUB_URL` 等 | mihomo 代理订阅（见 `proxy/gen_config.py`） |

`blueset.telegram/config.yaml` 里的 `token` / `admins` 仍需直接填（BotFather Token 与你的 TG 数字 ID）。

### Telegram Master 推荐配置

```yaml
token: "YOUR_TELEGRAM_BOT_TOKEN"
admins:
- YOUR_TELEGRAM_USER_ID
# 使用本地 Bot API Server 时文件同步上传，读超时放宽到 1 小时，避免被误判超时而重复投递
request_kwargs:
    read_timeout: 3600
    connect_timeout: 20
flags:
    retry_on_error: true
    auto_locale: false
    animated_stickers: true
    # 本地 Bot API Server（单文件上限 2GB），由 compose 里的 telegram_bot_api 提供
    api_base_url: "http://telegram_bot_api:8081/bot"
    api_base_file_url: "http://telegram_bot_api:8081/file/bot"
    local_tdlib_api: true
```

### 中间件清单（`profiles/comwechat/config.yaml`）

```yaml
master_channel: "blueset.telegram"
slave_channels:
- "honus.comwechat"
middlewares:
- QQ_War.keyword_reply
- QQ_War.message_merge
- jiz4oh.keyword_replace
- jiz4oh.map
- catbaron.voice_recog      # 可选，需开通云服务
- catbaron.search_msg       # 可选
- flechazo.video_parser     # 视频链接 -> 视频消息（放在 telegraph 之前）
- flechazo.telegraph        # 所有链接 -> Telegraph 即时预览
```

---

## 脱敏说明（提交前必读）

以下内容**绝对不要**提交到公开仓库：

- `.env`（Telegram API id/hash、Bot Token、GitHub token、代理订阅、VNC 密码等）
- Telegram Bot Token、管理员 ID、Telegraph Token
- 语音识别服务的 SecretId / SecretKey
- `proxy/config.yaml`（含代理节点凭据）、`compose.override.yaml`
- `profiles/**` 下的真实配置、`*.db` 消息数据库、`comwechat/Files/` 聊天文件

本仓库 `.gitignore` 已忽略 `*.db*`、`WeChat/`、`/comwechat/`、`.env`、`compose.override.yaml`、
`proxy/config.yaml`。真实 channel 配置建议只提交 `.example` 模板：

```
profiles/*/blueset.telegram/config.yaml
profiles/*/catbaron.voice_recog/config.yaml
```

> 本方案已把密钥集中到 `.env`，`flechazo.*` 的 `config.yaml` 只用 `${...}` 引用、不含明文，可安全提交。
> 如果仓库历史里曾提交过凭据，请用 `git filter-repo` / BFG 清理，并**立即吊销已泄露的 Token/密钥**。

---

## 已知问题

- **语音转文字需要自行开通云服务**：以腾讯云为例，未开通时会返回
  `FailedOperation.UserNotRegistered`（`User is unopened`）。密钥有效但未开通服务不会报错到启动阶段，
  只会在每条语音上附带错误信息，建议开通前先禁用该中间件。
- **`efb-online-middleware` 不兼容本方案**：它依赖官方 `efb-wechat-slave` 的 `wxpy`
  且只认 `blueset.wechat`，在 `honus.comwechat` 下会直接 `ImportError`，故未启用。
- **微信长时间运行可能崩溃**：曾出现运行数月后 `WeChat.exe` 变僵尸进程、
  消息静默不转发的情况。建议定期检查（如探活 `http://127.0.0.1:18888/api/?type=0`
  返回的 `is_login`）或配置定时重启/告警。
- **微信插件不要盲目升级**：`python-comwechatrobot-http` 与
  `efb-wechat-comwechat-slave` 需配套升级，详见上文第 2 点。

---

## 致谢

本方案站在众多开源项目之上，特此致谢：

- **[jiz4oh](https://github.com/jiz4oh)** — 上游 Docker 方案作者，以及
  `efb-telegram-master`、`efb-wechat-comwechat-slave`、`python-comwechatrobot-http`、
  `efb-map-middleware`、`efb-mp-instantview-middleware`、`efb-keyword-replace` 等 fork 的维护者；
- **[Eana Hufwe / blueset](https://github.com/ehForwarderBot)** —
  [EhForwarderBot](https://github.com/ehForwarderBot/EhForwarderBot) 框架作者；
- **[0honus0](https://github.com/0honus0)** — `efb-wechat-comwechat-slave`（ComWeChat Slave）作者；
- **[ljc545w](https://github.com/ljc545w)** — [ComWeChatRobot](https://github.com/ljc545w/ComWeChatRobot) 作者；
- **[tomsnow1999](https://github.com/tomsnow1999)** — `docker-com_wechat_robot` 镜像维护者；
- **[QQ-War](https://github.com/QQ-War)** — `efb-keyword-reply`、`efb_message_merge` 作者；
- **[catbaron](https://github.com/catbaron)** — `mp_instantview`、`voice_recog`、`search_msg` 等中间件作者；
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** 与 **ffmpeg** — `flechazo.video_parser` 的下载与分段基础；
- **Wolfsilver** — `efb-patch-middleware`、`efb-online-middleware` 作者；
- 以及 EhForwarderBot 社区所有贡献者与插件作者。

---

## 版权声明

- 本仓库 **fork 自 [jiz4oh/ehforwarderbot](https://github.com/jiz4oh/ehforwarderbot)**，
  许可以上游仓库为准；本仓库中的改动（`Dockerfile`、`patches/`、`README.md` 等）
  以与上游相同的开源许可发布。
- 各组件遵循各自许可，包括但不限于：
  - [EhForwarderBot](https://github.com/ehForwarderBot/EhForwarderBot)：**AGPL-3.0-or-later**
  - EFB Telegram Master Channel：AGPL-3.0-or-later
  - EFB WeChat ComWeChat Slave、ComWeChatRobot 等：请参照各自仓库声明
- 本项目仅用于**个人学习与技术交流**，整合的第三方代码版权归各自作者所有。
- **使用风险提示**：通过第三方客户端转发微信消息可能违反相关平台的用户协议，
  请自行评估合规风险，因使用本方案产生的任何后果由使用者自行承担。
