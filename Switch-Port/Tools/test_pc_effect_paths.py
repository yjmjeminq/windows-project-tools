"""Exercise offline card effects, including zones, costs, timing, and empty archetype rows."""

import ctypes as c

from test_pc_duel_effects import (
    ACTIVATE, ASKED_PLAYER, BANISHED, DECK, DIALOG_KIND, DIALOG_OWNER, EXTRA,
    GRAVE, HAND, INPUT_ACTIVE, INPUT_MODE, NORMAL_SUMMON, PLACE_PENDULUM,
    SPECIAL_SUMMON, run_cases,
)


ATTACK, SET_MONSTER, SET_TRAP = 0, 6, 7
BATTLE_PHASE = 3
FILLER_HAND = [4007, 4642, 4037, 4047]


def choose_deck_card(duel, target, expected):
    index, choices = duel.choose(target, DECK)
    assert choices == [(cid, DECK) for cid in expected], (target, choices)
    return index


def select_effect_option(duel, index):
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 6, "effect mode choice")
    duel.reply(index)


def chain_response(duel, player, zone, index=0):
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 4 and duel.u32(DIALOG_OWNER) == player,
                 f"player {player} chain response")
    duel.reply(1)
    duel.advance(lambda: duel.u32(INPUT_MODE) in (4, 5) and duel.u32(INPUT_ACTIVE)
                 and duel.u32(ASKED_PLAYER) == player and duel.mask(player, zone, index) & (1 << ACTIVATE),
                 "response activation available")
    duel.command(player, zone, index, ACTIVATE)


def restored_deck_searches(duel):
    # The second candidate tests the real list index. Each deck also has ineligible cards.
    searches = [
        (17373, [17374, 17375, 17376], [23345]),  # Runick Tip
        (17765, [17762, 18149, 17763], [17808, 23345]),  # The Bystial Lubellion
        (19900, [19858, 20198, 19859], [23345]),  # Sangen Summoning
        (20237, [20192, 20194, 20195], [20238, 23345]),  # Tales of the White Forest
        (20196, [20240, 20816, 20241], [20490, 23345]),  # Fiendsmith Engraver
        (21361, [21354, 21789, 21355], [21363, 23345]),  # Ketu Dracotail
        (18523, [18478, 18479, 18480], [18522, 23345]),  # Sweet Dreams, Nemleria
        (19522, [19474, 19475, 19476], [23345]),  # Barrier of the Voiceless Voice
        (19196, [19148], [23345]),  # WANTED: Seeker of Sinful Spoils
    ]
    results = {}
    for card, candidates, other in searches:
        hand = [4008, *FILLER_HAND[:3]] if card == 20237 else FILLER_HAND
        duel.start([card, *hand], [*candidates, *other])
        if card == 20237:
            duel.play(4008, NORMAL_SUMMON)
        duel.play(card)
        if card in (19900, 19522):
            duel.activate_on_field(card)
        if card == 17373:
            select_effect_option(duel, 0)

        target = candidates[min(1, len(candidates) - 1)]
        choose_deck_card(duel, target, candidates)
        if card == 19900:
            duel.choose_hand_target(4007)
        duel.advance(lambda: target in duel.pile(0, HAND) and duel.ready(0), "card added to hand")
        assert target not in duel.pile(0, DECK)
        if card in (17765, 20196):
            assert card in duel.pile(0, GRAVE)
        if card == 17373:
            assert len(duel.pile(1, BANISHED)) == 1
        results[card] = target

    duel.start([21385, *FILLER_HAND], [21376, 21377, 21378, 21383, 23345])
    duel.play(21385)
    cpu = duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)
    cpu(0, 1)
    duel.list_items("K9 on-activation search")
    cpu(0, 0)
    choose_deck_card(duel, 21377, [21376, 21377, 21378])
    duel.advance(lambda: 21377 in duel.pile(0, HAND), "K9 search resolves")
    results[21385] = 21377
    return {"scenarios": len(results), "added_to_hand": results}


def labrynth_set_from_deck(duel):
    duel.start([17364, *FILLER_HAND], [17369, 18222, 17365, 23498, 17367])
    duel.play(17364)
    duel.choose_hand_target(4007)
    assert choose_deck_card(duel, 18222, [17369, 18222, 17367]) == 1
    duel.advance(lambda: 18222 in duel.field(0) and duel.ready(0), "Labrynth trap set")
    zone = duel.field(0).index(18222)
    assert 7 <= zone <= 11 and duel.face(0, zone) == 0
    assert not duel.mask(0, zone, 0) & (1 << ACTIVATE)
    assert {17364, 4007} <= set(duel.pile(0, GRAVE)) and 18222 not in duel.pile(0, DECK)
    return {"scenarios": 1, "set_from_deck": 18222}


def field_placements(duel):
    duel.start([17457, *FILLER_HAND], [17407, 17409, 17408, 17458, 23345])
    duel.play(17457)
    choose_deck_card(duel, 17409, [17407, 17409, 17408])
    duel.wait_for_grave(17457)
    attack = duel.function("CardGetAtk", c.c_int, c.c_int)(17409)
    assert 17409 in duel.field(0) and duel.lp(0) == 8000 - attack

    duel.start([19376, *FILLER_HAND], [19373, 20200, 19374, 19378, 23345])
    duel.play(19376)
    duel.activate_on_field(19376)
    duel.choose_hand_target(4007)
    choose_deck_card(duel, 20200, [19373, 20200, 19374])
    duel.advance(lambda: 20200 in duel.field(0), "Centur-Ion placed as continuous trap")
    zone = duel.field(0).index(20200)
    assert 7 <= zone <= 11 and duel.face(0, zone) == 1 and 4007 in duel.pile(0, GRAVE)

    duel.start([21374, 21365, 21366, 4007, 4642], [21367, 23345])
    duel.play(21374)
    select_effect_option(duel, 1)
    _, choices = duel.choose(21366, HAND)
    assert choices == [(21365, HAND), (21366, HAND)]
    duel.advance(lambda: 21366 in duel.field(0), "Yummy summoned from hand")
    assert 21366 not in duel.pile(0, HAND)
    return {"scenarios": 3, "summoned": [17409, 21366], "placed_as_trap": 20200}


def summon_and_move(duel):
    duel.start([17811, *FILLER_HAND], [17414, 17415, 17416, 17473, 23345])
    duel.play(17811)
    choose_deck_card(duel, 17415, [17414, 17415, 17416])
    duel.choose_field_target(17415)
    duel.advance(lambda: 17415 in duel.pile(0, GRAVE), "Tearlaments sent after summon")
    assert 17415 not in duel.field(0) and 17415 not in duel.pile(0, DECK)

    duel.start([18845, 17991, *FILLER_HAND[:3]], [17993, 17997, 17994, 18000, 23345])
    duel.play(18845)
    choose_deck_card(duel, 17997, [17993, 17997, 17994])
    duel.choose_hand_target(17991)
    duel.advance(lambda: 17991 in duel.pile(0, GRAVE), "Rescue-ACE tribute resolves")
    assert 17997 in duel.field(0) and duel.face(0, duel.field(0).index(17997)) == 1

    duel.start([19368, 19363, *FILLER_HAND[:3]], [19364, 19365, 19366, 19369, 23345])
    duel.play(19368)
    duel.choose_hand_target(19363)
    choose_deck_card(duel, 19365, [19364, 19365, 19366])
    duel.advance(lambda: 19365 in duel.field(0), "Memento summoned")
    assert 19363 in duel.pile(0, GRAVE) and 19365 not in duel.pile(0, HAND)
    assert duel.face(0, duel.field(0).index(19365)) == 1
    return {"scenarios": 3, "sent": 17415, "tributed": 17991, "destroyed": 19363}


def conditional_summons(duel):
    duel.start([18022, 4642, 4007, 4037, 4047], [18015, 18016, 18017, 23345])
    duel.play(4642, NORMAL_SUMMON)
    duel.play(18022)
    duel.choose_field_target(4642)
    duel.activate_on_field(18022)
    choose_deck_card(duel, 18016, [18015, 18016])
    duel.advance(lambda: 18016 in duel.field(0) and 4642 in duel.pile(0, HAND), "Mikanko equip transferred")
    assert 18022 in duel.field(0) and 4642 not in duel.field(0)

    duel.start([18747, 18739, *FILLER_HAND[:3]], [18740, 18741, 23345])
    duel.play(18747)
    assert duel.choose_hand_target(18739) == [18739]
    duel.choose_hand_target(4007)
    duel.advance(lambda: duel.u32(DIALOG_KIND) == 14, "Nouvelles ritual confirmation")
    duel.reply(1)
    duel.advance(lambda: 18739 in duel.field(0), "Nouvelles ritual summon")
    assert 4007 in duel.pile(0, GRAVE)

    duel.start([18734, 4037, 4007, 4642, 4047], [18728, 18729, 18730, 18727, 23345], opponent_is_human=True)
    duel.play(18734)
    duel.choose_hand_target(4037)
    choose_deck_card(duel, 18730, [18729, 18730])
    duel.advance(lambda: 18730 in duel.field(0), "Vanquish Soul same-attribute summon")
    duel.end_turn(0)
    assert 18730 in duel.pile(0, HAND) and 18730 not in duel.field(0)

    duel.start([18203, 18151, *FILLER_HAND[:3]], [17769, 17770, 17768, 17815, 23345])
    duel.play(18151, NORMAL_SUMMON)
    duel.play(18203)
    duel.choose_field_target(18151)
    choose_deck_card(duel, 17770, [17769, 17770, 17768])
    duel.advance(lambda: 17770 in duel.field(0), "Kashtira different-attribute summon")
    assert duel.face(0, duel.field(0).index(17770)) == 1
    return {"scenarios": 4, "summoned": [18016, 18739, 18730, 17770]}


def therion_cost(duel):
    duel.start([17166, 17118, *FILLER_HAND[:3]], [4008, 4009, 17119, 23345])
    duel.play(17166)
    assert duel.choose_hand_target(17118) == [17118]
    duel.wait_for_grave(17166)
    assert {4008, 4009} <= set(duel.pile(0, HAND)) and 17118 in duel.pile(0, GRAVE)
    return {"scenarios": 1, "paid": 17118, "drew": [4008, 4009]}


def purrely_hidden_choice(duel):
    duel.start([18010, *FILLER_HAND], [18003, 18009, 18012, 18013, 23345])
    duel.play(18010)
    duel.activate_on_field(18010)
    choices = duel.list_items("Purrely reveal three")
    assert choices == [(cid, DECK) for cid in (18003, 18009, 18012, 18013)]
    assert duel.function("DuelListGetSelectMin", c.c_int)() == 3
    selected = {18003, 18012, 18013}
    duel.submit_list([choices.index((cid, DECK)) for cid in (18003, 18012, 18013)])
    hidden = duel.list_items("Purrely opponent's blind selection")
    assert hidden == [(0, DECK)] * 3
    duel.submit_list([1])
    duel.advance(lambda: duel.ready(0), "Purrely choice resolves")
    added = selected & set(duel.pile(0, HAND))
    assert len(added) == 1 and selected - added <= set(duel.pile(0, DECK))
    assert duel.lp(0) == 7500
    return {"scenarios": 1, "revealed": sorted(selected), "added": sorted(added)}


def ritual_beast_zones(duel):
    for target, origin in ((19631, GRAVE), (11497, BANISHED)):
        duel.start([12799, 5236, 6161, 11493, 4007], [19631, 11497, 4009])
        duel.play(5236)
        duel.choose(19631, DECK)
        duel.wait_for_grave(5236)
        duel.play(6161)
        duel.choose(11497, DECK)
        duel.wait_for_grave(6161)
        duel.play(12799)
        assert duel.choose_hand_target(11493) == [11493]
        _, choices = duel.choose(target, origin)
        assert choices == [(19631, GRAVE), (11497, BANISHED), (11493, BANISHED)]
        duel.advance(lambda: target in duel.field(0), "Ritual Beast revived")
        assert target not in duel.pile(0, origin) and 11493 in duel.pile(0, BANISHED)

    banished_face_down = [19631, *range(4008, 4017)]
    duel.start([12465, 12799, 6161, 11493, 4007], [*banished_face_down, 4035, 4040, 11497])
    duel.play(12465)
    duel.wait_for_grave(12465)
    assert duel.pile(0, BANISHED) == banished_face_down
    duel.play(6161)
    duel.choose(11497, DECK)
    duel.wait_for_grave(6161)
    duel.play(12799)
    duel.choose_hand_target(11493)
    _, choices = duel.choose(11497, BANISHED)
    assert choices == [(11497, BANISHED), (11493, BANISHED)]
    duel.advance(lambda: 11497 in duel.field(0), "face-up banished card summoned")
    assert 19631 in duel.pile(0, BANISHED)
    return {"scenarios": 3, "origins": ["grave", "banished"], "excluded_face_down": 19631}


def delayed_banished_return(duel):
    duel.start([11497, *FILLER_HAND], [11502, 19631, 23345],
               opponent=[4642, 4007, 4037, 4047, 4008], opponent_is_human=True)
    duel.play(11497, NORMAL_SUMMON)
    duel.activate_on_field(11497)
    choose_deck_card(duel, 11502, [11502, 19631])
    duel.advance(lambda: 11502 in duel.pile(0, BANISHED) and duel.ready(0), "Cannahawk banishes")
    duel.end_turn(0)
    duel.end_turn(1)
    assert 11502 in duel.pile(0, BANISHED) and 11502 not in duel.pile(0, HAND)
    duel.end_turn(0)
    duel.play(4642, NORMAL_SUMMON, player=1)
    duel.end_turn(1)
    assert 11502 in duel.pile(0, HAND) and 11502 not in duel.pile(0, BANISHED)
    return {"scenarios": 1, "returned_on_second_standby": 11502}


def distinct_name_selection(duel):
    duel.start([5236, *FILLER_HAND], [15726, 4030, 19866, 21202, 19866, 12768, 23345])
    duel.play(5236)
    duel.choose(15726, DECK)
    cpu = duel.function("DuelSetPlayerType", None, c.c_int, c.c_int)
    cpu(0, 1)
    duel.list_items("Wightbaking first name")
    cpu(0, 0)
    choose_deck_card(duel, 19866, [19866, 19866, 4030, 12768])
    choose_deck_card(duel, 12768, [4030, 12768])
    duel.choose_hand_target(4007)
    duel.advance(lambda: duel.ready(0), "Wightbaking discard resolves")
    assert {19866, 12768} <= set(duel.pile(0, HAND)) and 4007 in duel.pile(0, GRAVE)
    assert duel.pile(0, DECK).count(19866) == 1
    return {"scenarios": 1, "selected_different_names": [19866, 12768]}


def order_cards_on_deck(duel):
    duel.start([15106, *FILLER_HAND], [15097, 23346, 15098, 15107, 23345])
    duel.play(15106)
    duel.activate_on_field(15106)
    options = duel.list_items("Laputite multi-selection")
    assert options == [(cid, DECK) for cid in (15097, 23346, 15098, 15107)]
    assert duel.function("DuelListIsMultiMode", c.c_int)()
    duel.submit_list([2, 1])
    order = duel.list_items("Laputite reorder selected cards")
    assert order == [(15098, DECK), (23346, DECK)]
    duel.submit_list([1, 0])
    duel.advance(lambda: duel.ready(0), "ordered cards placed")
    assert duel.pile(0, DECK)[:2] == [23346, 15098]
    return {"scenarios": 1, "deck_top": [23346, 15098]}


def effect_negation_keeps_cost(duel):
    cost = [4008, 4009, 4010]
    duel.start([7868, *FILLER_HAND], [*cost, 7591, 19865, 7592],
               opponent=[12950, *FILLER_HAND], opponent_is_human=True)
    duel.play(7868)
    assert duel.pile(1, HAND)[0] == 12950
    chain_response(duel, 1, HAND)
    duel.wait_for_grave(7868)
    assert 12950 in duel.pile(1, GRAVE) and set(cost) <= set(duel.pile(0, GRAVE))
    assert {7591, 19865, 7592} <= set(duel.pile(0, DECK))
    assert duel.pile(0, HAND) == FILLER_HAND
    return {"scenarios": 1, "negated": 7868, "cost_still_paid": cost}


def activation_negation(duel):
    duel.start([4861, *FILLER_HAND], opponent=[4844, *FILLER_HAND], opponent_is_human=True)
    duel.play(4861, SET_TRAP)
    duel.advance(lambda: duel.ready(0) and 4861 in duel.field(0), "Solemn Judgment set")
    zone = duel.field(0).index(4861)
    duel.end_turn(0)
    before = len(duel.pile(1, DECK))
    duel.play(4844, player=1)
    chain_response(duel, 0, zone)
    duel.advance(lambda: 4861 in duel.pile(0, GRAVE) and 4844 in duel.pile(1, GRAVE) and duel.ready(1),
                 "Solemn Judgment resolves")
    assert duel.lp(0) == 4000 and len(duel.pile(1, DECK)) == before

    duel.start([4861, *FILLER_HAND], opponent=[23345, *FILLER_HAND], opponent_is_human=True)
    duel.play(4861, SET_TRAP)
    duel.end_turn(0)
    zone = duel.field(0).index(4861)
    duel.play(23345, NORMAL_SUMMON, player=1)
    chain_response(duel, 0, zone)
    duel.advance(lambda: duel.ready(1), "normal summon negated")
    assert 23345 in duel.pile(1, GRAVE) and 23345 not in duel.field(1)
    assert 4861 in duel.pile(0, GRAVE) and duel.lp(0) == 4000
    return {"scenarios": 2, "activation_negated": 4844, "summon_negated": 23345, "lp_paid": 4000}


def simultaneous_triggers(duel):
    duel.start([4054, 4580, 4342, 4007, 4037], [4009, 4008, 4642, 23345], opponent_is_human=True)
    duel.play(4054, NORMAL_SUMMON)
    duel.end_turn(0)
    duel.end_turn(1)
    duel.play(4580, NORMAL_SUMMON)
    duel.play(4342)
    _, witch_choices = duel.choose(4642, DECK)
    assert (4008, DECK) not in witch_choices  # DEF 2000
    _, sangan_choices = duel.choose(4008, DECK)
    assert (4642, DECK) not in sangan_choices  # ATK 1600
    duel.advance(lambda: duel.ready(0), "simultaneous triggers resolve")
    assert {4008, 4642} <= set(duel.pile(0, HAND))
    assert {4054, 4580, 4342} <= set(duel.pile(0, GRAVE))
    activation_order = [card for code, _, card, _, _ in duel.events if code == 35]
    assert activation_order == [4342, 4054, 4580]
    return {"scenarios": 1, "activation_order": activation_order, "search_order": [4642, 4008]}


def missing_target_at_resolution(duel):
    duel.start([4642, 5914, 4007, 4037, 4047], opponent=[5432, *FILLER_HAND], opponent_is_human=True)
    duel.play(4642, NORMAL_SUMMON)
    duel.play(5914, SET_TRAP)
    duel.end_turn(0)
    duel.play(5432, player=1)
    duel.choose_field_target(4642)
    chain_response(duel, 0, duel.field(0).index(5914))
    duel.choose_field_target(4642)
    duel.advance(lambda: duel.ready(1), "chain resolves after the target leaves the field")
    assert 4642 in duel.pile(0, HAND) and 4642 not in duel.field(0)
    assert 5914 in duel.pile(0, GRAVE) and 5432 in duel.pile(1, GRAVE)
    return {"scenarios": 1, "returned_target": 4642, "original_effect": 5432}


def end_phase_expiration(duel):
    duel.start([4817, 5355, 4007, 4037, 4047], opponent=FILLER_HAND, opponent_is_human=True)
    duel.end_turn(0)
    duel.play(4642, NORMAL_SUMMON, player=1)
    duel.end_turn(1)
    duel.play(4817)
    duel.choose_field_target(4642, player=1)
    duel.play(5355)
    duel.choose_field_target(4642)
    duel.advance(lambda: duel.ready(0), "temporary modifiers applied")
    assert 4642 not in duel.field(1)
    stats = (c.c_int * 16)()
    get_stats = duel.function("DuelGetCardBasicVal", None, c.c_int, c.c_int, c.c_int, c.c_void_p)
    get_stats(0, duel.field(0).index(4642), 0, stats)
    assert stats[1] == 800
    duel.end_turn(0)
    assert 4642 not in duel.field(0)
    get_stats(1, duel.field(1).index(4642), 0, stats)
    assert stats[1] == 1600
    return {"scenarios": 1, "returned_control": 4642, "restored_attack": 1600}


def selection_cancel_and_retry(duel):
    duel.start([6995, 8933, 4007, 4642, 4037], [4008], extra=[22713, 23501])
    duel.play(6995)
    duel.choose_hand_target(4007)
    duel.wait_for_grave(6995)
    duel.play(8933, NORMAL_SUMMON)
    duel.advance(lambda: duel.ready(0), "synchro materials ready")
    duel.command(0, EXTRA, 0, SPECIAL_SUMMON)
    choices = duel.list_items("cancellable Extra Deck list")
    assert choices == [(22713, EXTRA), (23501, EXTRA)]
    duel.submit_list([])
    duel.advance(lambda: duel.ready(0), "cancel returns to the main phase")
    assert {8933, 4007} <= set(duel.field(0)) and duel.pile(0, EXTRA) == [22713, 23501]
    assert duel.summon_from_extra(23501, [8933, 4007]) == 1
    duel.advance(lambda: 23501 in duel.field(0), "second Extra Deck card summoned after cancellation")
    assert {8933, 4007} <= set(duel.pile(0, GRAVE)) and duel.pile(0, EXTRA) == [22713]
    return {"scenarios": 1, "selected_after_cancel": 23501}


def empty_search_pool(duel):
    duel.start([9122, 18789, 7687, 4007, 4642], [7758, 4037, 4047])
    index = duel.pile(0, HAND).index(9122)
    assert not duel.mask(0, HAND, index) & (1 << ACTIVATE)
    return {"scenarios": 1, "blocked_without_valid_target": 9122}


def once_per_turn_search(duel):
    duel.start([14410, 14410, *FILLER_HAND[:3]], [14404, 22499, 22320, 14406], opponent_is_human=True)
    duel.play(14410)
    duel.choose(22499, DECK)
    duel.wait_for_grave(14410)
    duel.advance(lambda: duel.ready(0), "first search finished")
    index = duel.pile(0, HAND).index(14410)
    assert not duel.mask(0, HAND, index) & (1 << ACTIVATE)
    duel.end_turn(0)
    duel.end_turn(1)
    duel.play(14410)
    duel.choose(22320, DECK)
    duel.advance(lambda: 22320 in duel.pile(0, HAND), "second copy available next turn")
    assert 22499 in duel.pile(0, HAND)
    return {"scenarios": 1, "searched_on_separate_turns": [22499, 22320]}


def fusion_materials(duel):
    duel.start([14304, 4930, 4007, 4642, 4037], [23345, 6658, 6949, 23323], extra=[12694, 16524])
    duel.play(14304)
    _, choices = duel.choose(12694, EXTRA)
    assert choices == [(12694, EXTRA), (16524, EXTRA)]
    _, choices = duel.choose(23345, DECK)
    assert choices == [(4930, HAND), (23345, DECK), (6658, DECK), (6949, DECK)]
    duel.choose(4930, HAND)
    duel.advance(lambda: 12694 in duel.field(0) or duel.u32(DIALOG_KIND) == 14, "fusion material confirmation")
    if duel.u32(DIALOG_KIND) == 14:
        duel.reply(1)
    duel.advance(lambda: 12694 in duel.field(0) and duel.ready(0), "Fusion Destiny resolves")
    assert {23345, 4930, 14304} <= set(duel.pile(0, GRAVE)) and duel.pile(0, EXTRA) == [16524]
    return {"scenarios": 1, "fusion": 12694, "materials_from_deck_and_hand": [23345, 4930]}


def link_and_pendulum(duel):
    duel.start([11740, 23345, 4007, 4642, 4037], [4008], extra=[14676, 13034])
    duel.play(11740)
    duel.choose(4008, DECK)
    duel.wait_for_grave(11740)
    duel.play(23345, NORMAL_SUMMON)
    duel.summon_from_extra(14676, [23345, 4008])
    duel.advance(lambda: 14676 in duel.field(0) and duel.ready(0), "Link Summon")
    assert {23345, 4008} <= set(duel.pile(0, GRAVE)) and duel.pile(0, EXTRA) == [13034]

    duel.start([11134, 11935, 4037, 4047, 4007])
    duel.play(11134, PLACE_PENDULUM)
    duel.play(11935, PLACE_PENDULUM)
    duel.advance(lambda: duel.ready(0), "Pendulum scales placed")
    assert {duel.field(0)[7], duel.field(0)[11]} == {11134, 11935}
    assert duel.mask(0, 7, 0) & (1 << SPECIAL_SUMMON)
    duel.command(0, 7, 0, SPECIAL_SUMMON)
    choices = duel.list_items("Pendulum Summon candidates")
    assert choices == [(4037, HAND), (4047, HAND)]
    duel.submit_list([1, 0])
    duel.advance(lambda: {4037, 4047} <= set(duel.field(0)) and duel.ready(0), "Pendulum Summon")
    assert duel.pile(0, HAND) == [4007]
    assert not (duel.mask(0, 7, 0) | duel.mask(0, 11, 0)) & (1 << SPECIAL_SUMMON)
    return {"scenarios": 2, "link": 14676, "pendulum": [4037, 4047]}


def battle_resolution(duel):
    for cylinder in (False, True):
        duel.start([5334, *FILLER_HAND], opponent=[4642, 5124, 4037, 4047, 4008], opponent_is_human=True)
        duel.play(5334, NORMAL_SUMMON)
        duel.end_turn(0)
        duel.play(4642, SET_MONSTER, player=1)
        if cylinder:
            duel.play(5124, SET_TRAP, player=1)
        duel.end_turn(1)
        duel.function("DuelComMovePhase", None, c.c_int)(BATTLE_PHASE)
        duel.advance(lambda: duel.phase() == BATTLE_PHASE and duel.u32(INPUT_MODE) == 3
                     and duel.u32(INPUT_ACTIVE), "attack available")
        zone = duel.field(0).index(5334)
        assert duel.mask(0, zone, 0) & (1 << ATTACK)
        duel.command(0, zone, 0, ATTACK)
        duel.choose_field_target(4642, player=1)
        if cylinder:
            chain_response(duel, 1, duel.field(1).index(5124))
            duel.wait_for_grave(5124, 1)
            assert duel.lp(0) == 6100 and duel.lp(1) == 8000 and 4642 in duel.field(1)
        else:
            duel.wait_for_grave(4642, 1)
            duel.advance(lambda: duel.u32(INPUT_MODE) == 3 and duel.u32(INPUT_ACTIVE), "battle resolves")
            assert duel.lp(0) == 8000 and duel.lp(1) == 7300 and duel.face(0, zone) == 1
    return {"scenarios": 2, "piercing_damage": 700, "reflected_damage": 1900}


def flip_during_battle(duel):
    duel.start([4507, *FILLER_HAND], opponent=[4642, 4007, 4037, 4047, 4008], opponent_is_human=True)
    duel.play(4507, SET_MONSTER)
    duel.end_turn(0)
    duel.play(4642, NORMAL_SUMMON, player=1)
    duel.advance(lambda: duel.ready(1), "opponent can enter battle")
    duel.function("DuelComMovePhase", None, c.c_int)(BATTLE_PHASE)
    duel.advance(lambda: duel.phase() == BATTLE_PHASE and duel.u32(INPUT_MODE) == 3
                 and duel.u32(INPUT_ACTIVE), "attack declared against a set monster")
    duel.command(1, duel.field(1).index(4642), 0, ATTACK)
    duel.choose_field_target(4507)
    duel.choose_field_target(4642, player=1)
    duel.wait_for_grave(4507)
    duel.wait_for_grave(4642, 1)
    assert duel.lp(0) == duel.lp(1) == 8000
    assert any(code == 35 and card == 4507 for code, _, card, _, _ in duel.events)
    return {"scenarios": 1, "flip_effect": 4507, "destroyed_attacker": 4642}


CASES = {
    "restored_deck_searches": restored_deck_searches,
    "labrynth_set_from_deck": labrynth_set_from_deck,
    "field_placements": field_placements,
    "summon_and_move": summon_and_move,
    "conditional_summons": conditional_summons,
    "therion_cost": therion_cost,
    "purrely_hidden_choice": purrely_hidden_choice,
    "ritual_beast_zones": ritual_beast_zones,
    "delayed_banished_return": delayed_banished_return,
    "distinct_name_selection": distinct_name_selection,
    "order_cards_on_deck": order_cards_on_deck,
    "effect_negation_keeps_cost": effect_negation_keeps_cost,
    "activation_negation": activation_negation,
    "simultaneous_triggers": simultaneous_triggers,
    "missing_target_at_resolution": missing_target_at_resolution,
    "end_phase_expiration": end_phase_expiration,
    "selection_cancel_and_retry": selection_cancel_and_retry,
    "empty_search_pool": empty_search_pool,
    "once_per_turn_search": once_per_turn_search,
    "fusion_materials": fusion_materials,
    "link_and_pendulum": link_and_pendulum,
    "battle_resolution": battle_resolution,
    "flip_during_battle": flip_during_battle,
}


if __name__ == "__main__":
    run_cases(CASES, __doc__, __file__)
