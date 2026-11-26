-- Minimal, pure-Lua 5.1/LuaJIT JSON encoder and decoder for balatro4llm.
-- Supports explicit empty arrays via json.array(tbl) and guards NaN/Inf/cycles.

local M = {}

local ARRAY_MT = { __balatro4llm_array = true }

function M.array(tbl)
    tbl = tbl or {}
    return setmetatable(tbl, ARRAY_MT)
end

local escape_map = {
    ['"'] = '\\"',
    ['\\'] = '\\\\',
    ['\b'] = '\\b',
    ['\f'] = '\\f',
    ['\n'] = '\\n',
    ['\r'] = '\\r',
    ['\t'] = '\\t',
}

local function escape_char(c)
    return escape_map[c] or string.format("\\u%04x", string.byte(c))
end

local function encode_string(s)
    return '"' .. s:gsub('[%z\1-\31\\"]', escape_char) .. '"'
end

local function is_array(t)
    if getmetatable(t) == ARRAY_MT then
        return true, #t
    end
    local count = 0
    local max_idx = 0
    for k, _ in pairs(t) do
        if type(k) ~= "number" or k <= 0 or math.floor(k) ~= k then
            return false, 0
        end
        count = count + 1
        if k > max_idx then
            max_idx = k
        end
    end
    if count == 0 then
        return false, 0
    end
    return count == max_idx, max_idx
end

local function encode_value(val, seen, depth)
    local t = type(val)
    if t == "nil" then
        return "null"
    elseif t == "boolean" then
        return val and "true" or "false"
    elseif t == "number" then
        if val ~= val or val == math.huge or val == -math.huge then
            return "null"
        end
        if math.floor(val) == val and math.abs(val) < 9007199254740992 then
            return string.format("%.0f", val)
        end
        return string.format("%.14g", val)
    elseif t == "string" then
        return encode_string(val)
    elseif t == "table" then
        if depth > 32 or seen[val] then
            return "null"
        end
        seen[val] = true
        local arr, n = is_array(val)
        local parts = {}
        if arr then
            for i = 1, n do
                parts[i] = encode_value(val[i], seen, depth + 1)
            end
            seen[val] = nil
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local idx = 0
            for k, v in pairs(val) do
                if v ~= nil and type(v) ~= "function" and type(v) ~= "userdata" and type(v) ~= "thread" then
                    idx = idx + 1
                    parts[idx] = encode_string(tostring(k)) .. ":" .. encode_value(v, seen, depth + 1)
                end
            end
            seen[val] = nil
            return "{" .. table.concat(parts, ",") .. "}"
        end
    else
        return "null"
    end
end

function M.encode(val)
    return encode_value(val, {}, 0)
end

-- Decoder (RFC 8259)

local function codepoint_to_utf8(n)
    if n <= 0x7F then
        return string.char(n)
    elseif n <= 0x7FF then
        return string.char(
            0xC0 + math.floor(n / 0x40),
            0x80 + (n % 0x40)
        )
    elseif n <= 0xFFFF then
        return string.char(
            0xE0 + math.floor(n / 0x1000),
            0x80 + (math.floor(n / 0x40) % 0x40),
            0x80 + (n % 0x40)
        )
    elseif n <= 0x10FFFF then
        return string.char(
            0xF0 + math.floor(n / 0x40000),
            0x80 + (math.floor(n / 0x1000) % 0x40),
            0x80 + (math.floor(n / 0x40) % 0x40),
            0x80 + (n % 0x40)
        )
    end
    error("invalid unicode codepoint: " .. tostring(n))
end

local unescape_map = {
    ['"'] = '"',
    ['\\'] = '\\',
    ['/'] = '/',
    ['b'] = '\b',
    ['f'] = '\f',
    ['n'] = '\n',
    ['r'] = '\r',
    ['t'] = '\t',
}

local function skip_ws(str, pos)
    local _, e = str:find("^[ \t\r\n]*", pos)
    return (e or pos - 1) + 1
end

local parse_value

local function parse_string(str, pos)
    pos = pos + 1 -- skip opening quote
    local res = {}
    local len = #str
    local chunk_start = pos
    while pos <= len do
        local b = str:byte(pos)
        if b == 34 then -- '"'
            res[#res + 1] = str:sub(chunk_start, pos - 1)
            return table.concat(res), pos + 1
        elseif b == 92 then -- '\'
            res[#res + 1] = str:sub(chunk_start, pos - 1)
            local esc = str:sub(pos + 1, pos + 1)
            if esc == "" then
                error("unterminated escape sequence at pos " .. pos)
            elseif unescape_map[esc] then
                res[#res + 1] = unescape_map[esc]
                pos = pos + 2
            elseif esc == "u" then
                local hex = str:sub(pos + 2, pos + 5)
                if not hex:match("^[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]$") then
                    error("invalid unicode escape at pos " .. pos)
                end
                local cp = tonumber(hex, 16)
                pos = pos + 6
                if cp >= 0xD800 and cp <= 0xDBFF and str:sub(pos, pos + 1) == "\\u" then
                    local hex2 = str:sub(pos + 2, pos + 5)
                    local cp2 = tonumber(hex2, 16)
                    if cp2 and cp2 >= 0xDC00 and cp2 <= 0xDFFF then
                        cp = 0x10000 + (cp - 0xD800) * 0x400 + (cp2 - 0xDC00)
                        pos = pos + 6
                    end
                end
                res[#res + 1] = codepoint_to_utf8(cp)
            else
                error("invalid escape character '" .. esc .. "' at pos " .. pos)
            end
            chunk_start = pos
        elseif b < 32 then
            error("unescaped control character in string at pos " .. pos)
        else
            pos = pos + 1
        end
    end
    error("unterminated string")
end

local function parse_number(str, pos)
    local s, e = str:find("^-?%d+%.?%d*[eE]?[+-]?%d*", pos)
    if not s then
        error("invalid number at pos " .. pos)
    end
    local num_str = str:sub(s, e)
    local num = tonumber(num_str)
    if not num then
        error("invalid number '" .. num_str .. "' at pos " .. pos)
    end
    return num, e + 1
end

local function parse_array(str, pos)
    pos = skip_ws(str, pos + 1)
    local arr = {}
    if str:sub(pos, pos) == "]" then
        return arr, pos + 1
    end
    local idx = 1
    while true do
        local val
        val, pos = parse_value(str, pos)
        arr[idx] = val
        idx = idx + 1
        pos = skip_ws(str, pos)
        local c = str:sub(pos, pos)
        if c == "]" then
            return arr, pos + 1
        elseif c == "," then
            pos = skip_ws(str, pos + 1)
        else
            error("expected ',' or ']' in array at pos " .. pos)
        end
    end
end

local function parse_object(str, pos)
    pos = skip_ws(str, pos + 1)
    local obj = {}
    if str:sub(pos, pos) == "}" then
        return obj, pos + 1
    end
    while true do
        if str:sub(pos, pos) ~= '"' then
            error("expected string key in object at pos " .. pos)
        end
        local key
        key, pos = parse_string(str, pos)
        pos = skip_ws(str, pos)
        if str:sub(pos, pos) ~= ":" then
            error("expected ':' after object key at pos " .. pos)
        end
        pos = skip_ws(str, pos + 1)
        local val
        val, pos = parse_value(str, pos)
        obj[key] = val
        pos = skip_ws(str, pos)
        local c = str:sub(pos, pos)
        if c == "}" then
            return obj, pos + 1
        elseif c == "," then
            pos = skip_ws(str, pos + 1)
        else
            error("expected ',' or '}' in object at pos " .. pos)
        end
    end
end

parse_value = function(str, pos)
    pos = skip_ws(str, pos)
    local c = str:sub(pos, pos)
    if c == "" then
        error("unexpected end of JSON input")
    elseif c == '"' then
        return parse_string(str, pos)
    elseif c == "{" then
        return parse_object(str, pos)
    elseif c == "[" then
        return parse_array(str, pos)
    elseif c == "t" then
        if str:sub(pos, pos + 3) == "true" then
            return true, pos + 4
        end
        error("invalid literal at pos " .. pos)
    elseif c == "f" then
        if str:sub(pos, pos + 4) == "false" then
            return false, pos + 5
        end
        error("invalid literal at pos " .. pos)
    elseif c == "n" then
        if str:sub(pos, pos + 3) == "null" then
            return nil, pos + 4
        end
        error("invalid literal at pos " .. pos)
    elseif c == "-" or (c >= "0" and c <= "9") then
        return parse_number(str, pos)
    else
        error("unexpected character '" .. c .. "' at pos " .. pos)
    end
end

function M.decode(str)
    if type(str) ~= "string" then
        error("expected string for json.decode")
    end
    local val, pos = parse_value(str, 1)
    pos = skip_ws(str, pos)
    if pos <= #str then
        error("trailing garbage at pos " .. pos)
    end
    return val
end

return M
