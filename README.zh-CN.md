# Balatro4llm

[English](README.md) | **简体中文**

一个**零视觉截图、零模拟键鼠**的游戏桥接器，让 AI Agent（DeepSeek Harness、Codex、Antigravity 及各类 MCP 客户端）能够通过游戏内 **Lua Mod（Lovely）** + 解耦的 **Python Core / CLI / MCP** 原生自主游玩《小丑牌》（**Balatro**）。

## 架构概览

```text
Balatro (LÖVE2D + Lovely 0.10+)
  └── mod/ (balatro4llm Lua Mod)
        ├── lovely.toml    # 注入 main.lua (love.load / love.update / love.quit)
        ├── server.lua     # 监听 127.0.0.1:12345 的非阻塞 LuaSocket NDJSON/TCP 服务
        ├── state.lua      # 只读内存状态、剩余牌组构成与精简统计信息
        ├── actions.lua    # 原子化的内部 G.FUNCS.* 回调执行器
        └── json.lua       # 纯 Lua 5.1/LuaJIT JSON 编解码器
                ▲
                │  NDJSON over TCP (127.0.0.1:12345)
                ▼
Python Layer (balatro4llm/)
  ├── core/                # 零依赖核心层（错误定义、动作注册、长连接 TCP 客户端、状态格式化）
  ├── cli/                 # 轻量 CLI 入口（`balatro-cli` / `python -m balatro4llm ...`，零额外依赖）
  └── mcp/                 # 可选 MCP Server（`balatro-mcp` / `python -m balatro4llm.mcp`，通过 `.[mcp]` 安装）
```

## 核心特性

- **无视觉 / 无截图 / 无模拟点击**：直接读取 Balatro 实时 Lua 内存状态（`G.*`）并调用经过验证的内部游戏回调（`G.FUNCS.*`）。
- **源码级校验**：所有状态字段与回调函数均对照从 `Balatro.exe` 解包出的 Lua 源码（`reference/balatro_src/`，已加入 `.gitignore`）逐一核验。
- **非阻塞通信**：基于 LÖVE2D 内置 `socket` 配合 `settimeout(0)` 在 `love.update(dt)` 中轮询，保持满帧运行且 TCP 往返延迟约 10 ms。
- **动作后稳定等待**：`BalatroClient.wait_until_stable()` 会等待阻塞动画队列（`G.E_MANAGER.queues.base`）、控制器锁（`G.CONTROLLER.locks`）以及界面就绪检查全部完成后再返回最新状态。
- **低 Token、高速度、省轮次（且不做任何作弊）**：支持查看牌堆剩余构成（`Deck Left`）、`--compact` 单行紧凑输出（持有小丑 / 消耗牌 / 生效标签 / 精简 `Actions:`）、小丑与牌型实时计数（`Supernova`、`Obelisk`、`Card Sharp`、`Upgraded Hands` `xN`）、商店下一盲注与 Boss 预览、`next-round --select|--skip`、精确商店购买状态标签（`[no $]` / `[slots full]` / `[slots full; --use OK]`）、`set-speed 0.5..16`（含 `ROUND_EVAL` 极速结算）、`move-joker`/`move-hand` 单张调序、`--auto-cash-out` / `--auto-advance`、原生 UTF-8 CLI 输出以及确定性 `batch` 批处理——所有战术与算分决策 100% 交由 LLM 自主完成。

## 快速开始（Windows）

### 1. 安装 Lovely Injector（v0.10+）
1. 前往 [ethangreen-dev/lovely-injector Releases](https://github.com/ethangreen-dev/lovely-injector/releases) 下载 `lovely-x86_64-pc-windows-msvc.zip`。
2. 将压缩包中的 **`winmm.dll`**（0.10 以下旧版本为 `version.dll`）解压到你的 Steam Balatro 游戏目录（例如 `E:\SteamLibrary\steamapps\common\Balatro\`）。

### 2. （可选）解包 Balatro Lua 源码供参考
```powershell
python scripts\extract_source.py
```
该脚本会将 `Balatro.exe` 中的所有 `.lua` 文件提取至 `reference/balatro_src/`（已加入 `.gitignore`）。

### 3. 部署 Lua Mod
```powershell
python scripts\install_mod.py
```
将 `mod/` 目录完整安装至 `%AppData%\Balatro\Mods\balatro4llm`。

### 4. 启动 Balatro 并验证连通性
通过 Steam 启动 Balatro，确认 Lovely 控制台输出以下日志：
```text
[balatro4llm] Listening on 127.0.0.1:12345 (NDJSON/TCP)
```
随后在终端测试（CLI 无需任何第三方依赖）：
```powershell
python -m balatro4llm ping
python -m balatro4llm --compact state
```

### 5. （可选）作为常驻 MCP Server 启动
安装可选的 `mcp` SDK 依赖后，即可通过 `stdio`（或 `streamable-http`）暴露 4 个精简工具（`balatro_ping`、`balatro_state`、`balatro_act`、`balatro_batch`）并复用长连接 TCP：
```powershell
pip install -e ".[mcp]"
balatro-mcp --help
```
DeepSeek Harness、Antigravity、Cursor 及 Claude Desktop 的具体 MCP 配置请参见 [docs/mcp-setup.md](docs/mcp-setup.md)。

## CLI 用法示例

```powershell
# 推荐 AI Agent 使用的全局参数（或设置环境变量 BALATRO4LLM_COMPACT=1, BALATRO4LLM_AUTO_CASH_OUT=1, BALATRO4LLM_AUTO_ADVANCE=1）
python -m balatro4llm --compact --auto-advance state

# 加速游戏内动画（0.5/1/2/4 会写入设置；8/16 为仅本次运行生效的极速模式；>=4x 同时加速结算）
python -m balatro4llm set-speed 8

# 开局、继续与局后导航（`--stake` 支持 1..8、`max` 或注数名称如 `green` / `绿注`）
python -m balatro4llm start --deck b_red --stake max # 别名: new-run
python -m balatro4llm continue
python -m balatro4llm endless                        # 在 Ante 8 通关结算页进入无尽模式
python -m balatro4llm main-menu                      # 返回主菜单

# 盲注选择
python -m balatro4llm select-blind
python -m balatro4llm skip-blind
python -m balatro4llm reroll-boss

# 出牌回合（1-based 手牌索引）
python -m balatro4llm sort-hand suit
python -m balatro4llm discard 2 4 7
python -m balatro4llm --compact --auto-cash-out play 1 3 5 6 8
python -m balatro4llm cash-out

# 商店与补充包
python -m balatro4llm buy 1
python -m balatro4llm buy 2 --use
python -m balatro4llm buy-voucher 1
python -m balatro4llm buy-pack 1
python -m balatro4llm pick 2 1 3
python -m balatro4llm skip-pack
python -m balatro4llm reroll
python -m balatro4llm next-round
python -m balatro4llm next-round --select   # 离开商店并直接进入下一盲注
python -m balatro4llm next-round --skip     # 离开商店并跳过下一小/大盲注

# 物品栏、调序与确定性批处理
python -m balatro4llm use 1 2 5
python -m balatro4llm sell-joker 2
python -m balatro4llm sell-consumable 1
python -m balatro4llm move-joker 1 5
python -m balatro4llm move-hand 1 2
python -m balatro4llm reorder-jokers 1 2 4 3
python -m balatro4llm --compact --auto-advance batch "move-joker 2 5" "play 1 2 3 4 5"

# 输出原始 JSON 供脚本 / MCP 使用
python -m balatro4llm --json state
```

完整的 AI Agent 操作规范与高注策略请参见 [SKILL.md](SKILL.md)。

## 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
