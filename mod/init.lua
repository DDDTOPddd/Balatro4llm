-- Entry point for the balatro4llm Lua Mod.
-- Hooked into main.lua via Lovely (love.load / love.update / love.quit).

local server = require("balatro4llm_server")
local state_mod = require("balatro4llm_state")
local actions_mod = require("balatro4llm_actions")

local M = {
    VERSION = "0.5.0",
    _initialized = false,
}

local function lookup_enum_name(enum_tbl, value)
    if type(enum_tbl) ~= "table" or value == nil then
        return nil
    end
    for k, v in pairs(enum_tbl) do
        if v == value then
            return k
        end
    end
    return nil
end

local function handle_ping(_args)
    local stage = G and G.STAGE or nil
    local state = G and G.STATE or nil
    return {
        pong = true,
        mod_version = M.VERSION,
        game_version = G and G.VERSION or nil,
        stage = stage,
        stage_name = lookup_enum_name(G and G.STAGES, stage),
        state = state,
        state_name = lookup_enum_name(G and G.STATES, state),
        state_complete = (G and G.STATE_COMPLETE) and true or false,
        paused = (G and G.SETTINGS and G.SETTINGS.paused) and true or false,
        uptime = (G and G.TIMERS and G.TIMERS.UPTIME) or 0,
        fps = (love and love.timer and love.timer.getFPS) and love.timer.getFPS() or nil,
    }
end

local COMMANDS = {
    ping = handle_ping,
    state = state_mod.get_state,
    action = actions_mod.dispatch,
}

local function dispatch(cmd, args, _req)
    local fn = COMMANDS[cmd]
    if not fn then
        return nil, "unknown command: " .. tostring(cmd)
    end
    return fn(args)
end

function M.init()
    if M._initialized then
        return
    end
    M._initialized = true
    local ok, err = pcall(server.start, dispatch)
    if not ok then
        print("[balatro4llm] ERROR during init: " .. tostring(err))
    end
end

function M.update(dt)
    if not M._initialized then
        return
    end
    local ok, err = pcall(server.update, dt)
    if not ok then
        print("[balatro4llm] ERROR during update: " .. tostring(err))
    end
end

function M.quit()
    if not M._initialized then
        return
    end
    pcall(server.stop)
    M._initialized = false
end

return M
