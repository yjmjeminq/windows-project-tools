"""Install the missing PC card definitions through the January 2026 release cutoff."""

import argparse
from copy import deepcopy
from datetime import date
from io import BytesIO
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from PIL import Image

from build_card_data import PORT_DIRECTORY, index_dat


CUTOFF = date(2026, 1, 31)
# The catalog omits this debut date. Konami lists it as DUAD-JP071.
VERIFIED_DEBUT_DATES = {21482: date(2025, 4, 26)}
MOD_ID = "2026-01-Cards"
SOURCE_PREFIX = "Mods/Cards/Yu-Gi-Oh-Ex/"
MOD_CONTENT = "Yu-Gi-Oh-Ex"
ENGINE_MAX_ID = 0x7FFF
SOURCE_ARTIFACT = "Yu-Gi-Oh-Ex-v1.6.1-Mods.zip"


def load_json(path):
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path, data):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def original_pool(project):
    stock = index_dat(project / "YGO_2020.dat")["bin/card_prop.bin"].read()
    stock_ids = {word & 0x3FFF for word, _ in struct.iter_unpack("<II", stock)} - {0}
    allocated = set(stock_ids)
    by_konami_id = {card_id: card_id for card_id in stock_ids}
    prior_archetypes = set()
    for mod in sorted((project / "Mods").iterdir()):
        directory = mod / MOD_CONTENT
        path = directory / "cards.json"
        if path.is_file():
            for card in load_json(path)["cards"]:
                card_id = card["id"]
                if card_id in allocated:
                    raise ValueError(f"Existing card ID {card_id} is already used")
                allocated.add(card_id)
                if card.get("konamiId"):
                    by_konami_id.setdefault(card["konamiId"], card_id)
        path = directory / "Archetypes.json"
        if path.is_file():
            prior_archetypes.update(row["code"] for row in load_json(path)["archetypes"])
    return allocated, by_konami_id, prior_archetypes


def release_date(details):
    dates = []
    for key in ("ocg_date", "tcg_date"):
        if details.get(key):
            try:
                dates.append(date.fromisoformat(details[key]))
            except ValueError:
                continue
    return min(dates, default=None)


def missing_cards(catalog, existing):
    selected = {}
    for card in catalog:
        details = (card.get("misc_info") or [{}])[0]
        card_id = details.get("konami_id")
        first_release = VERIFIED_DEBUT_DATES.get(card_id) or release_date(details)
        if (type(card_id) is not int or card_id <= 0 or card_id in existing
                or first_release is None or first_release > CUTOFF
                or card.get("frameType") in ("token", "skill")
                or "Rush Duel" in card["type"] or details.get("formats") == ["Rush Duel"]):
            continue
        previous = selected.get(card_id)
        if previous is None or first_release < previous[0]:
            selected[card_id] = first_release, card
    return selected


def translate_reference(value, id_map):
    if type(value) is int:
        return id_map.get(value, value)
    if isinstance(value, list):
        return [translate_reference(item, id_map) for item in value]
    return value


def translate_materials(card, id_map):
    for key in ("fusion", "ritualSpell", "sameName"):
        if key in card:
            card[key] = translate_reference(card[key], id_map)
    for key in ("synchro", "xyz", "link"):
        for field in ("material", "condition"):
            if field in card.get(key, {}):
                card[key][field] = translate_reference(card[key][field], id_map)


def fill_from_catalog(card_id, entry):
    if entry["type"] != "Spell Card" or entry.get("race") != "Normal":
        raise ValueError(f"No compatible source definition for card {card_id}")
    return {
        "konamiId": card_id,
        "password": entry["id"],
        "kind": "Spell",
        "icon": "Normal",
        "name": entry["name"],
        "description": entry["desc"],
    }


def localize(card, localization):
    name = localization.get("name", {}).get("ko")
    text = localization.get("text", {}).get("ko")
    has_name = isinstance(name, str) and bool(name.strip())
    has_text = isinstance(text, str) and bool(text.strip())
    if has_name:
        card["name"] = name.strip()
    if has_text:
        card["description"] = text.replace("\r\n", "\n").replace("\n", "\r\n").strip()
    return has_name and has_text


def art_bytes(archive, paths, cache, card_id, source):
    name = paths.get((SOURCE_PREFIX + source.get("image", "")).casefold())
    if name is not None and not name.endswith("/"):
        data = archive.read(name)
    else:
        data = (cache / "fallback-art" / f"{card_id}.jpg").read_bytes()
    with Image.open(BytesIO(data)) as image:
        if image.format != "JPEG" or image.width < 128 or image.height < 128:
            raise ValueError(f"Invalid artwork for card {card_id}")
        image.verify()
    return data


def build(project, cache):
    mods = (project / "Mods").resolve(strict=True)
    target = mods / MOD_ID
    if target.exists():
        raise ValueError(f"The card mod already exists at {target}")
    occupied, existing, prior_archetypes = original_pool(project)
    selected = missing_cards(load_json(cache / "cardinfo-misc.json")["data"], existing)
    official_january = set(load_json(cache / "blzd-ocg-official-ids.json"))
    if len(official_january) != 80 or official_january - (set(selected) | set(existing)):
        raise ValueError("The card catalog is missing cards from the official January OCG set")

    translations = {
        row["konami_id"]: row for row in load_json(cache / "yaml-yugi-cards.json")
        if row.get("konami_id") in selected
    }
    official_korean = cache / "official-ko-overrides.json"
    if official_korean.is_file():
        translations.update({int(card_id): row for card_id, row in load_json(official_korean).items()})
    with ZipFile(cache / SOURCE_ARTIFACT) as archive:
        source_cards = json.loads(archive.read(SOURCE_PREFIX + "cards.json"))["cards"]
        sources = {row["konamiId"]: row for row in source_cards if row.get("konamiId")}
        paths = {name.casefold(): name for name in archive.namelist()}
        archetypes = json.loads(archive.read(SOURCE_PREFIX + "Archetypes.json"))["archetypes"]
        new_ids = {}
        next_id = max(max(occupied), max(row["id"] for row in source_cards)) + 1
        for card_id in sorted(selected):
            preferred = sources.get(card_id, {}).get("id")
            if preferred is None or preferred in occupied:
                preferred = next_id
                next_id += 1
            if not 0 < preferred <= ENGINE_MAX_ID:
                raise ValueError("The new card ID does not fit the PC engine")
            new_ids[card_id] = preferred
            occupied.add(preferred)

        by_konami_id = existing | new_ids
        source_ids = {
            row["id"]: by_konami_id[row["konamiId"]] for row in source_cards
            if row.get("konamiId") in by_konami_id
        }
        id_map = by_konami_id | source_ids
        output = []
        fully_korean = 0
        fallback_art = 0
        fallback_definitions = 0
        used_archetypes = set()
        with TemporaryDirectory(dir=mods, prefix=".card-pool-") as directory:
            stage = Path(directory).resolve()
            if stage.parent != mods:
                raise ValueError("The card staging directory is outside Mods")
            prepared = stage / MOD_ID
            content = prepared / MOD_CONTENT
            art = content / "art"
            art.mkdir(parents=True)
            for card_id, (first_release, catalog_card) in sorted(
                selected.items(), key=lambda item: (item[1][0], item[0])
            ):
                source = sources.get(card_id)
                if source is None:
                    card = fill_from_catalog(card_id, catalog_card)
                    fallback_definitions += 1
                else:
                    card = deepcopy(source)
                    for key in ("effectScript", "effectClone", "effectLooser"):
                        card.pop(key, None)
                translate_materials(card, id_map)
                card["id"] = new_ids[card_id]
                card["copies"] = 3
                card["image"] = f"art/{card_id}.jpg"
                fully_korean += localize(card, translations.get(card_id, {}))
                used_archetypes.update(card.get("archetypes", []))
                source = source or {}
                if not source.get("image") or (SOURCE_PREFIX + source["image"]).casefold() not in paths:
                    fallback_art += 1
                (art / f"{card_id}.jpg").write_bytes(art_bytes(archive, paths, cache, card_id, source))
                output.append(card)

            write_json(content / "cards.json", {"cards": output})
            write_json(content / "Archetypes.json", {"archetypes": [
                row for row in archetypes if row["code"] in used_archetypes - prior_archetypes
            ]})
            write_json(prepared / "mod.json", {
                "name": "Card pool through January 2026",
                "version": "1.0",
                "description": f"Adds {len(output):,} cards first released in the OCG or TCG by {CUTOFF}.",
                "details": "Adds three copies per card. Uses Konami card IDs with the offline Master Duel Engine.",
                "author": "Card data and art from Yu-Gi-Oh-Ex, YGOPRODeck, and YAML Yugi",
                "requires": ["Yu-Gi-Oh-Cards", "Yu-Gi-Oh-Core/MasterDuelEngine"],
            })
            if prepared.resolve().parent != stage or target.resolve().parent != mods:
                raise ValueError("The installation path is outside Mods")
            prepared.rename(target)

    return {
        "mod": MOD_ID,
        "added": len(output),
        "korean_name_and_text": fully_korean,
        "first_printed_in_january_2026": sum(d.year == 2026 and d.month == 1 for d, _ in selected.values()),
        "january_ocg_set_present": len(official_january),
        "fallback_definitions": fallback_definitions,
        "fallback_art": fallback_art,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--catalog", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "YGO-PC-Full/CardCatalog")
    args = parser.parse_args()
    print(json.dumps(build(args.project, args.catalog)))


if __name__ == "__main__":
    main()
