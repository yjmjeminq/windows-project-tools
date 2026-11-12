"""Run deterministic offline duel regressions with the installed 80460 engine."""

import argparse
import ctypes as c
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys

from build_card_data import ATTRIBUTE, CARD_KIND, ICON, LINK_MARKER, MONSTER_TYPE, PORT_DIRECTORY, index_dat, packed_stat
from repair_pc_card_families import ENGINE_HASH, decode_card_groups


CARD_KINDS = CARD_KIND | {
    "Spirit": 7, "TunerNormal": 15, "Synchro": 17, "Xyz": 22, "Pendulum": 25,
    "TunerEffectSpecialSummonOnly": 30, "TunerFlipEffect": 32, "PendulumFlipEffect": 35,
    "SynchroPendulumEffect": 36, "RitualSpiritEffect": 38, "Link": 42,
    "PendulumTunerNormal": 44, "PendulumSpiritEffect": 45,
}
PENDULUM_KINDS = {25, 26, 33, 34, 35, 36, 40, 41, 44, 45}
XYZ_KINDS = {22, 23, 34}
LINK_KINDS = {42, 43}
RACES = MONSTER_TYPE | {"Illusion": 26, "Spell": 30, "Trap": 31}
ATTRIBUTES = ATTRIBUTE | {"Special": 0, "Spell": 8, "Trap": 9}

HAND, EXTRA, DECK, GRAVE, BANISHED = 13, 14, 15, 16, 17
SPECIAL_SUMMON, ACTIVATE, NORMAL_SUMMON, PLACE_PENDULUM, SELECT_TARGET, DRAW = 2, 3, 4, 8, 12, 13
MAIN_PHASE, END_PHASE = 2, 5
PLAYER_STRIDE = 3548
LIST_OFFSET = 15824
DIALOG_KIND, DIALOG_OWNER = 15508, 15512
INPUT_MODE, INPUT_ACTIVE, ASKED_PLAYER = 15568, 15580, 15616
CARD_PILES = {HAND: (484, 12), DECK: (964, 16), GRAVE: (2044, 20), EXTRA: (1444, 24), BANISHED: (2644, 28)}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def property_words(cid, kind, attribute, level, attack, defense, icon, race, scale):
    star = 0 if kind in (13, 14) else 2 if kind in XYZ_KINDS else 3 if kind in LINK_KINDS else 1
    return (cid | kind << 16 | attribute << 22 | level << 26 | star << 30,
            attack | defense << 9 | icon << 18 | race << 21 | scale << 27)


def installed_properties(project, stock, engine_dir):
    properties = [(0, 0)]
    cards = {}
    for a, b in list(struct.iter_unpack("<II", stock["bin/card_prop.bin"].read()))[1:]:
        properties.append(property_words(a & 0x3FFF, (b >> 1) & 63, (b >> 7) & 15, (b >> 11) & 15,
                                         (a >> 14) & 511, (a >> 23) & 511, (b >> 15) & 7,
                                         (b >> 18) & 31, (b >> 23) & 15))
    mods = project / "Mods"
    for mod in read_json(mods / "modlist.json")["mods"]:
        path = mods / mod["id"] / "Yu-Gi-Oh-Ex/cards.json"
        if not mod["enabled"] or not path.is_file():
            continue
        for row in read_json(path)["cards"]:
            cid = row.get("konamiId", row["id"] + 20000)
            kind = CARD_KINDS[row["kind"]]
            if kind in (13, 14):
                type_name = row["kind"]
                prop = property_words(cid, kind, ATTRIBUTES[type_name], 0, 0, 0, ICON[row["icon"]],
                                      RACES[type_name], 0)
            else:
                defense = (sum(LINK_MARKER[mark] for mark in row["linkmarkers"])
                           if kind in LINK_KINDS else packed_stat(row.get("def", 0)))
                prop = property_words(cid, kind, ATTRIBUTES[row["attribute"]], row["level"],
                                      packed_stat(row.get("atk", 0)), defense, 0, RACES[row["type"]],
                                      row.get("scale", 0) if kind in PENDULUM_KINDS else 0)
            properties.append(prop)
            cards[cid] = row

    by_id = {a & 0xFFFF: i for i, (a, _) in enumerate(properties) if i}
    if len(by_id) != len(properties) - 1:
        raise ValueError("Duplicate engine card IDs")
    override_path = engine_dir / "CARD_PropOverrides_80460.json"
    if override_path.is_file():
        for override in read_json(override_path)["cards"]:
            i = by_id[override["id"]]
            a, b = properties[i]
            if "kind" in override:
                a = (a & ~(63 << 16)) | override["kind"] << 16
            if "rank" in override:
                a = (a & 0x03FFFFFF) | override["rank"] << 26 | 2 << 30
            properties[i] = (a, b)
    return properties, by_id, cards


class OfflineDuel:
    def __init__(self, project):
        engine = project / "Mods/Master Duel Engine"
        dll = engine / "duel.dll"
        if sha256(dll.read_bytes()).hexdigest() != ENGINE_HASH:
            raise ValueError("These fixtures require the installed 80460 duel engine")
        stock = index_dat(project / "YGO_2020.dat")
        properties, self.by_id, self.cards = installed_properties(project, stock, engine)
        self.dll = c.WinDLL(str(dll.resolve(strict=True)))
        self.functions = {}
        work = self.function("SetWorkMemory", c.c_int64, c.c_void_p)
        self.work = c.create_string_buffer(work(None))
        if work(self.work) != 0:
            raise RuntimeError("Engine work memory could not be initialized")

        first = properties[1][0] & 0xFFFF
        last = max(self.by_id)
        lookup = [0] * (last - first + 1)
        for cid, i in self.by_id.items():
            lookup[cid - first] = i
        if properties[-1][0] & 0xFFFF != last:
            properties.append((last, 0))
        self.properties = properties
        self.named_data = (engine / "CARD_Named_80460.bin").read_bytes()
        self.buffers = [
            c.create_string_buffer(b"".join(struct.pack("<II", *pair) for pair in properties)),
            c.create_string_buffer(struct.pack(f"<{len(lookup)}H", *lookup)),
            c.create_string_buffer(stock["bin/card_genre.bin"].read().ljust(len(properties) * 8, b"\0")),
            c.create_string_buffer(self.named_data),
            c.create_string_buffer((engine / "CARD_Same_80460.bin").read_bytes()),
            c.create_string_buffer(stock["bin/card_link.bin"].read()),
        ]
        props, indexes, genres, named, same, links = self.buffers
        self.function("SetCardProperty", None, c.c_void_p, c.c_int)(props, len(properties) * 8)
        self.function("SetInternalID", None, c.c_void_p)(indexes)
        self.function("SetCardGenre", None, c.c_void_p)(genres)
        self.function("SetCardNamed", None, c.c_void_p)(named)
        self.function("SetCardSame", None, c.c_void_p, c.c_int)(same, len(same) - 1)
        self.function("SetCardLink", None, c.c_void_p, c.c_int)(links, len(links) - 1)
        self.act = self.function("DuelSysAct", c.c_int64)
        self.phase = self.function("DuelGetCurrentPhase", c.c_int)
        self.turn = self.function("DuelGetTurnNum", c.c_int)
        self.mask = self.function("DuelComGetCommandMask", c.c_int, c.c_int, c.c_int, c.c_int)
        self.command = self.function("DuelComDoCommand", None, c.c_int, c.c_int, c.c_int, c.c_int)
        self.answer = self.function("DuelDlgSetResult", None, c.c_int)
        self.events = []
        self.dialog_answered = False
        animation_type = c.CFUNCTYPE(c.c_int64, c.c_int64, c.c_int64, c.c_uint32, c.c_int64)
        busy_type = c.CFUNCTYPE(c.c_int64, c.c_uint32)
        self.animate = animation_type(self.on_animation)
        self.busy = busy_type(self.on_busy)
        self.function("SetEffectDelegate", None, animation_type, busy_type)(self.animate, self.busy)

    def function(self, name, result, *args):
        if name not in self.functions:
            proc = getattr(self.dll, "DLL_" + name)
            proc.restype = result
            proc.argtypes = args
            self.functions[name] = proc
        return self.functions[name]

    def u16(self, offset):
        return struct.unpack_from("<H", self.work, offset)[0]

    def u32(self, offset):
        return struct.unpack_from("<I", self.work, offset)[0]

    def pile(self, player, zone):
        start, count = CARD_PILES[zone]
        offset = player * PLAYER_STRIDE
        return [self.u16(offset + start + 4 * i) for i in range(self.u32(offset + count))]

    def field(self, player):
        offset = player * PLAYER_STRIDE
        return [self.u16(offset + 92 + 28 * zone) for zone in range(13)]

    def face(self, player, zone):
        return self.function("DuelGetCardFace", c.c_int, c.c_int, c.c_int, c.c_int)(player, zone, 0)

    def lp(self, player):
        return self.function("DuelGetLP", c.c_int, c.c_int)(player)

    def list_is_open(self):
        return self.u16(LIST_OFFSET + 10) > 0 and self.u32(DIALOG_KIND) == 20 + self.u16(LIST_OFFSET + 2)

    def on_animation(self, code, a, b, d):
        self.events.append((code, a, b, d, self.u32(DIALOG_KIND)))
        if code in (55, 56):
            self.dialog_answered = False
        return 0

    def on_busy(self, code):
        # An informational card-list prompt appears before the real selection.
        waiting = self.list_is_open() or self.u32(DIALOG_KIND) == 6
        return int(code in (55, 56) and waiting and not self.dialog_answered)

    def start(self, hand, rest=(), opponent=(), extra=(), opponent_is_human=False):
        self.function("DuelSysClearWork", None)()
        filler = [a & 0xFFFF for a, _ in self.properties[1:] if (a >> 16) & 63 == 0 and 1 <= (a >> 26) & 15 <= 4]
        first_deck = [*hand, *rest]
        second_deck = list(opponent)
        for player, ids in enumerate((first_deck, second_deck)):
            ids.extend(cid for cid in filler if cid not in ids and len(ids) < 40)
            if len(ids) != 40 or any(cid not in self.by_id for cid in ids):
                raise ValueError("Invalid fixture deck")
            extra_ids = extra if player == 0 else ()
            added = (c.c_uint32 * len(extra_ids))(*extra_ids)
            deck = (c.c_uint32 * len(ids))(*ids)
            self.function("DuelSysSetDeck2", None, c.c_int, c.c_void_p, c.c_int, c.c_void_p,
                          c.c_int, c.c_void_p, c.c_int)(player, deck, len(ids), added, len(extra_ids), None, 0)
            self.function("DuelSetPlayerType", None, c.c_int, c.c_int)(player, int(player == 1 and not opponent_is_human))
            self.function("DuelSetCpuParam", None, c.c_int, c.c_int)(player, 0)
        self.function("DuelSetRandomSeed", None, c.c_int)(20261112)
        self.function("DuelSetFirstPlayer", None, c.c_int)(0)
        self.function("DuelSysInitCustom", c.c_int64, c.c_int64, c.c_int, c.c_int, c.c_int,
                      c.c_int, c.c_int, c.c_int)(0, 0, 8000, 8000, 5, 5, 1)
        self.advance(lambda: self.ready(0), "first main phase")

    def ready(self, player):
        return (self.phase() == MAIN_PHASE and self.u32(INPUT_MODE) == 2
                and self.u32(INPUT_ACTIVE) != 0 and self.u32(ASKED_PLAYER) == player)

    def advance(self, predicate, description):
        for _ in range(1600):
            if predicate():
                return
            if self.u32(INPUT_MODE) == 7 and self.u32(INPUT_ACTIVE):
                self.function("DuelComDefaultLocation", None)()
            elif self.u32(DIALOG_KIND) == 4 and not self.dialog_answered:
                self.reply(0)
            elif self.u32(INPUT_MODE) == 4 and self.u32(INPUT_ACTIVE):
                self.function("DuelComCancelCommand2", c.c_int, c.c_int)(0)
            self.act()
        raise AssertionError(f"{description} timed out. phase={self.phase()} mode={self.u32(INPUT_MODE)} "
                             f"dialog={self.u32(DIALOG_KIND)} events={self.events[-6:]}")

    def play(self, card_id, command=ACTIVATE, player=0):
        self.advance(lambda: self.ready(player), f"player {player} ready")
        index = self.pile(player, HAND).index(card_id)
        mask = self.mask(player, HAND, index)
        if not mask & (1 << command):
            raise AssertionError(f"Card {card_id} cannot use command {command} (mask {mask:#x})")
        self.command(player, HAND, index, command)

    def activate_on_field(self, card_id, player=0):
        self.advance(lambda: self.ready(player) and card_id in self.field(player),
                     f"field effect {card_id} available")
        zone = self.field(player).index(card_id)
        assert self.mask(player, zone, 0) & (1 << ACTIVATE), (card_id, zone)
        self.command(player, zone, 0, ACTIVATE)

    def list_items(self, description):
        self.advance(lambda: self.list_is_open() and not self.dialog_answered, description)
        count = self.u16(LIST_OFFSET + 10)
        item = self.function("DuelListGetItemID", c.c_int, c.c_int)
        location = self.function("DuelListGetItemFrom", c.c_int, c.c_int)
        return [(item(i), location(i)) for i in range(count)]

    def submit_list(self, indexes):
        assert self.list_is_open() and not self.dialog_answered
        assert len(set(indexes)) == len(indexes)
        set_index = self.function("DuelListSetIndex", None, c.c_int)
        set_order = self.function("DuelListSetCardExData", None, c.c_int, c.c_int)
        for order, index in enumerate(indexes, start=1):
            assert 0 <= index < self.u16(LIST_OFFSET + 10)
            set_index(index)
            set_order(index, order)
        self.reply(len(indexes))

    def choose(self, card_id, zone=None):
        choices = self.list_items(f"list for {card_id}")
        index = next((i for i, (cid, place) in enumerate(choices)
                      if cid == card_id and (zone is None or zone == place)), None)
        if index is None:
            raise AssertionError(f"Card {card_id} absent from the selection {choices[:20]}")
        self.submit_list([index])
        return index, choices

    def reply(self, result):
        self.answer(result)
        self.dialog_answered = True

    def choose_hand_target(self, card_id, player=0):
        self.advance(lambda: self.u32(INPUT_MODE) == 8 and self.u32(INPUT_ACTIVE),
                     f"hand target {card_id}")
        hand = self.pile(player, HAND)
        mask = [self.mask(player, HAND, i) for i in range(len(hand))]
        index = hand.index(card_id)
        assert mask[index] & (1 << SELECT_TARGET), (card_id, hand, mask)
        self.command(player, HAND, index, SELECT_TARGET)
        return [cid for cid, flags in zip(hand, mask) if flags & (1 << SELECT_TARGET)]

    def choose_field_target(self, card_id, player=0):
        self.advance(lambda: self.u32(INPUT_MODE) in (8, 9) and self.u32(INPUT_ACTIVE),
                     f"field target {card_id}")
        zone = self.field(player).index(card_id)
        assert self.mask(player, zone, 0) & (1 << SELECT_TARGET), (card_id, zone)
        self.command(player, zone, 0, SELECT_TARGET)

    def wait_for_grave(self, card_id, player=0):
        self.advance(lambda: card_id in self.pile(player, GRAVE), f"card {card_id} resolves")

    def end_turn(self, player):
        self.advance(lambda: self.ready(player), "end turn from the main phase")
        assert self.function("DuelComGetMovablePhase", c.c_int)() & (1 << END_PHASE)
        self.function("DuelComMovePhase", None, c.c_int)(END_PHASE)
        self.advance(lambda: self.u32(INPUT_MODE) == 1 and self.u32(INPUT_ACTIVE), "draw prompt")
        next_player = 1 - player
        assert self.u32(ASKED_PLAYER) == next_player and self.mask(next_player, DECK, 0) & (1 << DRAW)
        self.command(next_player, DECK, 0, DRAW)
        self.advance(lambda: self.ready(next_player), "next main phase")

    def summon_from_extra(self, card_id, materials):
        self.advance(lambda: self.ready(0), "Extra Deck summon available")
        assert self.mask(0, EXTRA, 0) & (1 << SPECIAL_SUMMON)
        self.command(0, EXTRA, 0, SPECIAL_SUMMON)
        index, _ = self.choose(card_id, EXTRA)
        for material in materials:
            self.choose_field_target(material)
        self.advance(lambda: self.u32(DIALOG_KIND) == 14, "Extra Deck material confirmation")
        self.reply(1)
        return index


def check_catalog(duel):
    internal = duel.function("CardGetInternalID", c.c_int, c.c_int)
    kind = duel.function("CardGetKind", c.c_int, c.c_int)
    attack = duel.function("CardGetAtk", c.c_int, c.c_int)
    attr = duel.function("CardGetAttr", c.c_int, c.c_int)
    race = duel.function("CardGetType", c.c_int, c.c_int)
    scale = duel.function("CardGetScaleL", c.c_int, c.c_int)
    level_types = [duel.function(name, c.c_int, c.c_int)
                   for name in ("CardGetLevel", "CardGetRank", "CardGetLinkNum")]
    for cid, index in duel.by_id.items():
        a, b = duel.properties[index]
        assert internal(cid) == index and kind(cid) == (a >> 16) & 63, cid
        assert attr(cid) == (a >> 22) & 15 and race(cid) == (b >> 21) & 31, cid
        assert scale(cid) == (b >> 27) & 15, cid
        for field, get_value in enumerate(level_types, start=1):
            assert get_value(cid) == ((a >> 26) & 15 if field == a >> 30 else 0), cid
        if b & 511 != 511:
            assert attack(cid) == (b & 511) * 10, cid

    check_name = duel.function("CardCheckName", c.c_int, c.c_int, c.c_int)
    groups = decode_card_groups(duel.named_data)
    for group, members in enumerate(groups):
        assert all(check_name(cid, group) for cid in members), group
    return {"scenarios": 0, "card_records": len(duel.by_id), "mod_cards": len(duel.cards),
            "archetype_memberships": sum(map(len, groups))}


def reinforcement(duel):
    duel.start([5328, 4007, 4642, 4037, 4047], [4084, 23345, 23323])
    duel.play(5328)
    index, choices = duel.choose(23345, DECK)
    assert index > 0 and all(cid != 23323 for cid, _ in choices)
    duel.wait_for_grave(5328)
    assert 23345 in duel.pile(0, HAND) and 23345 not in duel.pile(0, DECK)
    return {"search_spell": 5328, "card_added": 23345, "choice": index + 1}


def named_search(duel):
    expected = [6310, 17403, 19719, 22593, 6311]
    targets = [17403, 19719, 6311]
    for target in targets:
        duel.start([6672, 4007, 4642, 4037, 4047], [*expected, 23345], extra=[23147])
        duel.play(6672)
        index, choices = duel.choose(target, DECK)
        assert index > 0 and choices == [(cid, DECK) for cid in expected]
        duel.wait_for_grave(6672)
        assert target in duel.pile(0, HAND) and target not in duel.pile(0, DECK)

    # A Hero Lives uses the same archetype with a Level 4 limit and the Main Deck only.
    duel.start([7187, 4007, 4642, 4037, 4047], [6310, 22593, 17403, 6311, 6658], extra=[23147])
    duel.play(7187)
    _, choices = duel.choose(22593, DECK)
    assert choices == [(6310, DECK), (22593, DECK), (6311, DECK)]
    duel.advance(lambda: 22593 in duel.field(0), "A Hero Lives resolves")
    assert duel.pile(0, EXTRA) == [23147] and 17403 in duel.pile(0, DECK)
    assert duel.lp(0) == 4000
    return {"scenarios": len(targets) + 1, "search_spell": 6672, "cards_added_in_separate_duels": targets,
            "level_limited_summon": 22593}


def more_archetype_searches(duel):
    searches = [
        (9122, [7687, 18789, 7700, 23345], [7687, 18789, 7700]),
        (9131, [7527, 19621, 7529, 19622, 23345], [7527, 19621, 7529]),
        (7868, [4008, 4009, 4010, 7591, 19865, 7592, 19918, 23345], [7591, 19865, 7592]),
        (13671, [13670, 21480, 13672, 17553, 23345], [13670, 21480, 13672, 17553]),
        (11446, [11439, 21768, 11440, 23345], [11439, 21768, 11440]),
        (14410, [14404, 22499, 14406, 21074, 23345], [14404, 22499, 14406]),
        (7460, [7284, 20756, 7285, 20797, 7282, 23345], [7284, 20756, 7285]),
        (8978, [8951, 21904, 8952, 7250, 23345], [8951, 21904, 8952]),
        (14244, [13889, 18908, 13890, 18913, 23345], [13889, 18908, 13890]),
        (23385, [15097, 23346, 15098, 23345], [15097, 23346, 15098]),
    ]
    for spell, deck, expected in searches:
        duel.start([spell, 4007, 4642, 4037, 4047], deck)
        duel.play(spell)
        if spell == 11446:
            duel.advance(lambda: duel.list_is_open() or duel.ready(0), "Dark Contract placed")
            if not duel.list_is_open():
                duel.activate_on_field(spell)
        if spell == 14244:
            duel.advance(lambda: duel.u32(DIALOG_KIND) == 6, "Salamangreat Circle effect choice")
            duel.reply(0)

        target = expected[1]
        index, choices = duel.choose(target, DECK)
        assert index == 1 and choices == [(cid, DECK) for cid in expected], (spell, choices)
        duel.advance(lambda: target in duel.pile(0, HAND), f"{spell} search resolves")
        assert target not in duel.pile(0, DECK)
        if spell == 7868:
            assert {4008, 4009, 4010} <= set(duel.pile(0, GRAVE))
    return {"scenarios": len(searches), "searches": {spell: expected[1] for spell, _, expected in searches}}


def red_eyes_search(duel):
    duel.start([12650, 4007, 4642, 4037, 4047], [4088, 17243, 17388, 11843, 11898, 12650, 23345])
    duel.play(12650)
    index, costs = duel.choose(17243, DECK)
    assert index == 1 and costs == [(4088, DECK), (17243, DECK), (17388, DECK)]
    _, choices = duel.choose(11843, DECK)
    assert set(choices) == {(11843, DECK), (11898, DECK)}
    duel.advance(lambda: 11843 in duel.pile(0, HAND), "Red-Eyes Insight resolves")
    assert 17243 in duel.pile(0, GRAVE)
    return {"spell": 12650, "cost": 17243, "added": 11843}


def onomatopaira_search(duel):
    duel.start([10953, 4007, 4642, 4037, 4047], [9563, 21412, 21773, 9618, 9619, 9852, 23345])
    duel.play(10953)
    duel.choose_hand_target(4007)
    index, choices = duel.choose(21773, DECK)
    assert index == 2 and choices == [(cid, DECK) for cid in (9563, 21412, 21773, 9618, 9619, 9852)]
    duel.advance(lambda: 21773 in duel.pile(0, HAND), "Onomatopaira resolves")
    assert 4007 in duel.pile(0, GRAVE) and 21773 not in duel.pile(0, DECK)
    check_name = duel.function("CardCheckName", c.c_int, c.c_int, c.c_int)
    assert all(check_name(21773, group) for group in (179, 121, 122, 155))
    return {"spell": 10953, "added": 21773}


def utopia_double_search(duel):
    duel.start([11740, 4642, 4007, 4037, 4047], [4008, 9663], extra=[14220, 9575, 17255, 22699])
    duel.play(11740)
    duel.choose(4008, DECK)
    duel.wait_for_grave(11740)
    duel.play(4642, NORMAL_SUMMON)
    duel.summon_from_extra(14220, [4008, 4642])
    duel.activate_on_field(14220)
    duel.choose(4008)
    duel.choose(9663, DECK)
    index, choices = duel.choose(22699, EXTRA)
    assert index == 2 and choices == [(9575, EXTRA), (17255, EXTRA), (22699, EXTRA)]
    duel.advance(lambda: 22699 in duel.field(0), "Utopia Double resolves")
    assert 9663 in duel.pile(0, HAND) and 22699 not in duel.pile(0, EXTRA)
    return {"monster": 14220, "summoned_from_extra": 22699}


def card_name_mention_searches(duel):
    duel.start([21166, 4007, 4642, 4037, 4047], [4030, 19866, 21202, 12768, 23345])
    duel.play(21166, NORMAL_SUMMON)
    cpu = duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)
    cpu(0, 1)
    duel.advance(lambda: duel.list_is_open() and not duel.dialog_answered, "Wight search")
    cpu(0, 0)
    index, choices = duel.choose(19866, DECK)
    assert index == 1 and choices == [(cid, DECK) for cid in (4030, 19866, 21202, 12768)]
    duel.advance(lambda: 19866 in duel.pile(0, HAND), "Wight search resolves")

    duel.start([16752, 4007, 4642, 4037, 4047], [16749, 17135, 16750, 17784, 17822, 23345])
    duel.play(16752)
    duel.activate_on_field(16752)
    index, choices = duel.choose(17135, DECK)
    assert index == 1 and choices == [(cid, DECK) for cid in (16749, 17135, 16750, 17784)]
    duel.choose_hand_target(4007)
    duel.advance(lambda: 17135 in duel.pile(0, HAND) and 4007 in duel.pile(0, GRAVE),
                 "Fateful Adventure resolves")

    duel.start([20397, 8539, 4007, 4642, 4037], [8538, 20393, 20394, 20395, 20396, 20397, 23345])
    duel.play(8539)
    duel.play(20397)
    duel.activate_on_field(20397)
    index, choices = duel.choose(20393, DECK)
    assert index == 1 and choices == [(cid, DECK) for cid in (8538, 20393, 20394, 20395, 20396)]
    duel.advance(lambda: 20393 in duel.pile(0, HAND), "Clear Wall resolves")
    return {"scenarios": 3, "searches": {21166: 19866, 16752: 17135, 20397: 20393}}


def s_force_summon(duel):
    duel.start([15702, 15705, 4007, 4642, 4037], [15703, 22969, 23345])
    duel.play(15702, NORMAL_SUMMON)
    duel.advance(lambda: duel.ready(0) and 15702 in duel.field(0), "S-Force Normal Summon")
    zone = duel.field(0).index(15702)
    assert duel.mask(0, zone, 0) & (1 << ACTIVATE)
    duel.command(0, zone, 0, ACTIVATE)
    assert duel.choose_hand_target(15705) == [15705]
    index, choices = duel.choose(22969, DECK)
    assert index == 1 and choices == [(15703, DECK), (22969, DECK)]
    duel.advance(lambda: 22969 in duel.field(0), "S-Force Special Summon")
    assert 15702 in duel.pile(0, HAND) and 15705 in duel.pile(0, BANISHED)
    assert 22969 not in duel.pile(0, DECK) and duel.face(0, duel.field(0).index(22969)) == 1
    return {"activated": 15702, "cost": 15705, "summoned": 22969, "choice": index + 1}


def destiny_hero_effect(duel):
    duel.start([23345, 6658, 4007, 4642, 4037], [4837])
    assert not duel.mask(0, HAND, 0) & (1 << ACTIVATE)
    duel.play(6658, NORMAL_SUMMON)
    duel.advance(lambda: duel.ready(0) and 6658 in duel.field(0), "Destiny HERO Normal Summon")
    duel.play(23345)
    duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)(0, 1)
    duel.choose(4837, DECK)
    duel.advance(lambda: 4837 in duel.pile(0, HAND), "Polymerization search resolves")
    assert 23345 in duel.pile(0, GRAVE) and 4837 not in duel.pile(0, DECK)
    return {"new_hero": 23345, "required_older_hero": 6658, "destroyed": 23345, "searched_spell": 4837}


def ancient_secrets(duel):
    duel.start([23497, 4007, 4642, 4037, 4047], [4084, 23128, 4007])
    duel.play(23497)
    index, choices = duel.choose(23128, DECK)
    assert index > 0 and (4007, HAND) in choices and (4007, DECK) not in choices
    duel.wait_for_grave(23497)
    assert 23128 in duel.field(0) and 23128 not in duel.pile(0, DECK)
    assert duel.face(0, duel.field(0).index(23128)) == 1
    return {"spell": 23497, "summoned_in_defense": 23128, "choice": index + 1}


def reborn(duel):
    duel.start([5236, 4842, 4007, 4642, 4037], [4084, 23323])
    duel.play(5236)
    index, _ = duel.choose(23323, DECK)
    assert index > 0
    duel.wait_for_grave(5236)
    assert 23323 in duel.pile(0, GRAVE)
    duel.play(4842)
    duel.choose(23323, GRAVE)
    duel.wait_for_grave(4842)
    assert 23323 in duel.field(0) and 23323 not in duel.pile(0, GRAVE)
    return {"grave_spells": [5236, 4842], "revived": 23323}


def draw_two(duel):
    duel.start([4844, 4007, 4642, 4037, 4047], [23345, 23128])
    before = len(duel.pile(0, DECK))
    duel.play(4844)
    duel.wait_for_grave(4844)
    assert len(duel.pile(0, DECK)) == before - 2 and len(duel.pile(0, HAND)) == 6
    assert {23345, 23128} <= set(duel.pile(0, HAND))
    return {"draw_spell": 4844, "drawn_new_cards": [23345, 23128]}


def ash_negation(duel):
    duel.start([23497, 4642, 4037, 4047, 4007], [23128],
               opponent=[12950, 4642, 4037, 4047, 4007], opponent_is_human=True)
    duel.play(23497)
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 4 and duel.u32(DIALOG_OWNER) == 1,
                 "Ash Blossom response prompt")
    duel.reply(1)
    duel.advance(lambda: duel.u32(INPUT_MODE) == 5 and duel.u32(INPUT_ACTIVE)
                 and duel.u32(ASKED_PLAYER) == 1 and duel.mask(1, HAND, 0) & (1 << ACTIVATE),
                 "Ash Blossom response to Ancient Secrets")
    assert duel.pile(1, HAND)[0] == 12950
    duel.command(1, HAND, 0, ACTIVATE)
    duel.wait_for_grave(23497)
    assert 12950 in duel.pile(1, GRAVE) and 23128 in duel.pile(0, DECK)
    assert not any(duel.field(0)[:7])
    return {"spell_negated": 23497, "negated_by": 12950}


def dark_summon(duel):
    duel.start([23500, 4930, 4007, 4642, 4037])
    mask = duel.mask(0, HAND, 0)
    assert not mask & (1 << NORMAL_SUMMON), mask
    duel.play(23500)
    choices = duel.choose_hand_target(4930)
    assert 4007 not in choices
    duel.advance(lambda: 4930 in duel.field(0) and duel.ready(0), "DARK monster Special Summon")
    assert 23500 in duel.pile(0, HAND)
    return {"revealed": 23500, "summoned": 4930}


def ritual_and_pendulum(duel):
    pendulum_scale = duel.function("CardGetScaleL", c.c_int, c.c_int)
    kind = duel.function("CardGetKind", c.c_int, c.c_int)
    scales = {17145: 4, 20595: 0, 20937: 5, 21627: 0, 22134: 0, 22539: 9}
    assert {cid: pendulum_scale(cid) for cid in scales} == scales
    assert all(kind(cid) == 52 for cid in scales)

    duel.start([12174, 17145, 11213, 4007, 4642])
    duel.play(12174)
    duel.choose_hand_target(17145)
    duel.choose_hand_target(11213)
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 14, "ritual material confirmation")
    duel.reply(1)
    duel.wait_for_grave(12174)
    assert 17145 in duel.field(0) and 11213 in duel.pile(0, GRAVE)

    duel.start([17145, 4007, 4642, 4037, 4047], [12174])
    duel.play(17145, PLACE_PENDULUM)
    duel.advance(lambda: duel.ready(0) and 17145 in duel.field(0), "pendulum placement")
    assert duel.field(0).index(17145) in (7, 11) and 17145 not in duel.pile(0, HAND)
    duel.function("DuelComMovePhase", None, c.c_int)(END_PHASE)
    duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)(0, 1)
    duel.choose(12174, DECK)
    duel.advance(lambda: {17145, 12174} <= set(duel.pile(0, HAND)), "Pendulum effect resolves")
    assert 17145 not in duel.field(0) and 12174 not in duel.pile(0, DECK)
    return {"scenarios": 2, "ritual_monster": 17145, "ritual_spell_used_and_searched": 12174, "scales": scales}


def synchro_effect(duel):
    duel.start([6995, 8933, 4007, 4642, 4037], [4008],
               opponent=[4844, 5236, 4007, 4642, 4037], extra=[22713, 23501], opponent_is_human=True)
    duel.end_turn(0)
    duel.play(4844, player=1)
    duel.wait_for_grave(4844, player=1)
    duel.play(5236, player=1)
    duel.choose(duel.pile(1, DECK)[1], DECK)
    duel.wait_for_grave(5236, player=1)
    opponent_grave = set(duel.pile(1, GRAVE))
    assert len(opponent_grave) == 3
    duel.end_turn(1)

    duel.play(6995)
    duel.choose_hand_target(4007)
    duel.wait_for_grave(6995)
    duel.play(8933, NORMAL_SUMMON)
    duel.advance(lambda: duel.ready(0) and 8933 in duel.field(0), "tuner Normal Summon")
    index = duel.summon_from_extra(23501, [8933, 4007])
    assert index == 1
    # Have the engine choose the optional trigger, discard, and banish targets.
    duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)(0, 1)
    duel.advance(lambda: len(duel.pile(1, BANISHED)) == 2, "Synchro banish effect resolves")
    banished = set(duel.pile(1, BANISHED))
    assert 23501 in duel.field(0) and duel.pile(0, EXTRA) == [22713]
    assert set(duel.pile(0, GRAVE)) == {6995, 4007, 8933, 4008}
    assert banished == opponent_grave - set(duel.pile(1, GRAVE))
    return {"summoned": 23501, "materials": [8933, 4007], "choice": index + 1,
            "discarded": 4008, "banished": sorted(banished)}


def blackwing_synchro(duel):
    duel.start([11740, 7219, 7849, 8011, 4037], [4642], extra=[7697, 22713], opponent_is_human=True)
    duel.play(11740)
    duel.choose(4642, DECK)
    duel.wait_for_grave(11740)
    duel.play(7219)
    duel.wait_for_grave(7219)
    duel.play(7849, NORMAL_SUMMON)
    duel.summon_from_extra(7697, [7849, 4642])
    duel.play(8011, NORMAL_SUMMON)
    duel.summon_from_extra(22713, [8011, 7697])
    duel.advance(lambda: duel.ready(0) and 22713 in duel.field(0), "Blackwing Synchro Summon")
    assert {8011, 7697} <= set(duel.pile(0, GRAVE))
    zone = duel.field(0).index(22713)
    is_tuner = duel.function("DuelIsThisTunerMonster", c.c_int, c.c_int, c.c_int)
    pierce = duel.function("DuelGetThisMonsterPierce", c.c_int, c.c_int, c.c_int)
    assert is_tuner(0, zone) == 1 and pierce(0, zone) == 1

    get_stats = duel.function("DuelGetCardBasicVal", None, c.c_int, c.c_int, c.c_int, c.c_void_p)
    stats = (c.c_int * 16)()
    get_stats(0, zone, 0, stats)
    assert stats[1] == 5600
    duel.end_turn(0)
    get_stats(0, zone, 0, stats)
    assert stats[1] == 3000
    return {"summoned": 22713, "materials": [8011, 7697], "tuner": True,
            "pierce": True, "attack_before_and_after_end_phase": [5600, 3000]}


def xyz_effect(duel):
    duel.start([11740, 4642, 4007, 4037, 4047], [4012, 4008],
               opponent=[4642, 4007, 4037, 4047, 4844], extra=[23502], opponent_is_human=True)
    duel.end_turn(0)
    duel.play(4642, NORMAL_SUMMON, player=1)
    duel.advance(lambda: duel.ready(1) and 4642 in duel.field(1), "opponent Normal Summon")
    unique_id = duel.function("DuelGetCardUniqueID", c.c_int, c.c_int, c.c_int, c.c_int)
    target_id = unique_id(1, duel.field(1).index(4642), 0)
    duel.end_turn(1)

    duel.play(11740)
    duel.choose(4008, DECK)
    duel.wait_for_grave(11740)
    duel.play(4642, NORMAL_SUMMON)
    duel.summon_from_extra(23502, [4008, 4642])
    duel.advance(lambda: duel.ready(0) and 23502 in duel.field(0), "Xyz Summon")

    zone = duel.field(0).index(23502)
    overlay_count = duel.function("DuelGetThisCardOverlayNum", c.c_int, c.c_int, c.c_int)
    overlay_id = duel.function("DuelGetThisCardOverlayUniqueID", c.c_int, c.c_int, c.c_int, c.c_int)
    assert overlay_count(0, zone) == 2 and target_id not in (overlay_id(0, zone, 1), overlay_id(0, zone, 2))
    assert duel.mask(0, zone, 0) & (1 << ACTIVATE)
    duel.command(0, zone, 0, ACTIVATE)
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 6, "Xyz effect mode")
    duel.reply(1)
    duel.choose(4008)
    duel.choose_field_target(4642, player=1)
    duel.advance(lambda: duel.ready(0), "Xyz effect resolves")
    assert 4008 in duel.pile(0, GRAVE) and 4642 not in duel.field(1)
    assert overlay_count(0, zone) == 2 and target_id in (overlay_id(0, zone, 1), overlay_id(0, zone, 2))
    return {"summoned": 23502, "detached": 4008, "opponent_monster_attached": 4642}


CASES = {
    "catalog": check_catalog,
    "reinforcement": reinforcement,
    "named_search": named_search,
    "more_archetype_searches": more_archetype_searches,
    "red_eyes_search": red_eyes_search,
    "onomatopaira_search": onomatopaira_search,
    "utopia_double_search": utopia_double_search,
    "card_name_mention_searches": card_name_mention_searches,
    "s_force_summon": s_force_summon,
    "destiny_hero_effect": destiny_hero_effect,
    "ancient_secrets": ancient_secrets,
    "reborn": reborn,
    "draw_two": draw_two,
    "ash_negation": ash_negation,
    "dark_summon": dark_summon,
    "ritual_and_pendulum": ritual_and_pendulum,
    "synchro_effect": synchro_effect,
    "blackwing_synchro": blackwing_synchro,
    "xyz_effect": xyz_effect,
}


def run_cases(cases, description, script):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--case", choices=cases)
    args = parser.parse_args()
    if args.case:
        print(json.dumps({"case": args.case, "scenarios": 1, **cases[args.case](OfflineDuel(args.project))}))
        return

    failed = []
    for name in cases:
        try:
            result = subprocess.run([sys.executable, str(Path(script).resolve()), "--project",
                                     str(args.project), "--case", name], timeout=15, check=False)
        except subprocess.TimeoutExpired:
            failed.append(name)
            print(f"{name}: engine process timed out", flush=True)
        else:
            if result.returncode:
                failed.append(name)
    if failed:
        raise SystemExit(f"Failed cases: {', '.join(failed)}")


if __name__ == "__main__":
    run_cases(CASES, __doc__, __file__)
