# Codex Telegram 完成通知

macOS、Linux、Windows 共用的通知脚本。Codex 一轮任务完成时，通过原生 `notify` 回调发送 Telegram 消息，不需要常驻服务、WezTerm 或截图。

需要 **Python 3.11 或更新版本**，只使用标准库，无需 `pip install`。

通知使用 Telegram HTML 模式发送：标题加粗，各部分用空行分隔。显示内容示例：

```text
✅ 本轮任务完成

会话：通知排版

任务
通知中增加任务摘要和结果摘要

结果
已修改脚本，测试通过。

📋 回复包含对比表，详情见会话。

💻 my-computer
🕒 2026-10-16 13:00:00 +0800
```

任务摘要最多 150 字，会话名称最多显示 200 字；结果保留开头最多两段正文、最多 300 字，保留段落和列表换行，超长时优先在完整句子处截断。摘要为已有文本的摘录，不额外调用模型。通知包含任务和回复的这部分内容。

正文中的 Markdown 加粗、标题、行内代码及链接标记会清理为可读文字；对比表和围栏代码块改为“详情见会话”的提示，不直接拼进摘要。标题由脚本生成 HTML，正文统一转义 `<`、`>`、`&` 等特殊字符，避免原始文本被当成标签。只更新脚本即可生效，无需重新填写 Telegram 凭据。

## 安装

将本目录复制到目标电脑，在目录内执行。安装器会备份原配置，保留其他 TOML 设置，并保存原有通知回调，在发送 Telegram 的同时继续调用它。

兼容桌面应用用 `--previous-notify` 包裹旧通知器的情况：保留桌面通知命令，移除它对本通知器的重复引用，避免循环调用或重复发送 Telegram。

### Windows

```powershell
python --version
python .\codex_telegram.py install
python .\codex_telegram.py configure --test
```

已通过旧 Windows 设置窗口保存的 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 会继续读取；已有凭据时可直接运行 `test`。安装器优先使用同一 Python 安装目录的 `pythonw.exe`，避免通知时弹出控制台。

### macOS

```bash
python3 --version
python3 ./codex_telegram.py install
python3 ./codex_telegram.py configure --test
```

如果没有 Python 3.11+，使用 Python 官方安装包或 Homebrew 安装后再执行。

### Linux

```bash
python3 --version
python3 ./codex_telegram.py install
python3 ./codex_telegram.py configure --test
```

如果发行版的默认 Python 低于 3.11，先安装更新版本，并将上述 `python3` 换成对应解释器，例如 `python3.12`。安装器会记住实际使用的解释器绝对路径。

**安装后完整退出并重启 Codex / 使用本地 Codex 后端的桌面应用，再完成一轮对话验证自动触发。** 以后只更新脚本内容不必重新设置 `notify`；重新运行 `install` 可部署新版。Python 被移动或卸载后，需要用新解释器重新安装本通知器。

## Telegram 凭据

通过 Telegram 的 `@BotFather` 获取 Bot Token，给机器人发一条消息，再从 Bot API 的 `getUpdates` 返回值中找到 `message.chat.id`。

推荐运行 `configure --test`：在终端隐藏输入 Bot Token，输入 Chat ID，保存后发送一条测试消息。凭据保存在：

- macOS / Linux：`~/.codex/notifications/codex-telegram/settings.json`。
- Windows：`%USERPROFILE%\.codex\notifications\codex-telegram\settings.json`。

macOS / Linux 上该文件权限为 `0600`。Windows 文件保存在当前用户目录，继承其访问权限。桌面应用可直接读取此文件，不依赖启动它的终端环境。

也支持环境变量 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`。读取顺序为：当前进程环境变量 → `settings.json` → Windows 用户/系统环境变量。若同时配置多种来源，请留意这个优先级。旧 Windows 设置窗口在没有新 `settings.json` 覆盖值时仍可使用。

## 测试与预览

Windows 使用 `python`；macOS / Linux 使用 `python3`。

```bash
# 只预览，不联网、不调用原有回调。
python3 ./codex_telegram.py test --dry-run

# 发送测试；指定会话 ID 时显示该会话的真实名称。
python3 ./codex_telegram.py test --session-id YOUR_SESSION_ID

# 查看命令帮助。
python3 ./codex_telegram.py --help
```

测试发送成功时返回 `success: true`、`status: "sent"`。这验证 Telegram 通道；原生自动触发仍需在应用中完成一轮对话确认。

会话名称优先读取事件自带的 `thread-name`，其次只读查询 Codex 本地数据库中的显式名称，再读取 `session_index.jsonl` 的最新命名记录；无显式名称时使用数据库标题，仍找不到则显示会话 ID。

## 文件位置与兼容入口

安装器自动更新用户级 `~/.codex/config.toml` 的顶层 `notify`，使用 Python 和已安装脚本的绝对路径。安装文件位于 `~/.codex/notifications/codex-telegram/`：

| 文件 | 用途 |
| --- | --- |
| `codex_telegram.py` | 三个系统共用的通知逻辑 |
| `settings.json` | 可选的 Telegram 凭据 |
| `codex-original-notify.json` | 原有通知命令，避免覆盖原功能 |
| `runtime.json` | 实际 Python 路径，供 Windows 兼容入口读取 |
| `codex-telegram.ps1` | 兼容早期 PowerShell 调用及设置窗口 |
| `error.log` | 仅记录时间和固定错误代码 |

`CODEX_HOME` 非默认位置也受支持，或使用全局参数，例如：

```bash
python3 ./codex_telegram.py --codex-home /custom/codex install
```

安装命令会把这个目录写入回调参数，后续无需依赖同名环境变量。修改配置前的备份为该目录下 `config.toml.backup-telegram-*`；需要回退时，可从备份恢复原来的 `notify` 配置。

本包不包含真实凭据。凭据文件、错误日志、Python 缓存不应放入分发压缩包。

## Git 管理

本目录是独立仓库，仅跟踪通知源码、测试、文档和 CI 配置。安装目录在用户的 Codex 数据目录中，真实 Token、Chat ID、原通知命令和 Python 路径由每台电脑自行配置，不复制进仓库。

`.gitignore` 已排除凭据、环境变量文件、运行时配置、Codex 配置及备份、会话数据、日志、私钥、缓存和压缩包。测试中的 Token、Chat ID、会话 ID 均为虚构数据。忽略规则无法检测写入源码的秘密，也不能阻止 `git add -f`；提交前仍需检查暂存区：

```bash
git status --short
git diff --cached --stat
git diff --cached
git commit -m "Describe the change"
```

初始提交使用通用作者身份 `Codex Notifications <notifications@example.invalid>`，仓库本地 Git 配置也使用此身份，避免自动带入全局配置中的真实姓名或邮箱。仓库尚未配置远端；需要同步时，再添加目标远端并推送。

## 排错

`missing-telegram-settings`：未找到凭据。运行 `configure --test`。

`invalid-telegram-settings`：Token 或 Chat ID 格式不正确。

`telegram-request-failed`：检查目标电脑访问 `api.telegram.org` 的网络、代理和 TLS 证书。脚本使用 Python 标准 HTTPS 校验及代理设置；不关闭证书验证。

`original-callback-unavailable`：原有通知程序已移动；不影响 Telegram 继续发送。Windows 旧版本化 `cua_node` 路径会尝试解析到已安装的新版本。

通知发送超时为 15 秒；失败记录固定代码，不把 Token、请求 URL 或任务正文写入错误日志。原生回调失败不终止 Codex；测试命令失败会返回非零退出码。

## 验证

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖 HTML 标签及特殊字符转义、段落保留、表格与代码块过滤、摘要截断、会话改名和数据库兼容、UTF-8、Telegram 请求、原回调转发、TOML 保留与备份、重复安装、Windows 隐藏窗口和原生命令行/标准输入。所有测试使用模拟 Telegram 响应，不发送真实消息。

本次实际验证：Windows / Python 3.12.3 与 Linux（WSL）/ Python 3.14.4 各 36 项测试通过；Windows 已另行完成真实 HTML 通知发送，旧 PowerShell 入口此前也已验证。Linux 尚未验证联网发送，macOS 尚未实机验证。

附带 GitHub Actions 的 Windows / macOS / Linux 与 Python 3.11 / 3.13 测试矩阵；把本目录作为仓库根目录后可运行。附带配置不代表已在远端执行。

原生 `notify` 当前处理 `agent-turn-complete`，不覆盖崩溃、卡死和所有审批等待，也不是普通 ChatGPT 网页聊天的通用监听器。

官方依据：[Codex 高级配置的 Notifications](https://developers.openai.com/codex/config-advanced/#notifications)。

排版依据：[Telegram Bot API 的 HTML 模式](https://core.telegram.org/bots/api#html-style)。
