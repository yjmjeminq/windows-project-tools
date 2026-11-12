"""Validate the deck editor's related-card file without starting the game."""

import argparse
import json
from pathlib import Path
import struct

from build_card_data import PORT_DIRECTORY, index_dat
from build_pc_card_pool import MOD_CONTENT, load_json
from build_pc_related_cards import (
    FAMILY_SUPPORT, KOREAN_POOL_ID, NAMED_BY, NAMES_CARD, RELATED_FILE, SAME_FAMILY,
    SUMMON_MATERIAL, active_cards,
)


def test_related_cards(project, path):
    cards = active_cards(project)
    archive = index_dat(project / "YGO_2020.dat")
    stock = {a & 0x3FFF for a, _ in struct.iter_unpack("<II", archive["bin/card_prop.bin"].read())} - {0}
    native_tag_count, = struct.unpack_from("<I", archive["bin/taginfo_e.bin"].read())
    data = load_json(path)
    tags = set(range(native_tag_count)) | {row["id"] for row in data["tags"]}
    entries = {row["card"]: {(unit["card"], unit["tag"]) for unit in row.get("add", ())}
               for row in data["cards"]}
    assert len(entries) == len(data["cards"])
    assert all(len(entries[row["card"]]) == len(row.get("add", ())) for row in data["cards"])
    assert all(entries.get(display) for display in cards), "an added card has an empty related list"

    active = stock | cards.keys()
    for source, units in entries.items():
        assert source in active
        assert all(target in active and target != source and tag in tags for target, tag in units), source

    original = load_json(project / "Mods/2020-2021-Cards" / MOD_CONTENT / RELATED_FILE)
    for row in original["cards"]:
        assert {(unit["card"], unit["tag"]) for unit in row["add"]} <= entries[row["card"]]

    display_id = {cid: cid for cid in stock}
    display_id.update((row["konamiId"], display) for display, row in cards.items() if row.get("konamiId"))
    positive = (
        (6672, 17403, FAMILY_SUPPORT), (17403, 6672, FAMILY_SUPPORT),  # E - Emergency Call
        (5328, 23345, 1086), (23345, 5328, 637),                    # Reinforcement of the Army
        (23379, 23395, SAME_FAMILY), (23395, 23379, SAME_FAMILY),    # Ashtra
        (23383, 21420, SAME_FAMILY), (23383, 21777, SAME_FAMILY),   # Artmage and DoomZ aliases
        (23383, 22117, SAME_FAMILY), (22117, 23383, SAME_FAMILY),   # Elfnote alias
        (23339, 21812, FAMILY_SUPPORT), (21812, 23339, FAMILY_SUPPORT),
        (22346, 4989, NAMES_CARD), (4989, 22346, NAMED_BY),        # Call of the Haunted
        (21443, 21419, SUMMON_MATERIAL), (21419, 21443, SUMMON_MATERIAL),
        (22996, 22956, SAME_FAMILY),                               # Sacred Beasts Released
        (22715, 13033, 159),                                     # generic Link support, S:P Fancy Ball
        (22937, 22935, FAMILY_SUPPORT), (22935, 22937, FAMILY_SUPPORT),  # Evolved Daneen supports GMX
    )
    for source, target, tag in positive:
        assert (display_id[target], tag) in entries[display_id[source]], (source, target, tag)

    negative = ((6672, 23345), (5328, 23323), (22996, 6563))
    for source, target in negative:
        assert all(card != display_id[target] for card, _ in entries[display_id[source]]), (source, target)
    assert display_id[23383] != 23383
    assert all(card != 23383 for card, _ in entries[display_id[22117]])
    assert (display_id[22935], SAME_FAMILY) not in entries[display_id[22937]]

    return {"related_lists": len(entries), "imported_cards_covered": len(cards),
            "links": sum(map(len, entries.values())), "targeted_checks": len(positive) + len(negative) + 2}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--related", type=Path)
    args = parser.parse_args()
    path = args.related or args.project / "Mods" / KOREAN_POOL_ID / MOD_CONTENT / RELATED_FILE
    print(json.dumps(test_related_cards(args.project, path)))


if __name__ == "__main__":
    main()
