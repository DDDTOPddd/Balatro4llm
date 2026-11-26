-- Non-blocking NDJSON-over-TCP server polled from love.update().
-- Uses LÖVE2D's bundled LuaSocket with settimeout(0) on both listener and clients.

local socket = require("socket")
local json = require("balatro4llm_json")

local M = {
    HOST = os.getenv("BALATRO4LLM_HOST") or "127.0.0.1",
    PORT = tonumber(os.getenv("BALATRO4LLM_PORT")) or 12345,
    MAX_CLIENTS = 8,
    MAX_RX_BYTES = 1024 * 1024,
    _server = nil,
    _clients = {},
    _handler = nil,
}

local function close_client(entry)
    if entry and entry.sock then
        pcall(function() entry.sock:close() end)
        entry.sock = nil
    end
end

function M.start(handler)
    if M._server then
        M.stop()
    end
    M._handler = handler

    local srv, err = socket.tcp()
    if not srv then
        print("[balatro4llm] ERROR socket.tcp() failed: " .. tostring(err))
        return false, err
    end

    pcall(function() srv:setoption("reuseaddr", true) end)

    local ok, bind_err = srv:bind(M.HOST, M.PORT)
    if not ok then
        print(string.format("[balatro4llm] ERROR bind(%s:%d) failed: %s", M.HOST, M.PORT, tostring(bind_err)))
        pcall(function() srv:close() end)
        return false, bind_err
    end

    local listen_ok, listen_err = srv:listen(16)
    if not listen_ok then
        print("[balatro4llm] ERROR listen() failed: " .. tostring(listen_err))
        pcall(function() srv:close() end)
        return false, listen_err
    end

    srv:settimeout(0)
    M._server = srv
    M._clients = {}
    print(string.format("[balatro4llm] Listening on %s:%d (NDJSON/TCP)", M.HOST, M.PORT))
    return true
end

function M.stop()
    for i = #M._clients, 1, -1 do
        close_client(M._clients[i])
        table.remove(M._clients, i)
    end
    if M._server then
        pcall(function() M._server:close() end)
        M._server = nil
        print("[balatro4llm] Server stopped")
    end
end

local function handle_line(line)
    local dec_ok, req = pcall(json.decode, line)
    if not dec_ok or type(req) ~= "table" then
        return {
            ok = false,
            error = "invalid JSON request: " .. tostring(req),
        }
    end

    local cmd = req.cmd
    local req_id = req.id
    if type(cmd) ~= "string" or cmd == "" then
        return {
            ok = false,
            id = req_id,
            error = "missing or invalid 'cmd' field",
        }
    end

    if not M._handler then
        return {
            ok = false,
            id = req_id,
            cmd = cmd,
            error = "no command handler registered",
        }
    end

    local call_ok, result, call_err = pcall(M._handler, cmd, req.args or {}, req)
    if not call_ok then
        return {
            ok = false,
            id = req_id,
            cmd = cmd,
            error = "internal handler error: " .. tostring(result),
        }
    end

    if result == nil and call_err ~= nil then
        return {
            ok = false,
            id = req_id,
            cmd = cmd,
            error = tostring(call_err),
        }
    end

    return {
        ok = true,
        id = req_id,
        cmd = cmd,
        data = result,
    }
end

local function queue_response(entry, resp)
    local enc_ok, encoded = pcall(json.encode, resp)
    if not enc_ok then
        encoded = '{"ok":false,"error":"failed to encode JSON response"}'
    end
    entry.tx_buf = entry.tx_buf .. encoded .. "\n"
end

local function accept_new_clients()
    for _ = 1, M.MAX_CLIENTS do
        local client, err = M._server:accept()
        if not client then
            break
        end
        if #M._clients >= M.MAX_CLIENTS then
            pcall(function() client:close() end)
        else
            client:settimeout(0)
            pcall(function() client:setoption("tcp-nodelay", true) end)
            M._clients[#M._clients + 1] = {
                sock = client,
                rx_buf = "",
                tx_buf = "",
                peer_closed = false,
            }
        end
    end
end

local function service_client(entry)
    -- 1. Non-blocking read into rx_buf
    if not entry.peer_closed then
        for _ = 1, 16 do
            local chunk, err, partial = entry.sock:receive(8192)
            local data = chunk or partial
            if data and #data > 0 then
                entry.rx_buf = entry.rx_buf .. data
                if #entry.rx_buf > M.MAX_RX_BYTES then
                    queue_response(entry, { ok = false, error = "request line exceeded max size" })
                    entry.rx_buf = ""
                    entry.peer_closed = true
                    break
                end
            end
            if err == "closed" then
                entry.peer_closed = true
                break
            elseif err == "timeout" then
                break
            elseif err ~= nil then
                entry.peer_closed = true
                break
            end
        end
    end

    -- 2. Process all complete newline-delimited JSON messages
    while true do
        local nl = entry.rx_buf:find("\n", 1, true)
        if not nl then
            break
        end
        local line = entry.rx_buf:sub(1, nl - 1)
        entry.rx_buf = entry.rx_buf:sub(nl + 1)
        if line:sub(-1) == "\r" then
            line = line:sub(1, -2)
        end
        if line:match("%S") then
            local resp = handle_line(line)
            queue_response(entry, resp)
        end
    end

    -- 3. Non-blocking flush of tx_buf
    if #entry.tx_buf > 0 then
        local sent, err, last = entry.sock:send(entry.tx_buf)
        if sent then
            if sent >= #entry.tx_buf then
                entry.tx_buf = ""
            else
                entry.tx_buf = entry.tx_buf:sub(sent + 1)
            end
        elseif err == "timeout" then
            if last and last > 0 then
                entry.tx_buf = entry.tx_buf:sub(last + 1)
            end
        else
            -- closed or fatal write error
            return false
        end
    end

    -- 4. Drop client once peer closed and response fully flushed
    if entry.peer_closed and #entry.tx_buf == 0 then
        return false
    end
    return true
end

function M.update(dt)
    if not M._server then
        return
    end
    accept_new_clients()
    for i = #M._clients, 1, -1 do
        local entry = M._clients[i]
        local alive_ok, keep_alive = pcall(service_client, entry)
        if not alive_ok or not keep_alive then
            close_client(entry)
            table.remove(M._clients, i)
        end
    end
end

return M
