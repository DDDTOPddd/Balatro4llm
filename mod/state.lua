-- Read-only, side-effect-free Balatro game state exporter.
-- Every field referenced here is verified against Balatro 1.0.1o-FULL Lua source.

local json = require("balatro4llm_json")

local M = {
    SCHEMA_VERSION = 1,
}

local PACK_STATE_KEYS = {
    TAROT_PACK = true,
    PLANET_PACK = true,
    SPECTRAL_PACK = true,
    STANDARD_PACK = true,
    BUFFOON_PACK = true,
}

local RANK_SHORT = {
    ["2"] = "2", ["3"] = "3", ["4"] = "4", ["5"] = "5",
    ["6"] = "6", ["7"] = "7", ["8"] = "8", ["9"] = "9",
    ["10"] = "10", ["Jack"] = "J", ["Queen"] = "Q",
    ["King"] = "K", ["Ace"] = "A",
}

local SUIT_SHORT = {
    Spades = "S",
    Hearts = "H",
    Clubs = "C",
    Diamonds = "D",
}

local RARITY_NAME = {
    [1] = "Common",
    [2] = "Uncommon",
    [3] = "Rare",
    [4] = "Legendary",
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

local function safe_localize_name(set, key, fallback)
    if not localize or not set or not key then
        return fallback
    end
    local ok, res = pcall(localize, { type = "name_text", set = set, key = key })
    if ok and type(res) == "string" and res ~= "" and res ~= "ERROR" then
        return res
    end
    return fallback
end

local function safe_raw_desc(set, key, vars)
    if not localize or not set or not key then
        return nil
    end
    local ok, lines = pcall(localize, {
        type = "raw_descriptions",
        set = set,
        key = key,
        vars = vars or {},
    })
    if not ok or type(lines) ~= "table" or #lines == 0 then
        return nil
    end
    local cleaned = {}
    for _, line in ipairs(lines) do
        if type(line) == "string" then
            local s = line:gsub("%s+", " "):gsub("^%s+", ""):gsub("%s+$", "")
            if s ~= "" then
                cleaned[#cleaned + 1] = s
            end
        end
    end
    if #cleaned == 0 then
        return nil
    end
    return table.concat(cleaned, " ")
end

-- Pure side-effect-free loc_vars computation mirroring card.lua:732-921 & common_events.lua:2559-2705.
local function joker_loc_vars(card)
    local ab = card.ability or {}
    local name = ab.name
    local probs = (G.GAME and G.GAME.probabilities and G.GAME.probabilities.normal) or 1

    if name == "Joker" then return { ab.mult }
    elseif name == "Jolly Joker" or name == "Zany Joker" or name == "Mad Joker"
        or name == "Crazy Joker" or name == "Droll Joker" then
        return { ab.t_mult, localize(ab.type, "poker_hands") }
    elseif name == "Sly Joker" or name == "Wily Joker" or name == "Clever Joker"
        or name == "Devious Joker" or name == "Crafty Joker" then
        return { ab.t_chips, localize(ab.type, "poker_hands") }
    elseif name == "Half Joker" then return { ab.extra.mult, ab.extra.size }
    elseif name == "Fortune Teller" then
        return { ab.extra, (G.GAME and G.GAME.consumeable_usage_total and G.GAME.consumeable_usage_total.tarot or 0) }
    elseif name == "Steel Joker" then return { ab.extra, 1 + ab.extra * (ab.steel_tally or 0) }
    elseif name == "Chaos the Clown" then return { ab.extra }
    elseif name == "Space Joker" then return { "" .. probs, ab.extra }
    elseif name == "Stone Joker" then return { ab.extra, ab.extra * (ab.stone_tally or 0) }
    elseif name == "Drunkard" then return { ab.d_size }
    elseif name == "Green Joker" then return { ab.extra.hand_add, ab.extra.discard_sub, ab.mult }
    elseif name == "Credit Card" then return { ab.extra }
    elseif name == "Greedy Joker" or name == "Lusty Joker" or name == "Wrathful Joker" or name == "Gluttonous Joker" then
        return { ab.extra.s_mult, localize(ab.extra.suit, "suits_singular") }
    elseif name == "Blue Joker" then
        return { ab.extra, ab.extra * ((G.deck and G.deck.cards) and #G.deck.cards or 52) }
    elseif name == "Hack" or name == "Dusk" or name == "Sock and Buskin" then return { ab.extra + 1 }
    elseif name == "Faceless Joker" then return { ab.extra.dollars, ab.extra.faces }
    elseif name == "Juggler" then return { ab.h_size }
    elseif name == "Golden Joker" or name == "Banner" or name == "Fibonacci" or name == "Scary Face"
        or name == "Delayed Gratification" or name == "Even Steven" or name == "Odd Todd"
        or name == "Superposition" or name == "Egg" or name == "Burglar" or name == "DNA"
        or name == "Hiker" or name == "Astronomer" or name == "Golden Ticket" or name == "Acrobat"
        or name == "Certificate" or name == "Hanging Chad" or name == "Rough Gem" or name == "Arrowhead"
        or name == "Onyx Agate" or name == "Flower Pot" or name == "Seeing Double" or name == "Matador"
        or name == "Riff-raff" or name == "Vagabond" or name == "Baron" or name == "Photograph"
        or name == "Gift Card" or name == "To the Moon" or name == "Baseball Card" or name == "Trading Card"
        or name == "Seltzer" or name == "Smiley Face" or name == "Shoot the Moon" or name == "Triboulet"
        or name == "Perkeo" then
        return { ab.extra }
    elseif name == "Joker Stencil" then return { ab.x_mult }
    elseif name == "Ceremonial Dagger" or name == "Swashbuckler" then return { ab.mult }
    elseif name == "Mystic Summit" then return { ab.extra.mult, ab.extra.d_remaining }
    elseif name == "Loyalty Card" then
        local status = localize({
            type = "variable",
            key = (ab.loyalty_remaining == 0 and "loyalty_active" or "loyalty_inactive"),
            vars = { ab.loyalty_remaining },
        })
        return { ab.extra.Xmult, ab.extra.every + 1, status }
    elseif name == "8 Ball" or name == "Business Card" or name == "Hallucination" then
        return { "" .. probs, ab.extra }
    elseif name == "Abstract Joker" then
        return { ab.extra, (G.jokers and G.jokers.cards and #G.jokers.cards or 0) * ab.extra }
    elseif name == "Gros Michel" then return { ab.extra.mult, "" .. probs, ab.extra.odds }
    elseif name == "Scholar" then return { ab.extra.mult, ab.extra.chips }
    elseif name == "Spare Trousers" then return { ab.extra, localize("Two Pair", "poker_hands"), ab.mult }
    elseif name == "Ride the Bus" or name == "Red Card" or name == "Flash Card" then return { ab.extra, ab.mult }
    elseif name == "Blackboard" then
        return { ab.extra, localize("Spades", "suits_plural"), localize("Clubs", "suits_plural") }
    elseif name == "Runner" or name == "Ice Cream" or name == "Wee Joker" or name == "Square Joker" then
        return { ab.extra.chips, ab.extra.chip_mod }
    elseif name == "Constellation" or name == "Throwback" or name == "Glass Joker" or name == "Hit the Road"
        or name == "Madness" or name == "Vampire" or name == "Hologram" or name == "Obelisk"
        or name == "Lucky Cat" or name == "Campfire" then
        return { ab.extra, ab.x_mult }
    elseif name == "To Do List" then
        return { ab.extra.dollars, localize(ab.to_do_poker_hand, "poker_hands") }
    elseif name == "Troubadour" then return { ab.extra.h_size, -ab.extra.h_plays }
    elseif name == "Bloodstone" then return { "" .. probs, ab.extra.odds, ab.extra.Xmult }
    elseif name == "Merry Andy" then return { ab.d_size, ab.h_size }
    elseif name == "The Idol" then
        local ic = G.GAME and G.GAME.current_round and G.GAME.current_round.idol_card
        if ic then
            return { ab.extra, localize(ic.rank, "ranks"), localize(ic.suit, "suits_plural") }
        end
    elseif name == "The Duo" or name == "The Trio" or name == "The Family"
        or name == "The Order" or name == "The Tribe" then
        return { ab.x_mult, localize(ab.type, "poker_hands") }
    elseif name == "Cavendish" then return { ab.extra.Xmult, "" .. probs, ab.extra.odds }
    elseif name == "Card Sharp" then return { ab.extra.Xmult }
    elseif name == "Seance" then return { localize(ab.extra.poker_hand, "poker_hands") }
    elseif name == "Cloud 9" then return { ab.extra, ab.extra * (ab.nine_tally or 0) }
    elseif name == "Rocket" then return { ab.extra.dollars, ab.extra.increase }
    elseif name == "Turtle Bean" then return { ab.extra.h_size, ab.extra.h_mod }
    elseif name == "Erosion" then
        local missing = G.playing_cards and (G.GAME.starting_deck_size - #G.playing_cards) or 0
        return { ab.extra, math.max(0, ab.extra * missing), G.GAME.starting_deck_size }
    elseif name == "Reserved Parking" then return { ab.extra.dollars, "" .. probs, ab.extra.odds }
    elseif name == "Mail-In Rebate" then
        local mc = G.GAME and G.GAME.current_round and G.GAME.current_round.mail_card
        return { ab.extra, mc and localize(mc.rank, "ranks") or "Ace" }
    elseif name == "Bull" then
        return { ab.extra, ab.extra * math.max(0, (G.GAME and G.GAME.dollars) or 0) }
    elseif name == "Diet Cola" then
        return { safe_localize_name("Tag", "tag_double", "Double Tag") }
    elseif name == "Popcorn" then return { ab.mult, ab.extra }
    elseif name == "Ramen" then return { ab.x_mult, ab.extra }
    elseif name == "Ancient Joker" then
        local ac = G.GAME and G.GAME.current_round and G.GAME.current_round.ancient_card
        return { ab.extra, ac and localize(ac.suit, "suits_singular") or "Spades" }
    elseif name == "Walkie Talkie" then return { ab.extra.chips, ab.extra.mult }
    elseif name == "Castle" then
        local cc = G.GAME and G.GAME.current_round and G.GAME.current_round.castle_card
        return { ab.extra.chip_mod, cc and localize(cc.suit, "suits_singular") or "Spades", ab.extra.chips }
    elseif name == "Stuntman" then return { ab.extra.chip_mod, ab.extra.h_size }
    elseif name == "Invisible Joker" then return { ab.extra, ab.invis_rounds }
    elseif name == "Satellite" then
        local planets_used = 0
        if G.GAME and G.GAME.consumeable_usage then
            for _, v in pairs(G.GAME.consumeable_usage) do
                if v.set == "Planet" then planets_used = planets_used + 1 end
            end
        end
        return { ab.extra, planets_used * ab.extra }
    elseif name == "Driver's License" then return { ab.extra, ab.driver_tally or 0 }
    elseif name == "Bootstraps" then
        local dollars = (G.GAME and G.GAME.dollars or 0) + (G.GAME and G.GAME.dollar_buffer or 0)
        return { ab.extra.mult, ab.extra.dollars, ab.extra.mult * math.floor(dollars / ab.extra.dollars) }
    elseif name == "Caino" then return { ab.extra, ab.caino_xmult }
    elseif name == "Yorick" then return { ab.extra.xmult, ab.extra.discards, ab.yorick_discards, ab.x_mult }
    end
    return {}
end

local function card_description(card)
    local center = card.config and card.config.center
    local ab = card.ability or {}
    if not center or not center.key then
        return nil
    end
    local set = ab.set or center.set
    local cfg = center.config or {}

    if set == "Joker" then
        if ab.name == "Misprint" and type(ab.extra) == "table" then
            return string.format("+%s-%s Mult (random)", tostring(ab.extra.min or 0), tostring(ab.extra.max or 23))
        end
        local ok, vars = pcall(joker_loc_vars, card)
        return safe_raw_desc("Joker", center.key, ok and vars or {})
    elseif set == "Planet" then
        local hand_type = cfg.hand_type
        local h = hand_type and G.GAME and G.GAME.hands and G.GAME.hands[hand_type]
        if h then
            return safe_raw_desc("Planet", center.key, {
                h.level,
                localize(hand_type, "poker_hands"),
                h.l_mult,
                h.l_chips,
            })
        end
        return safe_raw_desc("Planet", center.key, {})
    elseif set == "Tarot" then
        local vars = {}
        local name = center.name
        if name == "The Fool" then
            local fc = G.GAME and G.GAME.last_tarot_planet and G.P_CENTERS[G.GAME.last_tarot_planet]
            vars = { fc and safe_localize_name(fc.set, fc.key, fc.name) or localize("k_none") }
        elseif name == "The Magician" or name == "The Empress" or name == "The Hierophant"
            or name == "The Lovers" or name == "The Chariot" or name == "Justice"
            or name == "The Devil" or name == "The Tower" then
            vars = { cfg.max_highlighted, safe_localize_name("Enhanced", cfg.mod_conv, cfg.mod_conv) }
        elseif name == "The High Priestess" then vars = { cfg.planets }
        elseif name == "The Emperor" then vars = { cfg.tarots }
        elseif name == "The Hermit" then vars = { cfg.extra }
        elseif name == "The Wheel of Fortune" then
            vars = { (G.GAME and G.GAME.probabilities and G.GAME.probabilities.normal) or 1, cfg.extra }
        elseif name == "Strength" or name == "The Hanged Man" or name == "Death" then
            vars = { cfg.max_highlighted }
        elseif name == "Temperance" then
            local money = 0
            if G.jokers and G.jokers.cards then
                for _, j in ipairs(G.jokers.cards) do
                    if j.ability and j.ability.set == "Joker" then
                        money = money + (j.sell_cost or 0)
                    end
                end
            end
            vars = { cfg.extra, math.min(cfg.extra or 50, money) }
        elseif name == "The Star" or name == "The Moon" or name == "The Sun" or name == "The World" then
            vars = { cfg.max_highlighted, localize(cfg.suit_conv, "suits_plural") }
        end
        return safe_raw_desc("Tarot", center.key, vars)
    elseif set == "Spectral" then
        local vars = {}
        local name = center.name
        if name == "Familiar" or name == "Grim" or name == "Incantation" or name == "Cryptid" then
            vars = { cfg.extra }
        elseif name == "Immolate" then
            vars = { cfg.extra.destroy, cfg.extra.dollars }
        elseif name == "Ectoplasm" then
            vars = { (G.GAME and G.GAME.ecto_minus) or 1 }
        end
        return safe_raw_desc("Spectral", center.key, vars)
    elseif set == "Voucher" then
        local vars = {}
        local name = center.name
        if name == "Tarot Merchant" or name == "Tarot Tycoon"
            or name == "Planet Merchant" or name == "Planet Tycoon" then
            vars = { cfg.extra_disp }
        elseif name == "Seed Money" or name == "Money Tree" then
            vars = { (cfg.extra or 0) / 5 }
        elseif cfg.extra ~= nil then
            vars = { cfg.extra }
        end
        return safe_raw_desc("Voucher", center.key, vars)
    elseif set == "Booster" then
        local override_map = {
            ["Arcana Pack"] = "p_arcana_normal",
            ["Jumbo Arcana Pack"] = "p_arcana_jumbo",
            ["Mega Arcana Pack"] = "p_arcana_mega",
            ["Celestial Pack"] = "p_celestial_normal",
            ["Jumbo Celestial Pack"] = "p_celestial_jumbo",
            ["Mega Celestial Pack"] = "p_celestial_mega",
            ["Spectral Pack"] = "p_spectral_normal",
            ["Jumbo Spectral Pack"] = "p_spectral_jumbo",
            ["Mega Spectral Pack"] = "p_spectral_mega",
            ["Standard Pack"] = "p_standard_normal",
            ["Jumbo Standard Pack"] = "p_standard_jumbo",
            ["Mega Standard Pack"] = "p_standard_mega",
            ["Buffoon Pack"] = "p_buffoon_normal",
            ["Jumbo Buffoon Pack"] = "p_buffoon_jumbo",
            ["Mega Buffoon Pack"] = "p_buffoon_mega",
        }
        local ok_key = override_map[center.name]
        if ok_key then
            return safe_raw_desc("Other", ok_key, { cfg.choose, cfg.extra })
        end
        return nil
    end
    return nil
end

local function tag_description(tag_key, blind_slot, tag_obj)
    local ok, desc = pcall(function()
        local proto = G.P_TAGS and G.P_TAGS[tag_key]
        if not proto then
            return nil
        end
        local cfg = (tag_obj and tag_obj.config) or proto.config or {}
        local name = proto.name
        local vars = {}
        if name == "Investment Tag" then vars = { cfg.dollars }
        elseif name == "Handy Tag" then
            vars = { cfg.dollars_per_hand, (cfg.dollars_per_hand or 1) * ((G.GAME and G.GAME.hands_played) or 0) }
        elseif name == "Garbage Tag" then
            vars = { cfg.dollars_per_discard, (cfg.dollars_per_discard or 1) * ((G.GAME and G.GAME.unused_discards) or 0) }
        elseif name == "Juggle Tag" then vars = { cfg.h_size }
        elseif name == "Top-up Tag" then vars = { cfg.spawn_jokers }
        elseif name == "Skip Tag" then
            vars = { cfg.skip_bonus, (cfg.skip_bonus or 5) * (((G.GAME and G.GAME.skips) or 0) + 1) }
        elseif name == "Orbital Tag" then
            local hand_name = nil
            if tag_obj and tag_obj.ability and tag_obj.ability.orbital_hand then
                hand_name = tag_obj.ability.orbital_hand
            elseif blind_slot and G.GAME and G.GAME.orbital_choices
                and G.GAME.orbital_choices[G.GAME.round_resets.ante] then
                hand_name = G.GAME.orbital_choices[G.GAME.round_resets.ante][blind_slot]
            end
            local disp_hand = hand_name and localize(hand_name, "poker_hands") or ("[" .. localize("k_poker_hand") .. "]")
            if disp_hand == "ERROR" then disp_hand = hand_name or "Poker Hand" end
            vars = { disp_hand, cfg.levels }
        elseif name == "Economy Tag" then vars = { cfg.max }
        end
        return safe_raw_desc("Tag", tag_key, vars)
    end)
    if ok then
        return desc
    end
    return nil
end

local function serialize_playing_card(card, index, context)
    local face_down = (card.facing == "back")
    local ab = card.ability or {}
    local entry = {
        index = index,
        id = card.sort_id,
        kind = "PlayingCard",
        face_down = face_down,
        highlighted = card.highlighted and true or false,
        debuff = card.debuff and true or false,
        forced_selection = (ab.forced_selection) and true or false,
    }
    if context == "shop" or context == "pack" then
        entry.cost = card.cost or 0
        if context == "shop" then
            local budget = (G.GAME and ((G.GAME.dollars or 0) - (G.GAME.bankrupt_at or 0))) or 0
            entry.can_buy = (entry.cost <= budget) or (entry.cost == 0)
        else
            entry.can_select = true
        end
    end
    if face_down then
        entry.short = "??"
        return entry
    end

    local base = card.base or {}
    local is_stone = (ab.effect == "Stone Card")
    entry.rank = base.value
    entry.rank_id = base.id
    entry.suit = base.suit
    if is_stone then
        entry.short = "Stone"
    else
        entry.short = (RANK_SHORT[base.value] or tostring(base.value or "?"))
            .. (SUIT_SHORT[base.suit] or "?")
    end

    local nominal = is_stone and 0 or (base.nominal or 0)
    entry.chips = nominal + (ab.bonus or 0) + (ab.perma_bonus or 0)
    entry.perma_bonus = ab.perma_bonus or 0
    if ab.set == "Enhanced" then
        entry.enhancement = ab.name
    end
    if card.edition and card.edition.type then
        entry.edition = card.edition.type
    end
    if card.seal then
        entry.seal = card.seal
    end
    return entry
end

local function serialize_item_card(card, index, context)
    local ab = card.ability or {}
    local center = card.config and card.config.center or {}
    local set = ab.set or center.set or "Unknown"

    if set == "Default" or set == "Enhanced" then
        return serialize_playing_card(card, index, context)
    end

    local face_down = (card.facing == "back")
    local key = card.config and card.config.center_key or center.key
    local entry = {
        index = index,
        id = card.sort_id,
        kind = set,
        key = key,
        face_down = face_down,
        highlighted = card.highlighted and true or false,
        debuff = card.debuff and true or false,
    }

    if face_down then
        entry.name = "???"
        entry.loc_name = "???"
        if context == "jokers" or context == "consumeables" then
            entry.sell_cost = card.sell_cost or 0
            local ok_sell, can_sell = pcall(function() return card:can_sell_card() end)
            entry.can_sell = (ok_sell and can_sell) and true or false
        end
        return entry
    end

    entry.name = ab.name or center.name or card.label or set
    if set == "Booster" then
        local override_map = {
            ["Arcana Pack"] = "p_arcana_normal",
            ["Jumbo Arcana Pack"] = "p_arcana_jumbo",
            ["Mega Arcana Pack"] = "p_arcana_mega",
            ["Celestial Pack"] = "p_celestial_normal",
            ["Jumbo Celestial Pack"] = "p_celestial_jumbo",
            ["Mega Celestial Pack"] = "p_celestial_mega",
            ["Spectral Pack"] = "p_spectral_normal",
            ["Jumbo Spectral Pack"] = "p_spectral_jumbo",
            ["Mega Spectral Pack"] = "p_spectral_mega",
            ["Standard Pack"] = "p_standard_normal",
            ["Jumbo Standard Pack"] = "p_standard_jumbo",
            ["Mega Standard Pack"] = "p_standard_mega",
            ["Buffoon Pack"] = "p_buffoon_normal",
            ["Jumbo Buffoon Pack"] = "p_buffoon_jumbo",
            ["Mega Buffoon Pack"] = "p_buffoon_mega",
        }
        entry.loc_name = safe_localize_name("Other", override_map[entry.name], entry.name)
    else
        entry.loc_name = safe_localize_name(set, key, entry.name)
    end

    if set == "Joker" and center.rarity then
        entry.rarity = RARITY_NAME[center.rarity] or tostring(center.rarity)
    end
    if card.edition and card.edition.type then
        entry.edition = card.edition.type
    end
    if ab.eternal then entry.eternal = true end
    if ab.perishable then
        entry.perishable = true
        entry.perish_tally = ab.perish_tally
    end
    if ab.rental then entry.rental = true end

    local ok_desc, desc = pcall(card_description, card)
    if ok_desc and desc then
        entry.description = desc
    end

    if ab.consumeable then
        local ok_use, can_use = pcall(function() return card:can_use_consumeable() end)
        entry.can_use = (ok_use and can_use) and true or false
        local max_h = ab.consumeable.max_highlighted
        local min_h = ab.consumeable.min_highlighted
        if ab.name == "Aura" then
            max_h = 1
            min_h = 1
        end
        if max_h then
            entry.max_highlighted = max_h
            entry.min_highlighted = min_h or 1
        end
        if ab.consumeable.hand_type then
            entry.hand_type = ab.consumeable.hand_type
        end
        -- Targeted consumables report can_use=false when 0 hand cards are currently highlighted,
        -- even though the agent can supply target hand indices directly via `use`/`pick`.
        local can_use_with_targets = entry.can_use
        if not can_use_with_targets and max_h then
            local in_target_state = (
                G.STATE == G.STATES.SELECTING_HAND
                or G.STATE == G.STATES.TAROT_PACK
                or G.STATE == G.STATES.SPECTRAL_PACK
                or G.STATE == G.STATES.PLANET_PACK
            )
            local not_blocked = not ((G.play and #G.play.cards > 0) or (G.CONTROLLER and G.CONTROLLER.locked) or (G.GAME and G.GAME.STOP_USE and G.GAME.STOP_USE > 0))
            if in_target_state and not_blocked and G.hand and G.hand.cards then
                if ab.name == "Aura" then
                    for _, hc in ipairs(G.hand.cards) do
                        if not hc.edition then
                            can_use_with_targets = true
                            break
                        end
                    end
                elseif #G.hand.cards >= (min_h or 1) then
                    can_use_with_targets = true
                end
            end
        end
        entry.can_use_with_targets = can_use_with_targets
    end

    if set == "Booster" and center.config then
        entry.choose = center.config.choose
        entry.pack_size = center.config.extra
    end

    if context == "jokers" or context == "consumeables" then
        entry.sell_cost = card.sell_cost or 0
        local ok_sell, can_sell = pcall(function() return card:can_sell_card() end)
        entry.can_sell = (ok_sell and can_sell) and true or false
    elseif context == "shop" then
        entry.cost = card.cost or 0
        local budget = (G.GAME and ((G.GAME.dollars or 0) - (G.GAME.bankrupt_at or 0))) or 0
        local affordable = (entry.cost <= budget) or (entry.cost == 0)
        local has_space = true
        if set == "Joker" then
            local is_neg = card.edition and card.edition.negative
            has_space = is_neg or (G.jokers and (#G.jokers.cards + (G.GAME.joker_buffer or 0) < G.jokers.config.card_limit))
        elseif ab.consumeable then
            local is_neg = card.edition and card.edition.negative
            has_space = is_neg or (G.consumeables and (#G.consumeables.cards + (G.GAME.consumeable_buffer or 0) < G.consumeables.config.card_limit))
        end
        entry.can_buy = (affordable and has_space) and true or false
        if ab.consumeable then
            entry.can_buy_and_use = (affordable and entry.can_use) and true or false
        end
    elseif context == "pack" then
        if set == "Joker" then
            local is_neg = card.edition and card.edition.negative
            entry.can_select = (is_neg or (G.jokers and #G.jokers.cards < G.jokers.config.card_limit)) and true or false
        elseif ab.consumeable then
            entry.can_select = (entry.can_use or entry.can_use_with_targets) and true or false
        else
            entry.can_select = true
        end
    end

    return entry
end

local function serialize_cardarea(area, context, is_playing_area)
    local list = json.array({})
    if not area or not area.cards then
        return list
    end
    for i, card in ipairs(area.cards) do
        if is_playing_area then
            list[i] = serialize_playing_card(card, i, context)
        else
            list[i] = serialize_item_card(card, i, context)
        end
    end
    return list
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

local function build_ready_info(state_name)
    local eq = {
        base = 0,
        unlock = 0,
        tutorial = 0,
        achievement = 0,
        other = 0,
        total = 0,
        base_blocking = 0,
    }
    if G.E_MANAGER and G.E_MANAGER.queues then
        for qname, q in pairs(G.E_MANAGER.queues) do
            if type(q) == "table" then
                local n = #q
                eq[qname] = n
                eq.total = eq.total + n
                if qname == "base" then
                    for _, ev in ipairs(q) do
                        if ev.blocking then
                            eq.base_blocking = eq.base_blocking + 1
                        end
                    end
                end
            end
        end
    end

    local active_locks = json.array({})
    if G.CONTROLLER and G.CONTROLLER.locks then
        for k, v in pairs(G.CONTROLLER.locks) do
            if v then
                active_locks[#active_locks + 1] = tostring(k)
            end
        end
        table.sort(active_locks)
    end

    local round_eval_ready = (state_name == "ROUND_EVAL")
        and (G.round_eval ~= nil)
        and (find_cash_out_button() ~= nil)

    local shop_ready = (state_name == "SHOP")
        and (G.STATE_COMPLETE and true or false)
        and (G.shop ~= nil)
        and (G.shop_jokers ~= nil)
        and (G.shop_vouchers ~= nil)
        and (G.shop_booster ~= nil)
        and (eq.base_blocking == 0)

    local blind_select_ready = (state_name == "BLIND_SELECT")
        and (G.STATE_COMPLETE and true or false)
        and (G.blind_select ~= nil)

    local pack_ready = (PACK_STATE_KEYS[state_name] == true)
        and (G.STATE_COMPLETE and true or false)
        and (G.pack_cards ~= nil)
        and (G.pack_cards.cards ~= nil)
        and (#G.pack_cards.cards > 0)

    return {
        paused = (G.SETTINGS and G.SETTINGS.paused) and true or false,
        has_overlay_menu = (G.OVERLAY_MENU ~= nil),
        in_tutorial = (G.OVERLAY_TUTORIAL ~= nil),
        tutorial_complete = (G.SETTINGS and G.SETTINGS.tutorial_complete) and true or false,
        controller_locked = (G.CONTROLLER and G.CONTROLLER.locked) and true or false,
        controller_lock_input = (G.CONTROLLER and G.CONTROLLER.lock_input) and true or false,
        active_locks = active_locks,
        event_queues = eq,
        stop_use = (G.GAME and G.GAME.STOP_USE) or 0,
        block_play = (G.GAME and G.GAME.blind and G.GAME.blind.block_play) and true or false,
        round_eval_ready = round_eval_ready,
        shop_ready = shop_ready,
        blind_select_ready = blind_select_ready,
        pack_ready = pack_ready,
    }
end

local function build_blind_info()
    local uv = G.GAME and G.GAME.used_vouchers or {}
    local rr0 = G.GAME and G.GAME.round_resets or {}
    local budget = (G.GAME and ((G.GAME.dollars or 0) - (G.GAME.bankrupt_at or 0))) or 0
    local can_reroll_boss = (budget >= 10) and (
        (uv["v_retcon"] and true or false)
        or ((uv["v_directors_cut"] and true or false) and not rr0.boss_rerolled)
    )
    local res = {
        active = nil,
        on_deck = G.GAME and G.GAME.blind_on_deck or nil,
        can_reroll_boss = can_reroll_boss,
        choices = json.array({}),
    }

    local b = G.GAME and G.GAME.blind
    if b and b.name and b.name ~= "" then
        local bkey = b.config and b.config.blind and b.config.blind.key or nil
        local debuff_text = ""
        if not b.disabled and b.get_loc_debuff_text then
            local ok, dt = pcall(b.get_loc_debuff_text, b)
            if ok and type(dt) == "string" then
                debuff_text = dt:gsub("%s+", " "):gsub("^%s+", ""):gsub("%s+$", "")
            end
        end
        res.active = {
            key = bkey,
            type = b.get_type and b:get_type() or nil,
            name = b.name,
            loc_name = b.loc_name or safe_localize_name("Blind", bkey, b.name),
            chips = b.chips or 0,
            dollars = b.dollars or 0,
            boss = b.boss and true or false,
            disabled = b.disabled and true or false,
            triggered = b.triggered and true or false,
            debuff_text = debuff_text,
        }
    end

    local rr = G.GAME and G.GAME.round_resets
    if rr and rr.blind_choices and rr.blind_states then
        local base_ante = rr.blind_ante or rr.ante or 1
        local base_amt = get_blind_amount and get_blind_amount(base_ante) or 300
        local scaling = (G.GAME.starting_params and G.GAME.starting_params.ante_scaling) or 1
        local slots = { "Small", "Big", "Boss" }
        for _, slot in ipairs(slots) do
            local bkey = rr.blind_choices[slot]
            local proto = bkey and G.P_BLINDS and G.P_BLINDS[bkey]
            local status = rr.blind_states[slot]
            if proto then
                local debuff_text = ""
                if proto.boss then
                    local vars = proto.vars
                    if proto.name == "The Ox" and G.GAME.current_round and G.GAME.current_round.most_played_poker_hand then
                        vars = { localize(G.GAME.current_round.most_played_poker_hand, "poker_hands") }
                    end
                    debuff_text = safe_raw_desc("Blind", bkey, vars) or ""
                end
                local dollars = proto.dollars or 0
                if G.GAME.modifiers and G.GAME.modifiers.no_blind_reward and G.GAME.modifiers.no_blind_reward[slot] then
                    dollars = 0
                end
                local skip_tag = nil
                if slot ~= "Boss" and rr.blind_tags and rr.blind_tags[slot] then
                    local tkey = rr.blind_tags[slot]
                    local tproto = G.P_TAGS and G.P_TAGS[tkey]
                    if tproto then
                        skip_tag = {
                            key = tkey,
                            name = tproto.name,
                            loc_name = safe_localize_name("Tag", tkey, tproto.name),
                            description = tag_description(tkey, slot, nil),
                        }
                    end
                end
                res.choices[#res.choices + 1] = {
                    slot = slot,
                    key = bkey,
                    name = proto.name,
                    loc_name = safe_localize_name("Blind", bkey, proto.name),
                    status = status,
                    chips = base_amt * (proto.mult or 1) * scaling,
                    dollars = dollars,
                    boss = proto.boss and true or false,
                    debuff_text = debuff_text,
                    skip_tag = skip_tag,
                }
            end
        end
    end

    return res
end

local function build_menu_info()
    local profile = G.SETTINGS and G.SETTINGS.profile or 1
    local has_save = (G.SAVED_GAME ~= nil)
    if not has_save and love and love.filesystem and love.filesystem.getInfo then
        has_save = (love.filesystem.getInfo(profile .. "/save.jkr") ~= nil)
    end
    local sel = G.GAME and G.GAME.selected_back
    local sel_key = sel and sel.effect and sel.effect.center and sel.effect.center.key or "b_red"
    local unlocked_decks = json.array({})
    if G.P_CENTER_POOLS and G.P_CENTER_POOLS.Back then
        for _, back in ipairs(G.P_CENTER_POOLS.Back) do
            if back.unlocked then
                unlocked_decks[#unlocked_decks + 1] = {
                    key = back.key,
                    name = back.name,
                    loc_name = safe_localize_name("Back", back.key, back.name),
                }
            end
        end
    end
    return {
        profile = profile,
        has_saved_run = has_save,
        selected_deck = {
            key = sel_key,
            name = (sel and sel.name) or "Red Deck",
            loc_name = (sel and sel.loc_name) or safe_localize_name("Back", sel_key, "Red Deck"),
        },
        unlocked_decks = unlocked_decks,
    }
end

local function build_run_info()
    local game = G.GAME
    if not game then
        return nil
    end
    local cr = game.current_round or {}
    local rr = game.round_resets or {}

    local stake_num = game.stake or 1
    local stake_proto = G.P_CENTER_POOLS and G.P_CENTER_POOLS.Stake and G.P_CENTER_POOLS.Stake[stake_num]
    local stake_name = stake_proto and stake_proto.name or ("Stake " .. tostring(stake_num))

    local back = game.selected_back
    local back_key = back and back.effect and back.effect.center and back.effect.center.key or nil

    local vouchers = json.array({})
    if game.used_vouchers then
        for vkey, used in pairs(game.used_vouchers) do
            if used then
                local vp = G.P_CENTERS and G.P_CENTERS[vkey]
                vouchers[#vouchers + 1] = {
                    key = vkey,
                    name = vp and vp.name or vkey,
                    loc_name = safe_localize_name("Voucher", vkey, vp and vp.name or vkey),
                }
            end
        end
        table.sort(vouchers, function(a, b) return a.key < b.key end)
    end

    local tags = json.array({})
    if game.tags then
        for _, tag_obj in ipairs(game.tags) do
            if tag_obj and tag_obj.key then
                tags[#tags + 1] = {
                    key = tag_obj.key,
                    name = tag_obj.name,
                    loc_name = safe_localize_name("Tag", tag_obj.key, tag_obj.name),
                    description = tag_description(tag_obj.key, nil, tag_obj),
                }
            end
        end
    end

    local poker_hands = json.array({})
    if game.hands then
        local ordered = {}
        for hname, h in pairs(game.hands) do
            if h.visible or (h.played and h.played > 0) or (h.level and h.level > 1) then
                ordered[#ordered + 1] = {
                    order = h.order or 99,
                    name = hname,
                    loc_name = localize(hname, "poker_hands"),
                    level = h.level or 1,
                    chips = h.chips or 0,
                    mult = h.mult or 0,
                    played = h.played or 0,
                    played_this_round = h.played_this_round or 0,
                }
            end
        end
        table.sort(ordered, function(a, b) return a.order < b.order end)
        for i, item in ipairs(ordered) do
            item.order = nil
            poker_hands[i] = item
        end
    end

    local ch = cr.current_hand or {}
    local preview = {
        hand_name = ch.handname or "",
        hand_level = ch.hand_level or "",
        chips = ch.chips or 0,
        mult = ch.mult or 0,
        boss_debuffed = G.boss_throw_hand and true or false,
    }

    return {
        ante = rr.ante or 1,
        blind_ante = rr.blind_ante or rr.ante or 1,
        win_ante = game.win_ante or 8,
        round = game.round or 0,
        won = game.won and true or false,
        stake = stake_num,
        stake_name = stake_name,
        deck = {
            key = back_key,
            name = (back and back.name) or "Red Deck",
            loc_name = (back and back.loc_name) or safe_localize_name("Back", back_key, "Red Deck"),
        },
        seed = game.pseudorandom and game.pseudorandom.seed or nil,
        seeded = game.seeded and true or false,
        dollars = game.dollars or 0,
        bankrupt_at = game.bankrupt_at or 0,
        chips = game.chips or 0,
        hands_left = cr.hands_left or 0,
        hands_played = cr.hands_played or 0,
        discards_left = cr.discards_left or 0,
        discards_used = cr.discards_used or 0,
        skips = game.skips or 0,
        probabilities_normal = (game.probabilities and game.probabilities.normal) or 1,
        most_played_hand = cr.most_played_poker_hand,
        current_hand_preview = preview,
        vouchers = vouchers,
        tags = tags,
        poker_hands = poker_hands,
    }
end

function M.get_state(_args)
    local stage = G and G.STAGE or nil
    local state = G and G.STATE or nil
    local stage_name = lookup_enum_name(G and G.STAGES, stage)
    local state_name = lookup_enum_name(G and G.STATES, state)

    local ready = build_ready_info(state_name)

    local out = {
        schema_version = M.SCHEMA_VERSION,
        game_version = G and G.VERSION or nil,
        language = G and G.SETTINGS and G.SETTINGS.language or nil,
        stage = stage,
        stage_name = stage_name,
        state = state,
        state_name = state_name,
        state_complete = (G and G.STATE_COMPLETE) and true or false,
        uptime = (G and G.TIMERS and G.TIMERS.UPTIME) or 0,
        ready = ready,
    }

    if stage_name == "MAIN_MENU" then
        out.menu = build_menu_info()
        return out
    end

    if stage_name == "RUN" and G.GAME then
        out.run = build_run_info()
        out.blind = build_blind_info()

        if G.hand then
            out.hand = {
                limit = G.hand.config and G.hand.config.card_limit or 0,
                highlight_limit = G.hand.config and G.hand.config.highlighted_limit or 5,
                sort = (G.hand.config and G.hand.config.sort) or G.GAME.sort or "desc",
                cards = serialize_cardarea(G.hand, "hand", true),
            }
        end

        if G.jokers then
            out.jokers = {
                limit = G.jokers.config and G.jokers.config.card_limit or 0,
                cards = serialize_cardarea(G.jokers, "jokers", false),
            }
        end

        if G.consumeables then
            out.consumeables = {
                limit = G.consumeables.config and G.consumeables.config.card_limit or 0,
                cards = serialize_cardarea(G.consumeables, "consumeables", false),
            }
        end

        if G.deck then
            out.deck = {
                remaining = G.deck.cards and #G.deck.cards or 0,
                total = G.playing_cards and #G.playing_cards or 0,
                discarded = (G.discard and G.discard.cards) and #G.discard.cards or 0,
                played = (G.play and G.play.cards) and #G.play.cards or 0,
            }
        end

        if state_name == "ROUND_EVAL" then
            out.round_eval = {
                ready = ready.round_eval_ready,
                cash_out_dollars = (G.GAME.current_round and G.GAME.current_round.dollars) or 0,
            }
        end

        if state_name == "SHOP" or (G.shop and not G.shop.REMOVED) then
            local cr = G.GAME.current_round or {}
            local reroll_cost = cr.reroll_cost or 5
            local budget = (G.GAME.dollars or 0) - (G.GAME.bankrupt_at or 0)
            out.shop = {
                ready = ready.shop_ready,
                reroll_cost = reroll_cost,
                free_rerolls = cr.free_rerolls or 0,
                can_reroll = (reroll_cost == 0) or (budget >= reroll_cost),
                jokers = serialize_cardarea(G.shop_jokers, "shop", false),
                vouchers = serialize_cardarea(G.shop_vouchers, "shop", false),
                boosters = serialize_cardarea(G.shop_booster, "shop", false),
            }
        end

        if PACK_STATE_KEYS[state_name] then
            local can_skip = (G.pack_cards and G.pack_cards.cards and G.pack_cards.cards[1] ~= nil)
                and (
                    state_name == "PLANET_PACK"
                    or state_name == "STANDARD_PACK"
                    or state_name == "BUFFOON_PACK"
                    or (G.hand and (G.hand.cards[1] ~= nil or (G.hand.config and G.hand.config.card_limit <= 0)))
                )
            out.pack = {
                type = state_name,
                ready = ready.pack_ready,
                choices_left = G.GAME.pack_choices or 0,
                can_skip = can_skip and true or false,
                cards = serialize_cardarea(G.pack_cards, "pack", false),
            }
        end
    end

    return out
end

return M
