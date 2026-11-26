# MCP 接入指南

用 MCP 模式玩《小丑牌》，就是让 Agent 后台常驻一个 `balatro-mcp` 进程，通过 TCP 长连接直接读写游戏状态：
- **更快**：省掉每次开终端、起 Python 的冷启动，读一次状态从 ~230ms 降到 **~8ms**；
- **更省心**：不用给 Agent 放开 Shell 权限，也不会遇到 Windows 终端编码/转义坑；
- **更省钱**：只暴露 4 个极简工具（Schema 总计约 400 tokens），和 CLI 共用同一套指令语法。

---

## 第一步：安装 MCP 依赖（只需一次）

在仓库根目录执行：

```powershell
pip install -e ".[mcp]"
```

执行 `balatro-mcp --help` 能正常打印帮助就说明装好了。（CLI 本身依然零第三方依赖，不受影响。）

> 小提示：在 Windows 上运行 `where.exe balatro-mcp` 可以看到它的绝对路径（例如 `E:\anaconda3\Scripts\balatro-mcp.exe`）。后面填配置时**建议填绝对路径**，避免客户端后台拉起进程时找不到 PATH。

---

## 第二步：接入你的 Agent 平台

### 推荐方式：通过「插件（Plugin）」拉起 MCP（优先推荐）

**强烈优先用插件方式接入**，而不是直接塞进全局配置：
- **随时开关**：不打牌时在插件面板一键关掉，MCP 进程和打牌技能同步下线，平时写代码**零上下文占用**；
- **打包省事**：把 MCP 服务和打牌攻略（`SKILL.md`）绑在一起，开局直接就能打。

#### 1. Antigravity（反重力）插件配置
在 `~/.gemini/config/plugins/balatro4llm/` 放 3 个文件（目录名即为插件 ID，自动识别，无需手动改 `config.json`）：

```text
~/.gemini/config/plugins/balatro4llm/
├── plugin.json
├── mcp_config.json
└── skills/balatro4llm/SKILL.md   # 直接复制仓库根目录的 SKILL.md
```

- `plugin.json`：
```json
{
  "name": "balatro4llm",
  "displayName": "Balatro4llm",
  "version": "0.8.0",
  "description": "Zero-vision MCP bridge and strategy guide for playing Balatro autonomously."
}
```

- `mcp_config.json`（把路径换成你本机 `where.exe balatro-mcp` 的结果）：
```json
{
  "mcpServers": {
    "balatro4llm": {
      "command": "E:\\anaconda3\\Scripts\\balatro-mcp.exe",
      "args": []
    }
  }
}
```

配好后在反重力的 **Customizations / Plugins** 页面即可一键开关。

#### 2. 其他 Agent 平台（DeepSeek Harness / Claude Code / Cursor 等）
只要平台支持插件、扩展或工作区级 MCP 开关，都建议按同样思路做成**独立可开关的插件/扩展项**（入口命令填 `balatro-mcp` 或其绝对路径，配合仓库里的 `SKILL.md` 一起启用）。

---

### 备选方式：直接写入通用 MCP 配置

如果所用客户端不支持插件分组，直接在客户端的 MCP 配置文件里加上这一段即可（默认 `stdio` 模式，客户端会自动拉起和关闭进程）：

```json
{
  "mcpServers": {
    "balatro": {
      "command": "E:\\anaconda3\\Scripts\\balatro-mcp.exe",
      "args": []
    }
  }
}
```

> 如果需要在多个客户端之间共享同一个服务，或者远程调试，也可以手动启动 HTTP 模式：
> ```powershell
> balatro-mcp --transport streamable-http --mcp-host 127.0.0.1 --mcp-port 8765
> ```
> 然后在客户端 MCP 配置中填写 `"url": "http://127.0.0.1:8765/mcp"`。

---

## 接入后 Agent 能用到什么？

| 类型 | 名称 | 干嘛用的 |
|---|---|---|
| 工具 | `balatro_ping` | 检查游戏连没连上、Mod 版本、当前倍速和延迟 |
| 工具 | `balatro_state` | 看当前局面（默认精简英文、单行小丑、剩余牌库、下个盲注预览、可执行动作） |
| 工具 | `balatro_act` | 执行单条指令，语法和 CLI 完全一样（如 `"play 1 2 3 4 5"`、`"buy 2 --use"`、`"next-round --select"`） |
| 工具 | `balatro_batch` | 连续执行多条确定性指令（如 `["move-joker 2 5", "play 1 2 3 4 5"]`），出错立刻停并返回现场 |
| 资源 | `balatro://state` | 只读当前精简局面 |
| 资源 | `balatro://guide` | 完整打牌指南与指令表（即仓库里的 `SKILL.md`） |

---

## 常见坑（3 条速查）

1. **提示连不上 `127.0.0.1:12345`**：确认 Steam 里的《小丑牌》已启动，且 Lovely 控制台打印了 `[balatro4llm] Listening on 127.0.0.1:12345`。**游戏重启后不用重启 MCP**，下次调用会自动重连。
2. **客户端报错找不到 `balatro-mcp`**：不要只写 `"balatro-mcp"`，改成 `where.exe balatro-mcp` 查出来的完整路径（或者用 `python.exe` + `["-m", "balatro4llm.mcp"]`）。
3. **改了默认端口**：给游戏和 MCP 两边配同一个环境变量 `BALATRO4LLM_PORT`（或启动参数 `--port`）即可。
