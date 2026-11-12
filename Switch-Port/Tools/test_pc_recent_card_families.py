"""Run offline regressions for recently added card families and support cards."""

import ctypes as c

from test_pc_duel_effects import (
    ACTIVATE, BANISHED, DECK, DIALOG_KIND, EXTRA, GRAVE, HAND, INPUT_ACTIVE, INPUT_MODE,
    NORMAL_SUMMON, SPECIAL_SUMMON, run_cases,
)
from test_pc_effect_paths import (
    FILLER_HAND, SET_MONSTER, SET_TRAP, choose_deck_card, select_effect_option,
)


def ashtra_search_and_trap(duel):
    duel.start([23379, 4642, 5124, 4007, 4047], [23331, 23332, 23395, 23396, 23379, 23345],
               opponent_is_human=True)
    duel.play(4642, SET_MONSTER)
    duel.play(23379)
    duel.activate_on_field(23379)
    duel.choose_field_target(4642)
    assert choose_deck_card(duel, 23395, [23331, 23332, 23395, 23396]) == 2
    duel.advance(lambda: duel.ready(0), "Ashtra search resolves")
    assert 23395 in duel.pile(0, HAND) and 4642 in duel.pile(0, GRAVE)

    duel.play(23395, SET_TRAP)
    duel.end_turn(0)
    duel.end_turn(1)
    duel.activate_on_field(23395)
    select_effect_option(duel, 0)
    duel.advance(lambda: 23395 in duel.field(0)[:7] and duel.ready(0), "Ashtra trap becomes a tuner")
    is_tuner = duel.function("DuelIsThisTunerMonster", c.c_int, c.c_int, c.c_int)
    assert is_tuner(0, duel.field(0).index(23395)) == 1
    return {"scenarios": 1, "searched_and_summoned_as_tuner": 23395}


def ars_magna_search(duel):
    duel.start([23383, *FILLER_HAND], [23340, 23341, 23342, 23399, 23345])
    duel.play(23383)
    duel.activate_on_field(23383)
    assert choose_deck_card(duel, 23341, [23340, 23341, 23342]) == 1
    duel.advance(lambda: duel.ready(0), "Ars Magna monster added to hand")
    assert 23341 in duel.pile(0, HAND) and 23341 not in duel.pile(0, DECK)
    assert not duel.mask(0, duel.field(0).index(23383), 0) & (1 << ACTIVATE)
    return {"scenarios": 1, "searched_monster": 23341}


def atlantis_mentions(duel):
    duel.start([23381, *FILLER_HAND], [23335, 23336, 23337, 23338, 23345, 23382, 5895, 13240])
    duel.play(23381)
    assert choose_deck_card(duel, 23337, [23335, 23336, 23337, 23338]) == 2
    duel.wait_for_grave(23381)
    assert 23337 in duel.pile(0, HAND) and {5895, 13240, 23382} <= set(duel.pile(0, DECK))
    return {"scenarios": 1, "searched_monster_mentioning_atlantis": 23337}


def dark_time_wizard_summon(duel):
    duel.start([23323, *FILLER_HAND], [23324, 23325, 23326, 23345, 23375, 23376, 23392])
    duel.play(23323, NORMAL_SUMMON)
    duel.activate_on_field(23323)
    duel.choose_hand_target(4007)
    select_effect_option(duel, 0)
    assert choose_deck_card(duel, 23326, [23324, 23325, 23326]) == 2
    duel.advance(lambda: 23326 in duel.field(0) and duel.ready(0), "Panther Warrior summons from the deck")
    assert 4007 in duel.pile(0, GRAVE) and 23326 not in duel.pile(0, DECK)
    return {"scenarios": 1, "tributed": 4007, "summoned": 23326}


def blitzclique_trap_and_trigger(duel):
    duel.start([23000, *FILLER_HAND], [23017, 23018, 23388, 23345])
    duel.play(23000)
    select_effect_option(duel, 0)
    assert choose_deck_card(duel, 23018, [23017, 23018]) == 1
    duel.advance(lambda: 23018 in duel.field(0) and duel.ready(0), "Blitzclique trap placed face-up")
    zone = duel.field(0).index(23018)
    assert 7 <= zone <= 11 and duel.face(0, zone) == 1

    duel.start([23001, 22960, 4007, 4642, 4037], [22959, 22961, 22962, 23345, 23017])
    duel.play(23001)
    duel.activate_on_field(23001)
    duel.choose_hand_target(22960)
    cpu = duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)
    cpu(0, 1)
    duel.list_items("Surge triggers after Steppleader destroys itself")
    cpu(0, 0)
    choose_deck_card(duel, 22961, [22959, 22961, 22962])
    duel.advance(lambda: duel.ready(0), "Surge search resolves")
    assert 22961 in duel.pile(0, HAND) and 23001 in duel.pile(0, GRAVE) and 22960 in duel.field(0)
    return {"scenarios": 2, "placed_trap": 23018, "summoned": 22960, "searched_on_destruction": 22961}


def gmx_set_from_deck(duel):
    duel.start([22937, *FILLER_HAND], [22342, 22936, 22938, 23345, 22937])
    duel.play(22937)
    duel.activate_on_field(22937)
    assert choose_deck_card(duel, 22936, [22342, 22936, 22938]) == 1
    duel.choose_hand_target(4007)
    duel.advance(lambda: duel.ready(0), "GMX sets a spell and returns a card to the deck")
    zone = duel.field(0).index(22936)
    assert 7 <= zone <= 11 and duel.face(0, zone) == 0 and duel.pile(0, DECK)[0] == 4007
    return {"scenarios": 1, "set_spell": 22936, "returned_to_deck_top": 4007}


def sacred_beast_distinct_names(duel):
    original_beasts = [6563, 6564, 6565]
    candidates = [22954, 22956, 22958, 22954, 22957]
    duel.start([22996, *FILLER_HAND], [22954, *original_beasts, *candidates[1:], 23345])
    duel.play(22996)
    choose_deck_card(duel, 22954, candidates)
    choose_deck_card(duel, 22956, [22956, 22958, 22957])
    choose_deck_card(duel, 22958, [22958, 22957])
    duel.choose_hand_target(4007)
    duel.choose_hand_target(4642)
    duel.advance(lambda: duel.ready(0), "Sacred Beasts search and discard resolve")
    assert {22954, 22956, 22958} <= set(duel.pile(0, HAND))
    assert {4007, 4642} <= set(duel.pile(0, GRAVE))
    assert set(original_beasts) <= set(duel.pile(0, DECK)) and duel.pile(0, DECK).count(22954) == 1
    return {"scenarios": 1, "searched_distinct_names": [22954, 22956, 22958], "discarded": [4007, 4642]}


def phantasm_fusion_from_graveyard(duel):
    materials = [22954, 22955, 22956]
    duel.start([12800, *materials, 4642], [23015, 23345], extra=[22978, 7342, 15514])
    duel.play(12800)
    duel.choose(23015, DECK)
    duel.wait_for_grave(12800)
    duel.advance(lambda: duel.ready(0), "Sacred Beasts trap can activate from the graveyard")
    index = duel.pile(0, GRAVE).index(23015)
    assert duel.mask(0, GRAVE, index) & (1 << ACTIVATE)
    duel.command(0, GRAVE, index, ACTIVATE)
    assert duel.choose(23015, GRAVE)[1] == [(23015, GRAVE)]
    assert duel.choose(22978, EXTRA)[1] == [(22978, EXTRA)]
    for index, material in enumerate(materials):
        assert duel.choose_hand_target(material) == materials[index:]
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 14, "Phantasm fusion material confirmation")
    duel.reply(1)
    duel.advance(lambda: 22978 in duel.field(0) and duel.ready(0), "Phantasm fusion resolves")
    assert 23015 in duel.pile(0, BANISHED) and set(materials) <= set(duel.pile(0, GRAVE))
    assert duel.pile(0, EXTRA) == [7342, 15514]
    return {"scenarios": 1, "banished_trap": 23015, "fusion": 22978, "materials": materials}


def clown_crew_extra_deck(duel):
    duel.start([22569, *FILLER_HAND], [22524, 22538, 23025, 23345], extra=[22541, 22991, 22713])
    duel.play(22569)
    duel.activate_on_field(22569)
    index, choices = duel.choose(22991, EXTRA)
    assert index == 3 and choices == [(22524, DECK), (22538, DECK), (22541, EXTRA), (22991, EXTRA)]
    duel.advance(lambda: 22991 in duel.field(0) and duel.ready(0), "Clown Crew summoned from the Extra Deck")
    assert duel.pile(0, EXTRA) == [22541, 22713]
    return {"scenarios": 1, "summoned_from_extra_deck": 22991}


def elfnote_places_ars_magna(duel):
    duel.start([22117, *FILLER_HAND], [22159, 22160, 23383, 23345])
    duel.play(22117, SPECIAL_SUMMON)
    duel.activate_on_field(22117)
    assert choose_deck_card(duel, 23383, [22159, 22160, 23383]) == 2
    duel.advance(lambda: duel.ready(0), "Elfnote places Citrinitas")
    zone = duel.field(0).index(23383)
    assert duel.field(0)[2] == 22117 and 7 <= zone <= 11 and duel.face(0, zone) == 1
    return {"scenarios": 1, "placed_via_elfnote_alias": 23383}


def power_patron_sends_and_searches(duel):
    duel.start([22565, *FILLER_HAND], [21423, 23339, 22119, 23345], extra=[23370, 21444, 23501])
    duel.play(22565)
    index, choices = duel.choose(23370, EXTRA)
    assert index == 3 and choices == [(21423, DECK), (23339, DECK), (22119, DECK), (23370, EXTRA), (21444, EXTRA)]
    choose_deck_card(duel, 23339, [23339])
    duel.advance(lambda: duel.ready(0), "Power Patron send and follow-up search resolve")
    assert 23370 in duel.pile(0, GRAVE) and duel.pile(0, EXTRA) == [21444, 23501]
    assert 23339 in duel.pile(0, HAND) and 23339 not in duel.pile(0, DECK)
    return {"scenarios": 1, "sent_from_extra_deck": 23370, "searched": 23339}


def light_and_darkness_ritual_monsters(duel):
    duel.start([22952, 22976, 22977, 4007, 4642], [22950, 22951, 23345])
    duel.play(22952, NORMAL_SUMMON)
    duel.activate_on_field(22952)
    assert duel.choose_hand_target(22977) == [22976, 22977]
    duel.advance(lambda: 22977 in duel.field(0) and duel.ready(0), "Celtic Mystic summons the chosen ritual monster")
    assert 22952 in duel.pile(0, GRAVE) and 22976 in duel.pile(0, HAND)
    return {"scenarios": 1, "tributed": 22952, "summoned": 22977}


def call_of_the_haunted_support(duel):
    duel.start([22346, *FILLER_HAND], [4989, 22350, 22351, 22352, 22353, 22344, 23345])
    duel.play(22346)
    choose_deck_card(duel, 22353, [4989, 22350, 22351, 22352, 22353])
    duel.advance(lambda: duel.ready(0), "Medusa searches a card mentioning Call of the Haunted")
    assert 22353 in duel.pile(0, HAND) and 22346 in duel.pile(0, GRAVE)

    duel.start([22344, 22345, 4007, 4642, 4037], [22350, 22351, 4989, 22353, 23345])
    duel.play(22344)
    choose_deck_card(duel, 4989, [4989])
    duel.choose_hand_target(22345)
    duel.activate_on_field(4989)
    _, choices = duel.choose(22345, GRAVE)
    assert choices == [(22345, GRAVE)]
    duel.advance(lambda: 22345 in duel.field(0) and duel.ready(0), "Call of the Haunted revives the discarded card")
    assert 22345 not in duel.pile(0, GRAVE)
    return {"scenarios": 2, "searched_support": 22353, "set_and_activated": 4989, "revived": 22345}


def citrinitas_other_aliases(duel):
    duel.start([21420, 23383, 4007, 4642, 4037], [23340, 23341, 23345])
    duel.play(23383)
    duel.play(21420)
    duel.advance(lambda: 21420 in duel.field(0) and duel.ready(0), "Citrinitas enables Artmage Fine Melt")
    assert 23383 in duel.field(0) and 21420 not in duel.pile(0, HAND)

    duel.start([22158, *FILLER_HAND], [23383, 23345])
    duel.play(22158)
    choose_deck_card(duel, 23383, [23383])
    duel.advance(lambda: duel.ready(0), "DoomZ Changer destroys Citrinitas")
    assert {22158, 23383} <= set(duel.pile(0, GRAVE)) and 23345 in duel.pile(0, DECK)
    return {"scenarios": 2, "artmage_summoned": 21420, "destroyed_as_doomz": 23383}


def medius_search(duel):
    duel.start([23383, *FILLER_HAND], [21419, 23339, 23345])
    duel.play(23383)
    duel.activate_on_field(23383)
    assert choose_deck_card(duel, 23339, [21419, 23339]) == 1
    duel.advance(lambda: duel.ready(0), "Medius search resolves")
    assert 23339 in duel.pile(0, HAND) and 21419 in duel.pile(0, DECK)
    return {"scenarios": 1, "searched_new_medius": 23339}


def medius_special_summon_and_search(duel):
    duel.start([23339, 22566, 5609, 23383, 4642], [21466, 21825, 22161, 23005, 23339, 23345],
               extra=[21443, 21812, 23501])
    duel.play(22566)
    duel.play(23339)
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 3, "Medius offers the optional Theorealize search")
    assert 23339 in duel.field(0)
    duel.reply(1)
    assert choose_deck_card(duel, 23005, [21466, 21825, 22161, 23005]) == 3
    duel.advance(lambda: duel.ready(0), "Medius adds the chosen spell")
    assert 23005 in duel.pile(0, HAND) and 23339 in duel.pile(0, DECK)

    duel.play(4642, NORMAL_SUMMON)
    duel.play(5609)
    duel.choose_hand_target(23005)
    duel.choose_field_target(4642)
    cpu = duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)
    cpu(0, 1)
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 6, "Medius reacts to a face-up banished monster")
    cpu(0, 0)
    enabled = duel.function("DuelDlgGetSelectItemEnable", c.c_int, c.c_int)
    assert [enabled(i) for i in range(2)] == [0, 1]
    duel.reply(1)
    index, choices = duel.choose(21812, EXTRA)
    assert index == 1 and choices == [(21443, EXTRA), (21812, EXTRA)]
    duel.advance(lambda: 21812 in duel.field(0), "Diactorus special summoned")
    assert {4642, 23339} <= set(duel.pile(0, BANISHED)) and duel.pile(0, EXTRA) == [21443, 23501]

    _, triggers = duel.choose(21812)
    assert triggers == [(21812, duel.field(0).index(21812))]
    assert duel.choose_hand_target(23383) == [23383]
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 3, "Diactorus offers to destroy a second card")
    duel.reply(0)
    duel.advance(lambda: duel.ready(0), "Diactorus trigger resolves")
    assert 21812 in duel.field(0) and {23005, 5609, 23383} <= set(duel.pile(0, GRAVE))
    return {"scenarios": 1, "searched_spell": 23005, "banished_medius": 23339,
            "summoned_diactorus": 21812, "destroyed_as_doomz": 23383}


def dark_tuner_additional_summon(duel):
    duel.start([22737, 22738, 11740, 4642, 4037], [4008, 23345])
    duel.play(11740)
    duel.choose(4008, DECK)
    duel.wait_for_grave(11740)
    duel.play(4642, NORMAL_SUMMON)
    duel.play(22737)
    duel.advance(lambda: duel.u32(INPUT_MODE) == 6 and duel.u32(INPUT_ACTIVE), "Dark Tuner summon command")
    hand = duel.pile(0, HAND)
    candidates = [cid for index, cid in enumerate(hand) if duel.mask(0, HAND, index) & (1 << NORMAL_SUMMON)]
    assert candidates == [22737, 22738]
    duel.command(0, HAND, hand.index(22738), NORMAL_SUMMON)
    for tribute in (4008, 4642):
        duel.choose_field_target(tribute)
    duel.advance(lambda: 22738 in duel.field(0) and duel.ready(0), "Dark Tuner normal summoned after the normal summon")
    assert {4008, 4642} <= set(duel.pile(0, GRAVE)) and 22737 in duel.pile(0, HAND)
    return {"scenarios": 1, "extra_normal_summon": 22738, "tributes": [4008, 4642]}


def zombie_send_and_recover(duel):
    duel.start([23352, 5236, 4007, 4642, 4037], [22344, 22930, 23345])
    duel.play(5236)
    duel.choose(22344, DECK)
    duel.wait_for_grave(5236)
    duel.play(23352, NORMAL_SUMMON)
    cpu = duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)
    cpu(0, 1)
    duel.list_items("Hubrow sends a level 6 Zombie")
    cpu(0, 0)
    choose_deck_card(duel, 22930, [22930])
    _, choices = duel.choose(22344, GRAVE)
    assert choices == [(22344, GRAVE), (22930, GRAVE)]
    duel.advance(lambda: duel.ready(0), "Hubrow recovers the chosen Zombie")
    assert 23352 in duel.field(0) and 22930 in duel.pile(0, GRAVE) and 22344 in duel.pile(0, HAND)
    return {"scenarios": 1, "sent_zombie": 22930, "recovered_zombie": 22344}


def witchcrafter_new_support(duel):
    duel.start([14410, *FILLER_HAND], [14404, 23163, 23164, 23345, 14406])
    duel.play(14410)
    choose_deck_card(duel, 23163, [14404, 23163, 23164, 14406])
    duel.wait_for_grave(14410)
    duel.play(23163)
    _, choices = duel.choose(14410, GRAVE)
    assert choices == [(14410, GRAVE)]
    duel.advance(lambda: 23163 in duel.field(0) and duel.ready(0), "Terracottan recovers Creation and summons itself")
    assert 14410 in duel.pile(0, HAND) and 14410 not in duel.pile(0, GRAVE)
    return {"scenarios": 1, "searched_and_summoned": 23163, "recovered_spell": 14410}


def unchained_destroy_and_summon(duel):
    duel.start([23171, 14696, 4007, 4642, 4037], [14635, 14636, 23170, 23172, 23345])
    duel.play(14696, SET_TRAP)
    duel.play(23171, NORMAL_SUMMON)
    cpu = duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)
    cpu(0, 1)
    duel.list_items("Shyma summon trigger")
    cpu(0, 0)
    choose_deck_card(duel, 23170, [14635, 14636, 23170])
    duel.choose_field_target(14696)
    cpu(0, 1)
    duel.list_items("old Unchained trap triggers on destruction")
    cpu(0, 0)
    choose_deck_card(duel, 14636, [14635, 23172, 14636])
    duel.advance(lambda: duel.ready(0), "Unchained monsters summoned")
    assert {23171, 23170, 14636} <= set(duel.field(0)) and 14696 in duel.pile(0, GRAVE)
    return {"scenarios": 1, "summoned": [23170, 14636], "destroyed_trap": 14696}


CASES = {
    "ashtra_search_and_trap": ashtra_search_and_trap,
    "ars_magna_search": ars_magna_search,
    "atlantis_mentions": atlantis_mentions,
    "dark_time_wizard_summon": dark_time_wizard_summon,
    "blitzclique_trap_and_trigger": blitzclique_trap_and_trigger,
    "gmx_set_from_deck": gmx_set_from_deck,
    "sacred_beast_distinct_names": sacred_beast_distinct_names,
    "phantasm_fusion_from_graveyard": phantasm_fusion_from_graveyard,
    "clown_crew_extra_deck": clown_crew_extra_deck,
    "elfnote_places_ars_magna": elfnote_places_ars_magna,
    "power_patron_sends_and_searches": power_patron_sends_and_searches,
    "light_and_darkness_ritual_monsters": light_and_darkness_ritual_monsters,
    "call_of_the_haunted_support": call_of_the_haunted_support,
    "citrinitas_other_aliases": citrinitas_other_aliases,
    "medius_search": medius_search,
    "medius_special_summon_and_search": medius_special_summon_and_search,
    "dark_tuner_additional_summon": dark_tuner_additional_summon,
    "zombie_send_and_recover": zombie_send_and_recover,
    "witchcrafter_new_support": witchcrafter_new_support,
    "unchained_destroy_and_summon": unchained_destroy_and_summon,
}


if __name__ == "__main__":
    run_cases(CASES, __doc__, __file__)
