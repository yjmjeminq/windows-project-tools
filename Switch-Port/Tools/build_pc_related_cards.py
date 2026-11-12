"""Build the deck editor's related-card lists for the installed PC card pool."""

import argparse
from collections import defaultdict
from functools import lru_cache
from hashlib import sha256
from html import unescape
import json
import operator
import os
from pathlib import Path
import re
import struct
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unicodedata import normalize
from urllib.request import urlopen

from build_card_data import ATTRIBUTE, CARD_KIND, ICON, MONSTER_TYPE, PORT_DIRECTORY, index_dat
from build_pc_card_pool import MOD_CONTENT, load_json
from repair_pc_card_families import TABLE_NAME, apply_memberships, decode_card_groups


KOREAN_POOL_ID = "2026-11-KR-Cards"
RELATED_FILE = "relatedcards.json"
ARCHETYPE_SOURCE = (
    "https://raw.githubusercontent.com/Arefu/Yu-Gi-Oh-Ex/v1.6.1/"
    "File%20Type%20Libraries/CARD_Named.bin/Archetypes.json"
)
ARCHETYPE_SHA256 = "410a8ae9cc9cc93d7308960fcf5a6f4c11808fc90e9a80f5849b784cec463dd4"
LAST_STOCK_GROUP = 418
NAMES_CARD, NAMED_BY, SAME_FAMILY, FAMILY_SUPPORT, SUMMON_MATERIAL = range(1802, 1807)

# These are the native 80460 indices verified by the PC duel fixtures.
# The numbers on cards.json's archetypes use the deck editor's older catalog.
VERIFIED_FAMILIES = {
    500: "Therion", 504: "Labrynth", 506: "Runick", 508: "Spright", 509: "Tearlaments",
    520: "Bystial", 521: "Kashtira", 523: "Rescue-ACE", 524: "Purrely", 525: "Mikanko",
    536: "Nemleria", 539: "Vanquish Soul", 540: "Nouvelles", 558: "Diabellstar",
    563: "Memento", 564: "Centur-Ion", 569: "Voiceless Voice", 579: "Tenpai Dragon",
    582: "White Forest", 583: "Fiendsmith", 620: "Dracotail", 621: "Yummy", 622: "K9",
    624: "Artmage", 625: "Power Patron", 626: "DoomZ", 638: "Elfnote", 641: "GMX",
    643: "Clown Crew", 646: "Dark Tuner", 648: "Sacred Beast", 649: "Blitzclique",
    652: "Theorealize", 659: "Daedalus", 660: "Ashtra", 661: "Ars Magna",
    662: "Medius", 663: "Diactorus",
}
NAME_REFERENCE_GROUPS = {
    642: "Call of the Haunted", 647: "Light and Darkness Ritual", 655: "Dark Time Wizard",
    658: "Atlantis, City of the Sea Dragon",
}

QUOTED = re.compile(r'"([^"\r\n]+)"|「([^」\r\n]+)」|『([^』\r\n]+)』')
GROUP_AFTER = re.compile(
    r"\s+(?:(?:effect|fusion|ritual|synchro|xyz|pendulum|link|normal|continuous|tuner)\s+)*"
    r"(?:card|monster|spell|trap)s?\b|\s*(?:의\s*)?카드명이\s*쓰여진", re.IGNORECASE,
)
GROUP_BEFORE = re.compile(r"mentions?\s*$", re.IGNORECASE)
PUNCTUATION = str.maketrans({"“": '"', "”": '"', "’": "'", "−": "-", "–": "-", "‐": "-", "―": "-"})
EXTRA_KINDS = {2, 3, 17, 18, 19, 20, 22, 23, 34, 36, 39, 41, 42, 43}
XYZ_KINDS = {22, 23, 34}
LINK_KINDS = {42, 43}
KIND_GROUPS = {
    46: {0, 15, 25, 44}, 47: {17, 18, 19, 20, 36}, 48: XYZ_KINDS,
    49: {15, 16, 19, 30, 32, 33, 37, 39, 44}, 50: {2, 3, 39, 41}, 51: {4, 5, 38},
    52: {25, 26, 33, 34, 35, 36, 40, 41, 44, 45}, 53: {24, 32, 35},
    54: LINK_KINDS, 55: {8, 37},
}
MOD_KINDS = CARD_KIND | {
    "Fusion": 2, "Ritual": 4, "Spirit": 7, "Token": 10, "TunerNormal": 15,
    "Synchro": 17, "Xyz": 22, "Pendulum": 25, "TunerEffectSpecialSummonOnly": 30,
    "TunerFlipEffect": 32, "PendulumFlipEffect": 35, "SynchroPendulumEffect": 36,
    "UnionTunerEffect": 37, "RitualSpiritEffect": 38, "Link": 42, "PendulumTunerNormal": 44,
    "PendulumSpiritEffect": 45,
}
STAT_COMPARISONS = (operator.le, operator.lt, operator.eq, operator.ge, operator.gt, operator.ne)


def clean_text(value):
    text = unescape(value or "")
    text = re.sub(r"<rt>.*?</rt>", "", text, flags=re.IGNORECASE | re.DOTALL)
    return normalize("NFKC", re.sub(r"<[^>]+>", " ", text)).translate(PUNCTUATION)


def term(value):
    return re.sub(r"\s*-\s*", "-", " ".join(clean_text(value).casefold().split()))


def archetype_labels(cache):
    path = cache / "ex-reference/Archetypes.v1.6.1.json"
    if path.is_file():
        raw = path.read_bytes()
    else:
        with urlopen(ARCHETYPE_SOURCE, timeout=30) as response:
            raw = response.read()
    if sha256(raw).hexdigest() != ARCHETYPE_SHA256:
        raise ValueError("The WolfX 1.6.1 archetype catalog has changed")
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=path.parent) as directory:
            stage = Path(directory) / path.name
            stage.write_bytes(raw)
            os.replace(stage, path)
    return {row["code"]: term(row["name"]) for row in json.loads(raw)["archetypes"]
            if row["name"].strip() and not row["name"].startswith("|")}


def active_cards(project, replacement=None):
    """Read deck-editor IDs in mod order, including a card pool staged for a new build."""
    mods = project / "Mods"
    cards = {}
    found_pool = False
    for entry in load_json(mods / "modlist.json")["mods"]:
        name = entry["id"]
        if name == KOREAN_POOL_ID and replacement is not None:
            cards.update((row["id"], row) for row in replacement)
            found_pool = True
        elif entry["enabled"] and (mods / name / "mod.json").is_file():
            path = mods / name / MOD_CONTENT / "cards.json"
            if path.is_file():
                data = load_json(path)
                cards.update((row["id"], row) for row in (data if isinstance(data, list) else data.get("cards", ())))
    if replacement is not None and not found_pool:
        cards.update((row["id"], row) for row in replacement)
    path = project / MOD_CONTENT / "cards.json"
    if path.is_file():
        data = load_json(path)
        cards.update((row["id"], row) for row in (data if isinstance(data, list) else data.get("cards", ())))
    return cards


def utf16_string(data, start):
    end = start
    while end + 2 <= len(data) and data[end:end + 2] != b"\0\0":
        end += 2
    return data[start:end].decode("utf-16-le", errors="replace")


def card_profile(kind, attr, level, atk, defense, icon, race):
    monster = kind not in (13, 14)
    return {
        0: atk if monster else None, 1: attr,
        2: defense if monster and kind not in LINK_KINDS else None, 3: kind,
        4: level if monster and kind not in XYZ_KINDS | LINK_KINDS else None,
        5: icon if not monster else None, 6: race, 7: int(kind in EXTRA_KINDS),
        8: level if kind in XYZ_KINDS else None, 12: level if kind in LINK_KINDS else None,
    }


def mod_profile(row):
    kind = MOD_KINDS[row["kind"]]
    attribute = 8 if kind == 13 else 9 if kind == 14 else ATTRIBUTE.get(row.get("attribute"), 0)
    race = 30 if kind == 13 else 31 if kind == 14 else MONSTER_TYPE.get(row.get("type"), 26)
    atk, defense = (65535 if row.get(key) == "?" else row.get(key, 0) for key in ("atk", "def"))
    return card_profile(kind, attribute, row.get("level", 0), atk, defense, ICON.get(row.get("icon"), 0), race)


def stock_cards(archive):
    records = list(struct.iter_unpack("<II", archive["bin/card_prop.bin"].read()))
    ids = [a & 0x3FFF for a, _ in records]
    name_data = archive["bin/card_name_e.bin"].read()
    name_offsets = list(struct.iter_unpack("<II", archive["bin/card_indx_e.bin"].read()))
    profiles, names = {}, {}
    for cid, (a, b), (name_at, _) in zip(ids[1:], records[1:], name_offsets[1:]):
        atk, defense = (65535 if value == 511 else value * 10 for value in ((a >> 14) & 511, (a >> 23) & 511))
        profiles[cid] = card_profile((b >> 1) & 63, (b >> 7) & 15, (b >> 11) & 15, atk, defense,
                                     (b >> 15) & 7, (b >> 18) & 31)
        names[cid] = utf16_string(name_data, name_at)
    return ids, profiles, names


def stock_relations(archive, ids):
    data = archive["bin/tagdata.bin"].read()
    table_end = 8 * len(ids)
    tag_data = archive["bin/taginfo_e.bin"].read()
    tag_count, = struct.unpack_from("<I", tag_data)
    tags = {}
    for index in range(tag_count):
        offset = 4 + 52 * index
        group = tag_data[offset]
        conditions = tuple(field for field in struct.iter_unpack("<BBH", tag_data[offset + 4:offset + 36])
                           if field[0] != 255)
        if group in (1, 2) and conditions and all(
            kind in (0, 1, 2, 3, 4, 5, 6, 7, 8, 12) and op < len(STAT_COMPARISONS)
            and (kind != 3 or value < 46 or (value in KIND_GROUPS and op in (2, 5)))
            for kind, op, value in conditions
        ):
            tags[index] = group, conditions

    existing = defaultdict(set)
    observations = defaultdict(set)
    for source, (start, count) in zip(ids, struct.iter_unpack("<II", data[:table_end])):
        if not source:
            continue
        first = table_end + 4 * start
        last = first + 4 * count
        if last + 4 > len(data) or data[last:last + 4] != b"\0\0\0\0":
            raise ValueError(f"Invalid related-card range for stock card {source}")
        for target, tag in struct.iter_unpack("<HH", data[first:last]):
            existing[source].add(target)
            if tag in tags:
                effect, match = (target, source) if tags[tag][0] == 1 else (source, target)
                observations[effect, tag].add(match)
    return existing, observations, tags


def quoted_terms(value):
    text = clean_text(value)
    for quote in QUOTED.finditer(text):
        key = term(next(item for item in quote.groups() if item is not None))
        group_use = bool(GROUP_AFTER.match(text, quote.end()) or GROUP_BEFORE.search(text[:quote.start()]))
        yield key, group_use


def card_indexes(catalog, cards, stock_names):
    titles = defaultdict(set)
    mentions = defaultdict(set)
    groups = defaultdict(set)
    for card, name in stock_names.items():
        titles[term(name)].add(card)
    for display, metadata in catalog.items():
        names, text, series = metadata
        for name in names:
            if name:
                titles[term(name)].add(display)
        for effect in text:
            mentions[display].update(quoted_terms(effect))
        for label in series:
            groups[term(label)].add(display)
    for display, row in cards.items():
        titles[term(row["name"])].add(display)
        mentions[display].update(quoted_terms(row.get("description")))
    return titles, mentions, groups


def group_members(project, labels, cards, catalog_groups, mentions, displays):
    group_uses = {key for terms in mentions.values() for key, qualified in terms if qualified}
    families = defaultdict(set)
    for key in group_uses & catalog_groups.keys():
        families[key].update(catalog_groups[key])
    for display, row in cards.items():
        for code in row.get("archetypes", []):
            if code in labels:
                families[labels[code]].add(display)

    path = project / "Mods/Master Duel Engine" / TABLE_NAME
    if not path.is_file():
        return families, {}
    raw, _ = apply_memberships(path.read_bytes())
    native = decode_card_groups(raw)
    by_native_name = defaultdict(set)
    for group in range(1, min(len(native), LAST_STOCK_GROUP + 1)):
        if group in labels and native[group]:
            by_native_name[labels[group]].update(displays[cid] for cid in native[group] if cid in displays)
    # Legacy archetypes use their engine membership, including the stock cards.
    for key, members in by_native_name.items():
        if members:
            families[key] = members
    for group, name in VERIFIED_FAMILIES.items():
        families[term(name)] = {displays[cid] for cid in native[group] if cid in displays}

    reference_groups = {}
    for group, name in NAME_REFERENCE_GROUPS.items():
        key = term(name)
        reference_groups[key] = {displays[cid] for cid in native[group] if cid in displays}
        families.pop(key, None)
    return families, reference_groups


def specific_ids(value):
    if type(value) is int:
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from specific_ids(item)


def materials(row):
    for key in ("fusion", "ritualSpell"):
        yield from specific_ids(row.get(key))
    for key, fields in (("synchro", ("tuner", "nonTuner")), ("xyz", ("material",)),
                        ("link", ("material", "condition", "including"))):
        for field in fields:
            yield from specific_ids(row.get(key, {}).get(field))


def add_named_relations(add, titles, mentions, families, reference_groups):
    for source, words in mentions.items():
        for key, _ in sorted(words):
            for target in titles.get(key, ()):
                add(source, target, NAMES_CARD)
                add(target, source, NAMED_BY)

    for groups, tag in ((families, SAME_FAMILY), (reference_groups, FAMILY_SUPPORT)):
        for members in groups.values():
            for source in members:
                for target in members:
                    add(source, target, tag)

    for source, words in mentions.items():
        for key, qualified in sorted(words):
            if key in titles and not qualified:
                continue
            members = reference_groups.get(key, families.get(key, ()))
            for target in members:
                add(source, target, FAMILY_SUPPORT)
                add(target, source, FAMILY_SUPPORT)


def add_stat_relations(add, stock, cards, observations, tags):
    # A game's tag can summarize only part of an effect. Extend a condition
    # only when its complete vanilla match set agrees with the displayed links.
    @lru_cache(maxsize=None)
    def matches(conditions, custom):
        profiles = cards if custom else stock
        return {cid for cid, values in profiles.items() if values[3] != 10
                and all(matches_condition(values[kind], kind, op, expected) for kind, op, expected in conditions)}

    accepted = 0
    for (effect, tag), targets in sorted(observations.items()):
        group, conditions = tags[tag]
        if matches(conditions, False) - {effect} != targets - {effect}:
            continue
        accepted += 1
        for candidate in matches(conditions, True):
            source, target = (candidate, effect) if group == 1 else (effect, candidate)
            add(source, target, tag)
    return accepted


def matches_condition(actual, kind, op, expected):
    if actual is None:
        return False
    if kind == 3 and expected in KIND_GROUPS:
        return (actual in KIND_GROUPS[expected]) == (op == 2)
    return STAT_COMPARISONS[op](actual, expected)


def build_related(project, cache, seed, replacement=None):
    archive = index_dat(project / "YGO_2020.dat")
    ids, stock, stock_names = stock_cards(archive)
    cards = active_cards(project, replacement)
    active = stock.keys() | cards.keys()
    displays = {cid: cid for cid in stock}
    displays.update((row["konamiId"], display) for display, row in cards.items() if row.get("konamiId"))
    catalog = {
        displays[row["konami_id"]]: (
            tuple(row.get("name", {}).get(lang) for lang in ("en", "ko")),
            tuple((row.get(field) or {}).get(lang) for field in ("text", "pendulum_effect") for lang in ("en", "ko")),
            row.get("series", []),
        )
        for row in load_json(cache / "yaml-yugi-cards.json") if row.get("konami_id") in displays
    }
    labels = archetype_labels(cache)
    titles, mentions, catalog_groups = card_indexes(catalog, cards, stock_names)
    families, references = group_members(project, labels, cards, catalog_groups, mentions, displays)
    known, observations, tags = stock_relations(archive, ids)
    entries = list(seed.get("cards", ()))
    entry_index = {row["card"]: index for index, row in enumerate(entries)}
    for row in entries:
        source = row["card"]
        known[source].update(unit["card"] for unit in row.get("add", ()))
        known[source].update(unit["card"] for unit in row.get("remove", ()))

    added = defaultdict(dict)
    inline = {cid: row["related"] for cid, row in cards.items() if isinstance(row.get("related"), list)}

    def add(source, target, tag):
        if (source != target and source in active and target in active and source not in inline
                and (source in cards or target in cards) and target not in known.get(source, ())):
            added[source].setdefault(target, tag)

    for source, row in cards.items():
        for target in materials(row):
            add(source, target, SUMMON_MATERIAL)
            add(target, source, SUMMON_MATERIAL)

    add_named_relations(add, titles, mentions, families, references)
    stat_filters = add_stat_relations(add, stock, {cid: mod_profile(row) for cid, row in cards.items()}, observations, tags)

    for source, links in added.items():
        index = entry_index.get(source)
        row = entries[index] if index is not None else {"card": source}
        updated = {**row, "add": [*row.get("add", ()), *(
            {"card": target, "tag": tag} for target, tag in sorted(links.items())
        )]}
        if index is None:
            entries.append(updated)
        else:
            entries[index] = updated
    result = {**seed, "cards": sorted(entries, key=lambda row: row["card"])}
    covered = {row["card"] for row in entries if row.get("add")} - inline.keys()
    covered.update(cid for cid, links in inline.items() if links)
    return result, {"new_links": sum(map(len, added.values())), "changed_cards": len(added),
                    "imported_cards_with_links": len(covered & cards.keys()), "imported_cards": len(cards),
                    "validated_stat_filters": stat_filters}


def write_related(path, data):
    # One card per line keeps this generated file smaller and diffable.
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("{\n")
        for key, value in data.items():
            if key != "cards":
                stream.write(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},\n")
        stream.write('  "cards": [\n')
        for index, row in enumerate(data["cards"]):
            if index:
                stream.write(",\n")
            stream.write("    " + json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        stream.write("\n  ]\n}\n")


def install(project, cache, output=None):
    current = project / "Mods" / KOREAN_POOL_ID / MOD_CONTENT / RELATED_FILE
    original = current.read_bytes()
    result, stats = build_related(project, cache, json.loads(original.decode("utf-8-sig")))
    if output is not None:
        write_related(output, result)
    elif stats["new_links"]:
        backups = cache / "pc-duel-backups"
        backups.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=current.parent, prefix=".related-cards-") as directory:
            stage = Path(directory) / current.name
            write_related(stage, result)
            with NamedTemporaryFile(dir=backups, prefix="relatedcards.before-rebuild-", suffix=".json", delete=False) as backup:
                backup.write(original)
            if current.read_bytes() != original:
                raise RuntimeError("The active related-card file changed during the rebuild")
            os.replace(stage, current)
        stats["backup"] = backup.name
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--catalog", type=Path,
                        default=Path(os.environ["LOCALAPPDATA"]) / "YGO-PC-Full/CardCatalog")
    parser.add_argument("--output", type=Path, help="Write a test copy of the related-card data")
    args = parser.parse_args()
    print(json.dumps(install(args.project, args.catalog, args.output)))


if __name__ == "__main__":
    main()
