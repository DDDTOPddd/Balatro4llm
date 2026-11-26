# 小丑牌 MCP 桥接（DSH 插件）

把仓库里的 `balatro-mcp` 以 **stdio MCP 服务器** 的形式挂进 DeepSeek Harness：插件挂载时拉起进程并注册工具，在「插件」里关掉插件就同步下线工具和上下文占用。

## 前置条件

1. 已安装 MCP 依赖（仓库根目录执行一次）：

   ```powershell
   pip install -e ".[mcp]"
   ```

2. `balatro-mcp` 可用。插件里写的是绝对路径 `E:\anaconda3\Scripts\balatro-mcp.exe`；如果你的安装位置不同，用 `where.exe balatro-mcp` 查出真实路径，改 `cordis.patch.yml` 里的 `command`。
3. 《小丑牌》已启动，且 Lovely 控制台打印了 `[balatro4llm] Listening on 127.0.0.1:12345`。游戏重启后不用重装插件，下一次调用会自动重连。

## 接入后 Agent 拿到的能力

| 类型 | 名称 | 用途 |
|---|---|---|
| 工具 | `mcp__balatro__balatro_ping` | 检查游戏连接、Mod 版本、倍速与延迟 |
| 工具 | `mcp__balatro__balatro_state` | 读取当前局面 |
| 工具 | `mcp__balatro__balatro_act` | 执行单条指令，语法与 CLI 一致 |
| 工具 | `mcp__balatro__balatro_batch` | 执行一组确定性指令，出错即停 |
| 资源 | `balatro://state` | 只读当前局面 |
| 资源 | `balatro://guide` | 完整打牌指南（仓库根目录的 `SKILL.md`） |

## 修改与重装

- 配置在 `cordis.patch.yml`：`serverName`（决定工具名前缀）、`command`、`args`，以及 `failOnStartupError`。若要换成 HTTP 模式，改成 `transport: streamable-http` + `url: http://127.0.0.1:8765/mcp`，并手动启动 `balatro-mcp --transport streamable-http --mcp-port 8765`。
- 本目录是被插件管理器**链接**安装的，改完文件后在该插件的检查/重装入口重新加载即可，不需要拷贝。
- 关掉插件（Plugins 面板）即可完全停止 `balatro-mcp` 进程。

## 排查

- `未找到 balatro-mcp`：`command` 要写 `where.exe balatro-mcp` 的绝对路径。
- 提示连不上 `127.0.0.1:12345`：游戏没开，或 Mod 没加载；游戏开着时重启 Harness 侧连接即可。
- 改过默认端口：给插件行加 `env: { BALATRO4LLM_PORT: '12346' }`，同时游戏侧用同一个端口。
