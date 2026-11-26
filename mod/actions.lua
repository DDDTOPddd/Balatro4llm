-- Atomic in-game action executor for balatro4llm (v0.4.0).
-- Every internal callback & argument shape is verified against Balatro 1.0.1o-FULL Lua source.

local M = {}

local PACK_STATES = {
    [9] = true,  -- TAROT_PACK
    [10] = true, -- PLANET_PACK
    [15] = true, -- SPECTRAL_PACK
    [17] = true, -- STANDARD_PACK
    [18] = true, -- BUFFOON_PACK
}

local function is_pack_state()
    return G and G.STATE and (
        G.STATE == G.STATES.TAROT_PACK
        or G.STATE == G.STATES.PLANET_PACK
        or G.STATE == G.STATES.SPECTRAL_PACK
        or G.STATE == G.STATES.STANDARD_PACK
        or G.STATE == G.STATES.BUFFOON_PACK
        or PACK_STATES[G.STATE]
    )
end

local function is_transient_state()
    return G and G.STATE and (
        G.STATE == G.STATES.HAND_PLAYED
        or G.STATE == G.STATES.DRAW_TO_HAND
        or G.STATE == G.STATES.NEW_ROUND
        or G.STATE == G.STATES.PLAY_TAROT
    )
end

local function require_run_ready(expected_state, expected_name)
    if not G or G.STAGE ~= G.STAGES.RUN then
        return false, "game is not currently in an active run"
    end
    if G.CONTROLLER and G.CONTROLLER.locked then
        return false, "controller is currently locked by an animation/transition"
    end
    if expected_state and G.STATE ~= expected_state then
        return false, string.format("expected state %s (%s), but current G.STATE is %s",
            tostring(expected_name), tostring(expected_state), tostring(G.STATE))
    end
    if not expected_state and is_transient_state() then
        return false, "game is currently in a transient animation state (G.STATE=" .. tostring(G.STATE) .. ")"
    end
    return true
end

local function resolve_deck_center(deck_spec)
    if not deck_spec or deck_spec == "" then
        return nil, nil
    end
    if G.P_CENTERS and G.P_CENTERS[deck_spec] and G.P_CENTERS[deck_spec].set == "Back" then
        return G.P_CENTERS[deck_spec], nil
    end
    local raw = tostring(deck_spec):gsub("^%s+", ""):gsub("%s+$", "")
    local lower = string.lower(raw)
    if G.P_CENTER_POOLS and G.P_CENTER_POOLS.Back then
        for _, back in ipairs(G.P_CENTER_POOLS.Back) do
            local loc_name = nil
            if localize then
                local ok_l, res_l = pcall(localize, { type = "name_text", set = "Back", key = back.key })
                if ok_l and type(res_l) == "string" and res_l ~= "" and res_l ~= "ERROR" then
                    loc_name = res_l
                end
            end
            if string.lower(back.key or "") == lower
                or string.lower(back.name or "") == lower
                or (loc_name and string.lower(loc_name) == lower) then
                return back, nil
            end
        end
    end
    return nil, "unknown deck: " .. tostring(deck_spec)
end

local function get_deck_max_unlocked_stake(deck_key)
    local stake_pool = G.P_CENTER_POOLS and G.P_CENTER_POOLS.Stake or {}
    local n_stakes = #stake_pool > 0 and #stake_pool or 8
    local profile = G.SETTINGS and G.SETTINGS.profile or 1
    if G.PROFILES and G.PROFILES[profile] and G.PROFILES[profile].all_unlocked then
        return n_stakes
    end
    local win_stake = 0
    if deck_key and get_deck_win_stake then
        local ok, w = pcall(get_deck_win_stake, deck_key)
        if ok and type(w) == "number" then
            win_stake = w
        end
    end
    return math.max(1, math.min(win_stake + 1, n_stakes))
end

local function resolve_stake_level(stake_spec, max_unlocked)
    local stake_pool = G.P_CENTER_POOLS and G.P_CENTER_POOLS.Stake or {}
    local n_stakes = #stake_pool > 0 and #stake_pool or 8
    if stake_spec == nil or stake_spec == "" then
        return 1, nil
    end
    local num = tonumber(stake_spec)
    if num ~= nil then
        if math.floor(num) ~= num or num < 1 or num > n_stakes then
            return nil, string.format("stake must be an integer between 1 and %d (or 'max' / stake name)", n_stakes)
        end
        return num, nil
    end

    local raw = tostring(stake_spec):gsub("^%s+", ""):gsub("%s+$", "")
    local lower = string.lower(raw)
    if lower == "max" or lower == "highest" or lower == "hardest" then
        return max_unlocked, nil
    end

    for i, sp in ipairs(stake_pool) do
        local key_l = string.lower(sp.key or "")
        local name_l = string.lower(sp.name or "")
        local short_l = name_l:gsub("%s+stake$", "")
        local loc_l = nil
        if localize then
            local ok_l, res_l = pcall(localize, { type = "name_text", set = "Stake", key = sp.key })
            if ok_l and type(res_l) == "string" and res_l ~= "" and res_l ~= "ERROR" then
                loc_l = string.lower(res_l)
            end
        end
        if lower == key_l or lower == name_l or lower == short_l or (loc_l and lower == loc_l) then
            return i, nil
        end
    end
    return nil, "unknown stake: " .. tostring(stake_spec) .. " (expected 1..8, 'max', or stake name like 'green')"
end

local function validate_hand_indices(raw_indices, min_count, max_count)
    if type(raw_indices) ~= "table" then
        return nil, "cards/indices must be an array of 1-based integers"
    end
    if not G.hand or not G.hand.cards then
        return nil, "G.hand is not available"
    end
    local n_hand = #G.hand.cards
    local seen = {}
    local out = {}
    for _, raw in ipairs(raw_indices) do
        local idx = tonumber(raw)
        if not idx or math.floor(idx) ~= idx then
            return nil, "invalid card index: " .. tostring(raw)
        end
        if idx < 1 or idx > n_hand then
            return nil, string.format("card index %d out of range (1..%d)", idx, n_hand)
        end
        if seen[idx] then
            return nil, "duplicate card index: " .. tostring(idx)
        end
        seen[idx] = true
        out[#out + 1] = idx
    end
    if min_count and #out < min_count then
        return nil, string.format("must select at least %d card(s), got %d", min_count, #out)
    end
    if max_count and #out > max_count then
        return nil, string.format("can select at most %d card(s), got %d", max_count, #out)
    end
    return out, nil
end

local function validate_permutation(raw_order, n)
    if type(raw_order) ~= "table" then
        return nil, "order must be an array of 1-based integers"
    end
    if #raw_order ~= n then
        return nil, string.format("order must contain exactly %d indices (got %d)", n, #raw_order)
    end
    local seen = {}
    local out = {}
    for _, raw in ipairs(raw_order) do
        local idx = tonumber(raw)
        if not idx or math.floor(idx) ~= idx or idx < 1 or idx > n then
            return nil, string.format("invalid index %s in permutation (expected 1..%d)", tostring(raw), n)
        end
        if seen[idx] then
            return nil, "duplicate index in permutation: " .. tostring(idx)
        end
        seen[idx] = true
        out[#out + 1] = idx
    end
    return out, nil
end

local function apply_hand_highlights(indices, enforce_forced_selection)
    if enforce_forced_selection then
        local idx_set = {}
        for _, idx in ipairs(indices) do
            idx_set[idx] = true
        end
        for i, card in ipairs(G.hand.cards) do
            if card.ability and card.ability.forced_selection and not idx_set[i] then
                return false, string.format("card #%d is force-selected by Boss Blind and must be included", i)
            end
        end
    end

    G.hand:unhighlight_all()
    for _, idx in ipairs(indices) do
        local card = G.hand.cards[idx]
        if not card.highlighted then
            G.hand:add_to_highlighted(card, true)
        end
    end
    return true
end

local function find_cash_out_button()
    if not G.I or not G.I.UIBOX then
        return nil
    end
    for _, box in pairs(G.I.UIBOX) do
        if box and not box.REMOVED and box.get_UIE_by_ID then
            local ok, btn = pcall(box.get_UIE_by_ID, box, "cash_out_button")
            if ok and btn and btn.config and btn.config.button == "cash_out" then
                return btn
            end
        end
    end
    return nil
end

-- === Action Handlers ===

local function action_start(args)
    local seed = args.seed
    if seed ~= nil then
        seed = tostring(seed)
        if seed == "" then seed = nil end
    end

    local profile = G.SETTINGS and G.SETTINGS.profile or 1
    local all_unlocked = (G.PROFILES and G.PROFILES[profile] and G.PROFILES[profile].all_unlocked) and true or false

    local center = nil
    if args.deck and args.deck ~= "" then
        local err
        center, err = resolve_deck_center(args.deck)
        if not center then
            return nil, err
        end
        if not center.unlocked and not all_unlocked then
            return nil, "deck is locked: " .. tostring(center.name)
        end
    end

    local active_deck_key = (center and center.key)
        or (G.GAME and G.GAME.selected_back and G.GAME.selected_back.effect and G.GAME.selected_back.effect.center and G.GAME.selected_back.effect.center.key)
        or "b_red"
    local active_deck_name = (center and center.name)
        or (G.GAME and G.GAME.selected_back and G.GAME.selected_back.name)
        or active_deck_key
    local max_unlocked = get_deck_max_unlocked_stake(active_deck_key)

    local stake, stake_err = resolve_stake_level(args.stake, max_unlocked)
    if not stake then
        return nil, stake_err
    end
    if stake > max_unlocked then
        local sp = G.P_CENTER_POOLS and G.P_CENTER_POOLS.Stake and G.P_CENTER_POOLS.Stake[stake]
        local sname = (sp and sp.name) or ("Stake " .. tostring(stake))
        return nil, string.format(
            "stake %d (%s) is locked for deck '%s' (unlocked stakes: 1..%d)",
            stake, sname, tostring(active_deck_name), max_unlocked
        )
    end

    if G.OVERLAY_MENU and G.FUNCS.exit_overlay_menu then
        G.FUNCS.exit_overlay_menu()
    end

    if center then
        G.GAME = G.GAME or {}
        G.GAME.viewed_back = Back(center)
        G.GAME.selected_back = Back(center)
        if G.PROFILES and G.SETTINGS and G.PROFILES[G.SETTINGS.profile] and G.PROFILES[G.SETTINGS.profile].MEMORY then
            G.PROFILES[G.SETTINGS.profile].MEMORY.deck = center.name
        end
    end

    G.FUNCS.start_run(nil, { stake = stake, seed = seed })
    return {
        action = "start",
        deck = active_deck_key,
        stake = stake,
        max_unlocked_stake = max_unlocked,
        seed = seed,
    }
end

local function action_continue(_args)
    if G.STAGE ~= G.STAGES.MAIN_MENU then
        return nil, "continue is only valid from MAIN_MENU"
    end

    if G.SAVED_GAME == nil then
        local profile = G.SETTINGS and G.SETTINGS.profile or 1
        local raw = get_compressed(profile .. "/save.jkr")
        if raw ~= nil then
            G.SAVED_GAME = STR_UNPACK(raw)
        end
    end
    if G.SAVED_GAME == nil then
        return nil, "no saved run found"
    end

    if G.OVERLAY_MENU and G.FUNCS.exit_overlay_menu then
        G.FUNCS.exit_overlay_menu()
    end

    G.FUNCS.start_run(nil, { savetext = G.SAVED_GAME })
    return { action = "continue" }
end

local function action_main_menu(_args)
    if G.STAGE == G.STAGES.MAIN_MENU then
        return { action = "main_menu", already_in_menu = true }
    end
    G.FUNCS.go_to_menu(nil)
    return { action = "main_menu" }
end

local function action_endless(_args)
    if not G or G.STAGE ~= G.STAGES.RUN then
        return nil, "not currently in a run"
    end
    if G.STATE == G.STATES.GAME_OVER then
        return nil, "cannot enter endless mode from GAME_OVER"
    end
    if not G.OVERLAY_MENU then
        return nil, "win overlay is not currently active"
    end
    local is_win = (G.GAME and G.GAME.won) and true or false
    if G.OVERLAY_MENU.get_UIE_by_ID then
        local ok_w, win_ui = pcall(G.OVERLAY_MENU.get_UIE_by_ID, G.OVERLAY_MENU, "you_win_UI")
        if ok_w and win_ui then
            is_win = true
        end
    end
    if not is_win then
        return nil, "current overlay is not the Ante 8 win screen; use dismiss_overlay instead"
    end
    G.FUNCS.exit_overlay_menu()
    return { action = "endless" }
end

local function action_dismiss_overlay(_args)
    if G.OVERLAY_TUTORIAL and G.FUNCS.skip_tutorial_section then
        G.FUNCS.skip_tutorial_section(nil)
        return { action = "dismiss_overlay", kind = "tutorial" }
    end
    if G.OVERLAY_MENU then
        if G.STATE == G.STATES.GAME_OVER then
            return nil, "cannot dismiss GAME_OVER overlay; use 'start' or 'main-menu' instead"
        end
        G.FUNCS.exit_overlay_menu()
        return { action = "dismiss_overlay", kind = "overlay_menu" }
    end
    return nil, "no active overlay menu or tutorial to dismiss"
end

local function action_select_blind(_args)
    local ok, err = require_run_ready(G.STATES.BLIND_SELECT, "BLIND_SELECT")
    if not ok then return nil, err end
    if not G.blind_select or not G.blind_select_opts then
        return nil, "blind select UI is not ready"
    end

    local slot = G.GAME.blind_on_deck
    if not slot then
        return nil, "no blind_on_deck found"
    end
    local opt_box = G.blind_select_opts[string.lower(slot)]
    local btn = opt_box and opt_box:get_UIE_by_ID("select_blind_button") or nil
    if not btn then
        local bkey = G.GAME.round_resets and G.GAME.round_resets.blind_choices and G.GAME.round_resets.blind_choices[slot]
        local bcfg = bkey and G.P_BLINDS and G.P_BLINDS[bkey]
        if not bcfg then
            return nil, "cannot resolve blind config for slot: " .. tostring(slot)
        end
        btn = { config = { ref_table = bcfg } }
    end

    G.FUNCS.select_blind(btn)
    return { action = "select_blind", slot = slot }
end

local function action_skip_blind(_args)
    local ok, err = require_run_ready(G.STATES.BLIND_SELECT, "BLIND_SELECT")
    if not ok then return nil, err end
    if not G.blind_select or not G.blind_select_opts then
        return nil, "blind select UI is not ready"
    end

    local slot = G.GAME.blind_on_deck
    if slot ~= "Small" and slot ~= "Big" then
        return nil, "cannot skip blind slot: " .. tostring(slot) .. " (only Small and Big can be skipped)"
    end

    local opt_box = G.blind_select_opts[string.lower(slot)]
    if not opt_box then
        return nil, "blind select option UIBox missing for slot: " .. tostring(slot)
    end
    local tag_container = opt_box:get_UIE_by_ID("tag_container")
    if not tag_container then
        return nil, "tag_container not found on blind option UIBox"
    end

    G.FUNCS.skip_blind({ UIBox = opt_box })
    return { action = "skip_blind", slot = slot }
end

local function action_reroll_boss(_args)
    local ok, err = require_run_ready(G.STATES.BLIND_SELECT, "BLIND_SELECT")
    if not ok then return nil, err end
    if not G.blind_select_opts or not G.blind_select_opts.boss then
        return nil, "boss blind select option is not ready"
    end
    local uv = G.GAME.used_vouchers or {}
    local has_voucher = uv["v_retcon"] or (uv["v_directors_cut"] and not (G.GAME.round_resets and G.GAME.round_resets.boss_rerolled))
    if not has_voucher then
        return nil, "boss reroll requires Director's Cut (once per Ante) or Retcon voucher"
    end
    local budget = (G.GAME.dollars or 0) - (G.GAME.bankrupt_at or 0)
    if budget < 10 then
        return nil, string.format("insufficient funds for boss reroll: costs $10, budget is $%d", budget)
    end

    G.FUNCS.reroll_boss(nil)
    return { action = "reroll_boss" }
end

local function action_play(args)
    local ok, err = require_run_ready(G.STATES.SELECTING_HAND, "SELECTING_HAND")
    if not ok then return nil, err end
    if G.GAME.blind and G.GAME.blind.block_play then
        return nil, "play is temporarily blocked by blind debuff alert"
    end
    if G.play and G.play.cards and #G.play.cards > 0 then
        return nil, "cards are already being played"
    end

    local limit = (G.hand and G.hand.config and G.hand.config.highlighted_limit) or 5
    local indices, idx_err = validate_hand_indices(args.cards, 1, math.min(5, limit))
    if not indices then return nil, idx_err end

    local h_ok, h_err = apply_hand_highlights(indices, true)
    if not h_ok then return nil, h_err end

    if #G.hand.highlighted <= 0 or #G.hand.highlighted > 5 then
        return nil, "highlighted card count invalid: " .. tostring(#G.hand.highlighted)
    end

    G.FUNCS.play_cards_from_highlighted(nil)
    return { action = "play", count = #indices }
end

local function action_discard(args)
    local ok, err = require_run_ready(G.STATES.SELECTING_HAND, "SELECTING_HAND")
    if not ok then return nil, err end
    if not G.GAME.current_round or (G.GAME.current_round.discards_left or 0) <= 0 then
        return nil, "no discards remaining"
    end

    local limit = (G.hand and G.hand.config and G.hand.config.highlighted_limit) or 5
    local indices, idx_err = validate_hand_indices(args.cards, 1, math.min(5, limit))
    if not indices then return nil, idx_err end

    local h_ok, h_err = apply_hand_highlights(indices, true)
    if not h_ok then return nil, h_err end

    G.FUNCS.discard_cards_from_highlighted(nil, false)
    return { action = "discard", count = #indices }
end

local function action_sort_hand(args)
    local ok, err = require_run_ready(G.STATES.SELECTING_HAND, "SELECTING_HAND")
    if not ok then return nil, err end
    local by = tostring(args.by or "rank")
    if by == "rank" or by == "value" then
        G.FUNCS.sort_hand_value(nil)
        return { action = "sort_hand", by = "rank" }
    elseif by == "suit" then
        G.FUNCS.sort_hand_suit(nil)
        return { action = "sort_hand", by = "suit" }
    end
    return nil, "invalid sort mode '" .. by .. "' (expected 'rank' or 'suit')"
end

local NATIVE_SPEEDS = {
    [0.5] = true,
    [1] = true,
    [2] = true,
    [4] = true,
}

local function action_set_speed(args)
    local speed = tonumber(args.speed)
    if not speed or (speed ~= 0.5 and speed ~= 1 and speed ~= 2 and speed ~= 4 and speed ~= 8 and speed ~= 16) then
        return nil, "invalid speed: expected one of 0.5, 1, 2, 4, 8, 16"
    end
    if not G or not G.SETTINGS then
        return nil, "G.SETTINGS is not initialized"
    end
    local prev = G.SETTINGS.GAMESPEED or 1
    if G.FUNCS and G.FUNCS.change_gamespeed then
        G.FUNCS.change_gamespeed({ to_val = speed })
    else
        G.SETTINGS.GAMESPEED = speed
    end
    -- Only persist native Options-menu values (0.5/1/2/4) to settings.jkr so UI_definitions.lua:2302 stays in-bounds.
    if NATIVE_SPEEDS[speed] and G.save_settings then
        pcall(G.save_settings, G)
    end
    return {
        action = "set_speed",
        previous_speed = prev,
        speed = G.SETTINGS.GAMESPEED,
        persisted = NATIVE_SPEEDS[speed] and true or false,
    }
end

local function action_move_joker(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not G.jokers or not G.jokers.cards or #G.jokers.cards < 2 then
        return nil, "need at least 2 jokers to move"
    end
    local n = #G.jokers.cards
    local from_idx = tonumber(args.from)
    local to_idx = tonumber(args.to)
    if not from_idx or math.floor(from_idx) ~= from_idx or from_idx < 1 or from_idx > n then
        return nil, string.format("invalid 'from' index %s (expected 1..%d)", tostring(args.from), n)
    end
    if not to_idx or math.floor(to_idx) ~= to_idx or to_idx < 1 or to_idx > n then
        return nil, string.format("invalid 'to' index %s (expected 1..%d)", tostring(args.to), n)
    end
    if from_idx ~= to_idx then
        local card = table.remove(G.jokers.cards, from_idx)
        table.insert(G.jokers.cards, to_idx, card)
        G.jokers:align_cards()
        G.jokers:set_ranks()
        play_sound("cardSlide1")
    end
    return { action = "move_joker", from = from_idx, to = to_idx }
end

local function action_move_hand(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not G.hand or not G.hand.cards or #G.hand.cards < 2 then
        return nil, "need at least 2 hand cards to move"
    end
    local n = #G.hand.cards
    local from_idx = tonumber(args.from)
    local to_idx = tonumber(args.to)
    if not from_idx or math.floor(from_idx) ~= from_idx or from_idx < 1 or from_idx > n then
        return nil, string.format("invalid 'from' index %s (expected 1..%d)", tostring(args.from), n)
    end
    if not to_idx or math.floor(to_idx) ~= to_idx or to_idx < 1 or to_idx > n then
        return nil, string.format("invalid 'to' index %s (expected 1..%d)", tostring(args.to), n)
    end
    if from_idx ~= to_idx then
        local card = table.remove(G.hand.cards, from_idx)
        table.insert(G.hand.cards, to_idx, card)
        G.hand:align_cards()
        G.hand:set_ranks()
        play_sound("cardSlide1")
    end
    return { action = "move_hand", from = from_idx, to = to_idx }
end

local function action_reorder_jokers(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not G.jokers or not G.jokers.cards or #G.jokers.cards < 2 then
        return nil, "need at least 2 jokers to reorder"
    end
    local n = #G.jokers.cards
    local perm, perm_err = validate_permutation(args.order, n)
    if not perm then return nil, perm_err end

    local reordered = {}
    for i, old_idx in ipairs(perm) do
        reordered[i] = G.jokers.cards[old_idx]
    end
    G.jokers.cards = reordered
    G.jokers:align_cards()
    G.jokers:set_ranks()
    play_sound("cardSlide1")
    return { action = "reorder_jokers", count = n }
end

local function action_reorder_hand(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not G.hand or not G.hand.cards or #G.hand.cards < 2 then
        return nil, "need at least 2 hand cards to reorder"
    end
    local n = #G.hand.cards
    local perm, perm_err = validate_permutation(args.order, n)
    if not perm then return nil, perm_err end

    local reordered = {}
    for i, old_idx in ipairs(perm) do
        reordered[i] = G.hand.cards[old_idx]
    end
    G.hand.cards = reordered
    G.hand:align_cards()
    G.hand:set_ranks()
    play_sound("cardSlide1")
    return { action = "reorder_hand", count = n }
end

local function action_sell_joker(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not G.jokers or not G.jokers.cards or #G.jokers.cards == 0 then
        return nil, "no jokers owned"
    end
    local idx = tonumber(args.index)
    if not idx or math.floor(idx) ~= idx or idx < 1 or idx > #G.jokers.cards then
        return nil, string.format("joker index %s out of range (1..%d)", tostring(args.index), #G.jokers.cards)
    end
    local card = G.jokers.cards[idx]
    if not card:can_sell_card() then
        return nil, "joker #" .. tostring(idx) .. " cannot be sold right now (may be Eternal or blocked)"
    end
    local name = card.ability and card.ability.name
    local sell_cost = card.sell_cost or 0
    G.FUNCS.sell_card({ config = { ref_table = card } })
    return { action = "sell_joker", index = idx, name = name, sell_cost = sell_cost }
end

local function action_sell_consumable(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not G.consumeables or not G.consumeables.cards or #G.consumeables.cards == 0 then
        return nil, "no consumables owned"
    end
    local idx = tonumber(args.index)
    if not idx or math.floor(idx) ~= idx or idx < 1 or idx > #G.consumeables.cards then
        return nil, string.format("consumable index %s out of range (1..%d)", tostring(args.index), #G.consumeables.cards)
    end
    local card = G.consumeables.cards[idx]
    if not card:can_sell_card() then
        return nil, "consumable #" .. tostring(idx) .. " cannot be sold right now"
    end
    local name = card.ability and card.ability.name
    local sell_cost = card.sell_cost or 0
    G.FUNCS.sell_card({ config = { ref_table = card } })
    return { action = "sell_consumable", index = idx, name = name, sell_cost = sell_cost }
end

local function action_use(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not G.consumeables or not G.consumeables.cards or #G.consumeables.cards == 0 then
        return nil, "no consumables owned"
    end
    local idx = tonumber(args.index)
    if not idx or math.floor(idx) ~= idx or idx < 1 or idx > #G.consumeables.cards then
        return nil, string.format("consumable index %s out of range (1..%d)", tostring(args.index), #G.consumeables.cards)
    end
    local card = G.consumeables.cards[idx]
    local ab = card.ability or {}

    local targets_applied = false
    if args.targets and type(args.targets) == "table" and #args.targets > 0 then
        local t_indices, t_err = validate_hand_indices(args.targets, 1, 5)
        if not t_indices then return nil, t_err end
        local h_ok, h_err = apply_hand_highlights(t_indices, false)
        if not h_ok then return nil, h_err end
        targets_applied = true
    end

    if not card:can_use_consumeable() then
        if targets_applied and G.hand then
            G.hand:unhighlight_all()
        end
        local max_h = (ab.consumeable and ab.consumeable.max_highlighted) or (ab.name == "Aura" and 1 or nil)
        if max_h then
            local min_h = (ab.consumeable and ab.consumeable.min_highlighted) or 1
            return nil, string.format(
                "consumable '%s' cannot be used (requires %d..%d valid target hand cards while hand is visible)",
                tostring(ab.name), min_h, max_h
            )
        end
        return nil, string.format("consumable '%s' cannot be used right now", tostring(ab.name))
    end

    G.FUNCS.use_card({ config = { ref_table = card } })
    return { action = "use", index = idx, name = ab.name }
end

local function action_cash_out(_args)
    local ok, err = require_run_ready(G.STATES.ROUND_EVAL, "ROUND_EVAL")
    if not ok then return nil, err end
    if not G.round_eval then
        return nil, "round_eval UI is not present"
    end
    local btn = find_cash_out_button()
    if not btn then
        return nil, "cash_out_button is not ready yet"
    end
    local dollars = G.GAME.current_round and G.GAME.current_round.dollars or 0
    G.FUNCS.cash_out(btn)
    return { action = "cash_out", dollars = dollars }
end

local function check_affordable(card)
    local cost = card.cost or 0
    if cost <= 0 then
        return true
    end
    local budget = (G.GAME.dollars or 0) - (G.GAME.bankrupt_at or 0)
    if cost > budget then
        return false, string.format("insufficient funds: costs $%d, available budget is $%d", cost, budget)
    end
    return true
end

local function action_buy(args)
    local ok, err = require_run_ready(G.STATES.SHOP, "SHOP")
    if not ok then return nil, err end
    if not G.shop_jokers or not G.shop_jokers.cards then
        return nil, "shop card area is not ready"
    end

    local idx = tonumber(args.index)
    if not idx or math.floor(idx) ~= idx or idx < 1 or idx > #G.shop_jokers.cards then
        return nil, string.format("shop card index %s out of range (1..%d)", tostring(args.index), #G.shop_jokers.cards)
    end

    local card = G.shop_jokers.cards[idx]
    local aff_ok, aff_err = check_affordable(card)
    if not aff_ok then return nil, aff_err end

    local buy_and_use = args.use and true or false
    if buy_and_use then
        if not (card.ability and card.ability.consumeable) then
            return nil, "buy_and_use is only valid for consumable cards"
        end
        if not card:can_use_consumeable() then
            return nil, "consumable card cannot be used right now"
        end
        G.FUNCS.buy_from_shop({ config = { ref_table = card, id = "buy_and_use" } })
        return { action = "buy", index = idx, name = card.ability and card.ability.name, use = true }
    end

    local set = card.ability and card.ability.set
    local is_neg = card.edition and card.edition.negative
    if set == "Joker" then
        local cap = G.jokers.config.card_limit + (is_neg and 1 or 0)
        if #G.jokers.cards >= cap then
            return nil, string.format("no free joker slot (%d/%d)", #G.jokers.cards, G.jokers.config.card_limit)
        end
    elseif card.ability and card.ability.consumeable then
        local cap = G.consumeables.config.card_limit + (is_neg and 1 or 0)
        if #G.consumeables.cards >= cap then
            return nil, string.format("no free consumable slot (%d/%d)", #G.consumeables.cards, G.consumeables.config.card_limit)
        end
    end

    G.FUNCS.buy_from_shop({ config = { ref_table = card, id = "buy" } })
    return { action = "buy", index = idx, name = card.ability and card.ability.name, use = false }
end

local function action_buy_voucher(args)
    local ok, err = require_run_ready(G.STATES.SHOP, "SHOP")
    if not ok then return nil, err end
    if not G.shop_vouchers or not G.shop_vouchers.cards then
        return nil, "shop vouchers area is not ready"
    end

    local idx = tonumber(args.index) or 1
    if math.floor(idx) ~= idx or idx < 1 or idx > #G.shop_vouchers.cards then
        return nil, string.format("voucher index %s out of range (1..%d)", tostring(args.index), #G.shop_vouchers.cards)
    end

    local card = G.shop_vouchers.cards[idx]
    local aff_ok, aff_err = check_affordable(card)
    if not aff_ok then return nil, aff_err end

    G.FUNCS.use_card({ config = { ref_table = card } })
    return { action = "buy_voucher", index = idx, name = card.ability and card.ability.name }
end

local function action_buy_pack(args)
    local ok, err = require_run_ready(G.STATES.SHOP, "SHOP")
    if not ok then return nil, err end
    if not G.shop_booster or not G.shop_booster.cards then
        return nil, "shop booster area is not ready"
    end

    local idx = tonumber(args.index)
    if not idx or math.floor(idx) ~= idx or idx < 1 or idx > #G.shop_booster.cards then
        return nil, string.format("booster pack index %s out of range (1..%d)", tostring(args.index), #G.shop_booster.cards)
    end

    local card = G.shop_booster.cards[idx]
    local aff_ok, aff_err = check_affordable(card)
    if not aff_ok then return nil, aff_err end

    G.FUNCS.use_card({ config = { ref_table = card } })
    return { action = "buy_pack", index = idx, name = card.ability and card.ability.name }
end

local function action_reroll(_args)
    local ok, err = require_run_ready(G.STATES.SHOP, "SHOP")
    if not ok then return nil, err end
    if not G.shop_jokers then
        return nil, "shop is not ready"
    end

    local cost = (G.GAME.current_round and G.GAME.current_round.reroll_cost) or 5
    local budget = (G.GAME.dollars or 0) - (G.GAME.bankrupt_at or 0)
    if cost > 0 and budget < cost then
        return nil, string.format("cannot afford reroll: costs $%d, budget is $%d", cost, budget)
    end

    G.FUNCS.reroll_shop(nil)
    return { action = "reroll", cost = cost }
end

local function action_next_round(_args)
    local ok, err = require_run_ready(G.STATES.SHOP, "SHOP")
    if not ok then return nil, err end
    if not G.shop then
        return nil, "shop UI is not present"
    end

    G.FUNCS.toggle_shop(nil)
    return { action = "next_round" }
end

local function action_pick(args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not is_pack_state() then
        return nil, "not currently in a booster pack state (G.STATE=" .. tostring(G.STATE) .. ")"
    end
    if not G.pack_cards or not G.pack_cards.cards or #G.pack_cards.cards == 0 then
        return nil, "pack cards are not ready"
    end

    local idx = tonumber(args.index)
    if not idx or math.floor(idx) ~= idx or idx < 1 or idx > #G.pack_cards.cards then
        return nil, string.format("pack card index %s out of range (1..%d)", tostring(args.index), #G.pack_cards.cards)
    end

    local card = G.pack_cards.cards[idx]
    local targets_applied = false

    if args.targets and type(args.targets) == "table" and #args.targets > 0 then
        local t_indices, t_err = validate_hand_indices(args.targets, 1, 5)
        if not t_indices then return nil, t_err end
        local h_ok, h_err = apply_hand_highlights(t_indices, false)
        if not h_ok then return nil, h_err end
        targets_applied = true
    end

    if card.ability and card.ability.set == "Joker" then
        local is_neg = card.edition and card.edition.negative
        if not is_neg and G.jokers and #G.jokers.cards >= G.jokers.config.card_limit then
            return nil, string.format("no free joker slot (%d/%d)", #G.jokers.cards, G.jokers.config.card_limit)
        end
    elseif card.ability and card.ability.consumeable then
        if not card:can_use_consumeable() then
            if targets_applied and G.hand then
                G.hand:unhighlight_all()
            end
            return nil, "selected pack consumable cannot be used with current hand selection"
        end
    end

    G.FUNCS.use_card({ config = { ref_table = card } })
    return { action = "pick", index = idx, name = card.ability and card.ability.name }
end

local function action_skip_pack(_args)
    local ok, err = require_run_ready(nil, nil)
    if not ok then return nil, err end
    if not is_pack_state() then
        return nil, "not currently in a booster pack state"
    end
    local can_skip = (G.pack_cards and G.pack_cards.cards and G.pack_cards.cards[1] ~= nil)
        and (
            G.STATE == G.STATES.PLANET_PACK
            or G.STATE == G.STATES.STANDARD_PACK
            or G.STATE == G.STATES.BUFFOON_PACK
            or (G.hand and (G.hand.cards[1] ~= nil or (G.hand.config and G.hand.config.card_limit <= 0)))
        )
    if not can_skip then
        return nil, "pack cannot be skipped right now"
    end

    G.FUNCS.skip_booster(nil)
    return { action = "skip_pack" }
end

local ACTIONS = {
    start = action_start,
    continue = action_continue,
    main_menu = action_main_menu,
    endless = action_endless,
    dismiss_overlay = action_dismiss_overlay,
    select_blind = action_select_blind,
    skip_blind = action_skip_blind,
    reroll_boss = action_reroll_boss,
    play = action_play,
    discard = action_discard,
    sort_hand = action_sort_hand,
    set_speed = action_set_speed,
    move_joker = action_move_joker,
    move_hand = action_move_hand,
    reorder_jokers = action_reorder_jokers,
    reorder_hand = action_reorder_hand,
    sell_joker = action_sell_joker,
    sell_consumable = action_sell_consumable,
    use = action_use,
    cash_out = action_cash_out,
    buy = action_buy,
    buy_voucher = action_buy_voucher,
    buy_pack = action_buy_pack,
    reroll = action_reroll,
    next_round = action_next_round,
    pick = action_pick,
    skip_pack = action_skip_pack,
}

function M.dispatch(args)
    if type(args) ~= "table" or type(args.name) ~= "string" or args.name == "" then
        return nil, "missing 'name' field in action args"
    end
    local fn = ACTIONS[args.name]
    if not fn then
        return nil, "unknown action: " .. tostring(args.name)
    end
    return fn(args)
end

return M
