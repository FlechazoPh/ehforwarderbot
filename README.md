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
├── docker-compose.yaml        # 主部署编排（efb + comwechat）
├── docker-compose.web.yaml    # Web 场景编排
├── docker-compose.windows.yaml# Windows/WSL 场景编排
├── entrypoint.sh              # 容器入口
├── run2.py                    # comwechat 容器内的启动脚本（VNC + 微信 + Hook）
├── cleanup.sh                 # 定期清理脚本
├── patches/                   # 对上游 Python 包的补丁脚本
│   └── patch_comwechat.py
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

### 3. 修复微信图片「下载超时」

- 现象：群图片经常显示 `[image 下载超时,请在手机端查看]`。
- 根因：微信群原图是**延迟下载**的（消息 `extrainfo` 中 `cdnbigimgurl_pd_pri="30"`），
  而 slave 里等待落盘的超时**硬编码为 120 秒**，经常卡在边界上。
- **处理**：
  - 等待时间 120s → **300s**（`patches/patch_comwechat.py`）；
  - 超时后**回退使用微信已下载的缩略图**（取消息自带的 `thumb_path`，且校验文件真实存在），
    而不是只显示一行「下载超时」文字。

### 4. 修复 Telegram 大文件被重复投递

- 现象：同一张图在 Telegram 里重复出现多次。
- 根因：ETM 默认 `read_timeout=15s`，上传大文件（数 MB）时易超时，
  触发其「无限重试」机制；而 Telegram 其实已收到，于是重复。
- **处理**：在 `blueset.telegram/config.yaml` 中通过 `request_kwargs` 放宽为 `read_timeout: 120`。

### 5. 新增两个中间件

| 中间件 | 作用 | 备注 |
|---|---|---|
| `catbaron.voice_recog` | 微信语音消息转文字 | 需自行开通对应云服务（如腾讯云 ASR） |
| `catbaron.search_msg` | 按中文关键词搜索历史消息 | TG 对中文不分词，此中间件可补全 |

并修复了 `efb-search_msg-middleware` 元数据中的畸形依赖声明
（`python-telegram-bot (>=10.0.0<12.0.0)`，缺逗号会导致 `pkg_resources` 抛 `InvalidRequirement`）。

### 6. 其他

- 启用 `jiz4oh.map` 地图中间件、修正 `mp_instantview` 配置；
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

# 2. 准备配置（把示例配置复制为正式配置并填入自己的凭据）
cp profiles/comwechat/blueset.telegram/config.yaml.example \
   profiles/comwechat/blueset.telegram/config.yaml
# 编辑填入 token / admins
# 如需语音转文字：
cp profiles/comwechat/catbaron.voice_recog/config.yaml.example \
   profiles/comwechat/catbaron.voice_recog/config.yaml

# 3. 构建并启动（comwechat 先起，efb 共享其网络）
docker compose up -d

# 4. 通过 VNC 连接 5905 端口扫码登录微信
#    （VNC 密码为 docker-compose.yaml 中的 VNCPASS，请自行修改）

# 5. 在 Telegram 里与自己的 Bot 对话，使用 /extra 等命令完成绑定
```

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

所有占位符都需要替换为你自己的值：

| 占位符 | 位置 | 说明 |
|---|---|---|
| `YOUR_TELEGRAM_BOT_TOKEN` | `profiles/*/blueset.telegram/config.yaml` | BotFather 给的 Token |
| `YOUR_TELEGRAM_USER_ID` | 同上 `admins` | 你的 Telegram 数字 ID |
| `YOUR_TELEGRAPH_TOKEN` | `profiles/*/catbaron.mp_instantview/config.yaml` | 公众号 InstantView 用 |
| `YOUR_SECRET_ID` / `YOUR_SECRET_KEY` | `profiles/*/catbaron.voice_recog/config.yaml` | 语音识别服务密钥 |
| `VNCPASS` | `docker-compose.yaml` | VNC 连接密码，请务必修改 |

### Telegram Master 推荐配置

```yaml
token: "YOUR_TELEGRAM_BOT_TOKEN"
admins:
- YOUR_TELEGRAM_USER_ID
# 放宽读超时，避免大文件上传被误判超时而重复投递
request_kwargs:
    read_timeout: 120
    connect_timeout: 20
flags:
    retry_on_error: true
    auto_locale: false
    animated_stickers: true
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
- catbaron.mp_instantview
- jiz4oh.map
- catbaron.voice_recog     # 可选，需开通云服务
- catbaron.search_msg      # 可选
```

---

## 脱敏说明（提交前必读）

以下内容**绝对不要**提交到公开仓库：

- Telegram Bot Token、管理员 ID
- 语音识别服务的 SecretId / SecretKey
- Telegraph Token
- VNC 密码（`VNCPASS`）
- `profiles/**` 下的真实配置、`*.db` 消息数据库、`comwechat/Files/` 聊天文件

本仓库 `.gitignore` 已忽略 `*.db*`、`WeChat/`、`/comwechat/`。
建议进一步忽略真实配置，只提交 `.example` 模板：

```
profiles/*/blueset.telegram/config.yaml
profiles/*/catbaron.voice_recog/config.yaml
profiles/*/catbaron.mp_instantview/config.yaml
```

> 如果你的仓库历史里曾经提交过这些凭据，请在推送前用 `git filter-repo` / BFG 清理历史，
> 并且**立即到对应平台吊销（revoke）已泄露的 Token/密钥**。

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
