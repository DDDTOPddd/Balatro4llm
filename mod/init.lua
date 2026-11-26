-- Entry point for the balatro4llm Lua Mod.
-- Hooked into main.lua via Lovely (love.load / love.update / love.quit).

local server = require("balatro4llm_server")
local state_mod = require("balatro4llm_state")
local actions_mod = require("balatro4llm_actions")

local M = {
    VERSION = "0.8.0",
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
        gamespeed = (G and G.SETTINGS and G.SETTINGS.GAMESPEED) or 1,
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

-- Pure animation-speed accelerator for fast settlement (ROUND_EVAL at >=4x)
-- and turbo scoring/drawing (HAND_PLAYED / NEW_ROUND / DRAW_TO_HAND at >=8x).
-- Never skips callbacks, never alters RNG order, and stops immediately on pause/overlay.
local function fast_forward_animations(dt)
    if not G or G.STAGE ~= G.STAGES.RUN or not G.SETTINGS or not G.E_MANAGER or not G.TIMERS then
        return
    end
    if G.SETTINGS.paused or G.OVERLAY_MENU or G.screenwipe then
        return
    end
    local spd = G.SETTINGS.GAMESPEED or 1
    if spd < 4 then
        return
    end
    local q = G.E_MANAGER.queues and G.E_MANAGER.queues.base
    if not q or #q == 0 then
        return
    end
    local step_dt = math.min(dt or 0.016, 0.05)

    if G.STATE == G.STATES.ROUND_EVAL then
        local re = G.round_eval
        local ready_to_boost = re and not re.REMOVED and (
            (re.T and re.VT and math.abs(re.T.y - re.VT.y) < 3)
            or (re.alignment and re.alignment.offset and re.alignment.offset.y and re.alignment.offset.y > 0)
        )
        if not ready_to_boost then
            return
        end
        local boost = math.max(spd * 2, 8)
        for _ = 1, 4 do
            if G.STATE ~= G.STATES.ROUND_EVAL or G.SETTINGS.paused or G.OVERLAY_MENU or G.screenwipe then
                break
            end
            q = G.E_MANAGER.queues and G.E_MANAGER.queues.base
            if not q or #q == 0 then
                break
            end
            G.TIMERS.TOTAL = G.TIMERS.TOTAL + step_dt * boost
            G.E_MANAGER:update(0, true)
        end
        return
    end

    if spd >= 8 and (
        G.STATE == G.STATES.HAND_PLAYED
        or G.STATE == G.STATES.NEW_ROUND
        or G.STATE == G.STATES.DRAW_TO_HAND
    ) then
        local extra = (spd >= 16) and 3 or 1
        local boost = spd * 0.5
        for _ = 1, extra do
            if (G.STATE ~= G.STATES.HAND_PLAYED
                and G.STATE ~= G.STATES.NEW_ROUND
                and G.STATE ~= G.STATES.DRAW_TO_HAND)
                or G.SETTINGS.paused or G.OVERLAY_MENU or G.screenwipe then
                break
            end
            q = G.E_MANAGER.queues and G.E_MANAGER.queues.base
            if not q or #q == 0 then
                break
            end
            G.TIMERS.TOTAL = G.TIMERS.TOTAL + step_dt * boost
            G.E_MANAGER:update(0, true)
        end
    end
end

function M.update(dt)
    if not M._initialized then
        return
    end
    pcall(fast_forward_animations, dt)
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
