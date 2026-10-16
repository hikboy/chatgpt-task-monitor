# ChatGPT Task Monitor

[![Tests](https://github.com/hikboy/chatgpt-task-monitor/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/hikboy/chatgpt-task-monitor/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platforms](https://img.shields.io/badge/Platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

**Codex 一轮任务结束后，将会话名称、当前请求和结果摘要发送到 Telegram。**

通过 Codex 原生 `notify` 回调触发，只使用 Python 标准库，无需安装第三方 Python 包，也无需常驻监听服务、终端插件或截图。

> **适用范围**：目前接入 Codex CLI，以及会调用相同 `notify` 回调的桌面本地 Codex 会话。普通 ChatGPT 网页聊天和未提供该回调的 ChatGPT / Work 会话尚未接入。

## 功能

- **跨平台**：Windows、macOS、Linux 共用一份 Python 脚本。
- **自动通知**：接收 `agent-turn-complete` 事件后发送 Telegram 消息。
- **可读排版**：使用 Telegram HTML 模式，标题加粗，正文保留段落，列表统一为圆点。
- **当前任务**：选择最近的有效用户请求，过滤已识别的自动接力摘要、环境信息和结构化问答回执。
- **结果摘要**：提取回复开头的正文和前三条列表要点，表格与代码块改为查看会话的提示。
- **会话名称**：支持从事件、Codex 本地数据库和会话索引中读取名称。
- **保留已有配置**：安装前备份配置，保留其他 TOML 设置并转发原有通知回调。
- **离线预览**：不发送消息即可查看通知内容；测试无需真实凭据。

## 通知示例

Telegram 中的 Success、Session、Task、Result 标题会加粗，各部分之间用空行分隔：

```text
✅ Success

📌 Session
通知脚本优化

📝 Task
整理脚本，让 Windows、macOS、Linux 都能发送通知

💡 Result
已完成跨平台通知脚本整理。

• 三个系统共用同一份通知逻辑
• 保留当前请求和结果摘要
• 凭据与项目源码分开保存

💻 my-computer
🕒 2026-10-16 14:00:00 +0800
```

`Success` 表示收到正常的本轮完成事件，**不代表任务内的测试或业务操作全部成功**。调用方可额外传入本项目自定义字段 `"notification-status": "failed"`，显示 `❌ Failed`；脚本不会根据回复中出现“失败”等词猜测任务状态。

## 快速开始

### 1. 准备环境与 Telegram 机器人

需要：

- Python **3.11 或更新版本**。
- 支持原生 `notify` 回调的 Codex 环境。
- 一台能够通过 HTTPS 访问 `api.telegram.org` 的电脑。
- Telegram Bot Token 和目标 Chat ID。

在 Telegram 中联系 [@BotFather](https://t.me/BotFather)，创建机器人并取得 Bot Token。给机器人发送 `/start` 或一条消息，再通过 [Bot API 的 getUpdates](https://core.telegram.org/bots/api#getupdates) 获取 `message.chat.id`。群组的 Chat ID 可能带负号，请完整保留。

### 2. 获取项目

```bash
git clone https://github.com/hikboy/chatgpt-task-monitor.git
cd chatgpt-task-monitor
```

也可以从 GitHub 下载源码 ZIP，解压后进入项目目录。

### 3. 安装并配置

**Windows / PowerShell**

```powershell
python --version
python .\codex_telegram.py install
python .\codex_telegram.py configure --test
```

Windows 安装器优先使用同一 Python 安装目录中的 `pythonw.exe`，避免通知时弹出控制台窗口。

**macOS / Linux**

```bash
python3 --version
python3 ./codex_telegram.py install
python3 ./codex_telegram.py configure --test
```

如果默认 Python 版本低于 3.11，请先安装更新版本，并使用对应解释器执行命令，例如 `python3.12`。

`configure --test` 会隐藏输入 Bot Token，提示输入 Chat ID，保存后发送一条测试通知。已有配置时，直接按回车可保留原值。

### 4. 重启并验证自动通知

完整退出并重新打开 Codex，再完成一轮简单对话，验证自动通知。

`configure --test` 成功仅说明 Telegram 发送通道可用；完成一轮真实对话才能确认回调已经触发。

## 常用命令

以下示例使用 `python3`；Windows 可换成 `python`。

```bash
# 离线预览，不发送消息，也不调用原有通知回调。
python3 ./codex_telegram.py test --dry-run

# 离线预览 Failed 样式。
python3 ./codex_telegram.py test --outcome failed --dry-run

# 发送一条测试通知。
python3 ./codex_telegram.py test

# 使用指定会话的真实名称发送测试通知。
python3 ./codex_telegram.py test --session-id YOUR_SESSION_ID

# 查看版本和命令帮助。
python3 ./codex_telegram.py --version
python3 ./codex_telegram.py --help
```

发送测试成功时返回 `success: true`、`status: "sent"`。离线预览返回 `status: "dry-run"`，并包含 HTML 消息内容。

## 配置与安装位置

安装器会更新用户级 Codex 配置的顶层 `notify`，写入 Python 解释器和已安装脚本的绝对路径。

| 内容 | 默认位置 |
| --- | --- |
| Codex 配置 | `~/.codex/config.toml` |
| 通知脚本与运行时配置 | `~/.codex/notifications/codex-telegram/` |
| Telegram 凭据 | `~/.codex/notifications/codex-telegram/settings.json` |
| 安装前的配置备份 | `~/.codex/config.toml.backup-telegram-*` |

Windows 中 `~` 对应 `%USERPROFILE%`。项目文件夹可以放在任意位置；安装后的脚本和凭据位于用户的 Codex 数据目录。

通知目录中的文件：

| 文件 | 用途 |
| --- | --- |
| `codex_telegram.py` | 三个平台共用的通知逻辑 |
| `settings.json` | Telegram Bot Token 与 Chat ID |
| `codex-original-notify.json` | 保存并转发原有通知命令 |
| `runtime.json` | Python 路径，供 Windows 兼容入口读取 |
| `codex-telegram.ps1` | 旧 PowerShell 调用方式的兼容入口 |
| `error.log` | 时间与固定错误代码 |

### 环境变量

也支持通过以下环境变量提供凭据：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

每个值的读取顺序为：**当前进程环境变量 → `settings.json` → Windows 用户/系统环境变量**。

推荐使用 `configure` 保存凭据，桌面应用读取配置文件时无需继承终端环境变量。早期 Windows 设置窗口保存的环境变量仍受支持。

### 自定义 CODEX_HOME

支持 `CODEX_HOME` 环境变量，也可以通过全局参数指定：

```bash
python3 ./codex_telegram.py --codex-home /custom/codex install
python3 ./codex_telegram.py --codex-home /custom/codex configure --test
```

安装器会将所选目录写入回调参数，后续触发无需依赖同名环境变量。

### 更新与回退

在项目目录中获取更新，再重新部署：

```bash
git pull --ff-only
python3 ./codex_telegram.py install
```

Windows 使用 `python`。更新不会要求重新输入已有凭据；如果 Python 的安装位置发生变化，请使用新解释器重新运行 `install`。

需要回退时，从安装前的 `config.toml.backup-telegram-*` 备份中取回原来的 `notify` 设置，再重启 Codex。若其他配置后来有修改，请保留这些修改。

## 通知内容规则

| 部分 | 处理方式 |
| --- | --- |
| Session | 最多 200 字；优先事件名称，再查询本地数据库和会话索引，最后回退到标题或会话 ID |
| Task | 从回调 `input-messages` 倒序选择有效请求，最多 150 字；不拼接历史问题 |
| Result | 最多两段正文与前三条列表要点，总计最多 300 字；每条要点最多 60 字 |
| 电脑与时间 | 本机主机名、本地时间及 UTC 偏移 |

任务筛选会跳过具有已知完整前缀的自动接力摘要，以及消息开头已闭合的环境信息、结构化问答回执。环境信息之后若还有用户请求，会保留该请求；只有自动上下文时显示“未提供任务内容”。这是对已知消息格式的处理，无法识别所有第三方自行插入的文本。

结果摘要是已有回复的摘录，**不会额外调用模型**。普通 Markdown 装饰会清理，HTML 特殊字符会转义；原文没有列表时不会生成新的列表要点。表格和围栏代码块不直接拼入摘要，通知会提示查看会话。

已有的通知回调会继续调用。安装器同时处理桌面通知器的 `--previous-notify` 包装形式，清理对本通知器的重复引用，避免循环调用和重复发送。

## 隐私与凭据

- 通知会把**会话名称、任务摘录、回复摘录、电脑名和时间**发送到你配置的 Telegram 聊天，请按实际任务内容选择是否启用。
- Bot Token、Chat ID、原通知命令和本机 Python 路径保存在用户目录，由每台电脑自行配置。
- macOS / Linux 的凭据文件权限为 `0600`；Windows 文件继承当前用户目录的访问权限。
- 错误日志只记录时间和固定错误代码，不记录 Token、请求 URL 或任务正文；HTTPS 保持证书校验。
- `.gitignore` 排除凭据、环境变量文件、运行时配置、会话数据、数据库、日志、备份、私钥与压缩包。手工写入源码的秘密仍需在提交前检查。
- 测试中的凭据和会话标识为虚构值，GitHub Actions 无需配置真实 Telegram 凭据。

## 常见问题

| 现象或错误代码 | 处理方式 |
| --- | --- |
| `missing-telegram-settings` | 运行 `configure --test` 配置凭据 |
| `invalid-telegram-settings` | 检查 Bot Token 和 Chat ID 格式 |
| `telegram-request-failed` | 检查网络、代理及 TLS 证书；浏览器代理不一定对 Python 生效 |
| `telegram-rejected-message` | 检查机器人与目标聊天是否可用，确认已向机器人发过消息 |
| 测试能收到，真实任务无通知 | 完整重启 Codex，并确认所用会话会调用 `notify` 回调 |
| 修改源码后通知仍是旧版本 | 重新运行项目中的 `install`，部署到实际通知目录 |
| `original-callback-unavailable` | 原有通知程序已移动或卸载；不影响 Telegram 继续发送 |

发送超时为 15 秒。测试命令失败会返回非零退出码；原生 `notify` 入口失败时保持安静，不阻断 Codex 任务。

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
```

测试使用模拟 Telegram 响应，不发送真实消息。覆盖任务选择、自动上下文过滤、HTML 排版与转义、结果摘要、会话名称、凭据读取、HTTP 请求、配置备份、重复安装和原通知回调转发等逻辑。

GitHub Actions 配置了 Windows / macOS / Linux 与 Python 3.11 / 3.13 的六组测试任务。最新远端执行结果见顶部 Tests 徽章。

当前本地验证：Windows / Python 3.12.3、Linux（WSL）/ Python 3.14.4 各 43 项测试通过。Windows 此前完成过真实 HTML 通知发送及 PowerShell 兼容入口验证；Linux 尚未验证联网发送，macOS 尚未实机验证。单元测试通过不等于已验证所有平台的真实通知链路。

项目结构：

```text
chatgpt-task-monitor/
├── codex_telegram.py             # 通知逻辑与安装、配置命令
├── codex-telegram.ps1            # Windows 旧入口兼容层
├── tests/test_codex_telegram.py  # 标准库 unittest 测试
├── .github/workflows/tests.yml  # 跨平台 CI
├── .gitattributes
├── .gitignore
└── README.md
```

## 当前限制

- 当前处理 Codex 的 `agent-turn-complete` 事件，不覆盖进程崩溃、卡死和所有等待审批的情况。
- 完成事件本身不提供任务业务成败判定；`Failed` 需要调用方显式传入自定义状态。
- 会话名称依赖本地数据格式，读取不到时会使用回退名称。
- 不提供 Telegram 双向控制，也不监听任意 PowerShell 窗口或普通 ChatGPT 网页。

## 参考

- [Codex Notifications 配置](https://developers.openai.com/codex/config-advanced/#notifications)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Telegram HTML 消息格式](https://core.telegram.org/bots/api#html-style)
