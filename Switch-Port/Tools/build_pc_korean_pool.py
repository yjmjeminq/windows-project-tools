"""Build the PC card pool from the Korean releases through November 12, 2026."""

import argparse
from copy import deepcopy
from html import unescape
import json
import os
from pathlib import Path
import re
from shutil import copyfile
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from build_pc_card_pool import (
    MOD_CONTENT,
    SOURCE_ARTIFACT,
    SOURCE_PREFIX,
    art_bytes,
    load_json,
    original_pool,
    translate_materials,
    write_json,
)
from build_card_data import PORT_DIRECTORY
from build_pc_related_cards import KOREAN_POOL_ID, RELATED_FILE, build_related, write_related


CUTOFF = "2026-11-12"
MOD_ID = KOREAN_POOL_ID
PREVIOUS_POOLS = ("2020-2021-Cards", "2026-01-Cards")
REQUIRED_SETS = {"1010001641000": 80, "1010001740000": 80, "1010001750000": 60}
PENDULUM_MARKER = "\r\n[Pendulum Effect]\r\n"
PRIZE_TYPES = {
    "비행야수족": "WingedBeast",
    "암석족": "Rock",
    "마법사족": "Spellcaster",
    "공룡족": "Dinosaur",
    "드래곤족": "Dragon",
    "사이버스족": "Cyberse",
    "천사족": "Fairy",
    "야수전사족": "BeastWarrior",
}
PRIZE_ATTRIBUTES = {"빛": "Light", "어둠": "Dark", "바람": "Wind"}
LINK_DIRECTIONS = {
    "1": "Bottom-Left", "2": "Bottom", "3": "Bottom-Right",
    "4": "Left", "6": "Right", "7": "Top-Left", "8": "Top", "9": "Top-Right",
}


def korean_release_ids(cache):
    products = {}
    for product in load_json(cache / "korean-product-index.json"):
        if not "2020-01-01" <= product["date"] <= CUTOFF:
            continue
        product_id = product["id"]
        release = load_json(cache / "korean-releases" / f"{product_id}.json")
        if release["date"] != product["date"] or release["name"] != product["name"]:
            raise ValueError(f"Official product does not match the Korean index: {product_id}")
        products[product_id] = set(release["cards"])
    for product_id, count in REQUIRED_SETS.items():
        if len(products[product_id]) != count:
            raise ValueError(f"Incomplete official product: {product_id}")
    return set().union(*products.values()), len(products)


def game_text(value):
    value = re.sub(r"<br\s*/?>", "\n", unescape(value), flags=re.IGNORECASE)
    value = re.sub(r"<rt>(.*?)</rt>", r"(\1)", value, flags=re.IGNORECASE)
    value = re.sub(r"</?ruby>", "", value, flags=re.IGNORECASE)
    return "\r\n".join(line.strip() for line in value.splitlines() if line.strip())


def korean_text(card_id, translations):
    row = translations[card_id]
    name = game_text(row["name"]["ko"])
    text = game_text(row["text"]["ko"])
    pendulum = row.get("pendulum_effect", {}).get("ko")
    if pendulum:
        text += PENDULUM_MARKER + game_text(pendulum)
    if not name or not text:
        raise ValueError(f"Empty Korean card text for {card_id}")
    return name, text


def prize_definition(card_id, official):
    """Describe match-win prize cards missing from the upstream playable catalog."""
    text = official["text"]["ko"]
    if "매치에서 승리" not in text:
        raise ValueError(f"No compatible card definition for {card_id}")
    attribute, level = official["official_attributes"]
    race = PRIZE_TYPES[official["official_race"]]
    link = official["official_link"]
    card = {
        "konamiId": card_id,
        "kind": "LinkEffect" if link else "Effect",
        "type": race,
        "attribute": PRIZE_ATTRIBUTES[attribute],
        "level": int(level.split()[-1]),
        "atk": int(official["official_atk"]),
        "def": 0 if link else int(official["official_def"]),
        "typeline": [race, "Link", "Effect"] if link else [race, "Effect"],
        "limitation": "Forbidden",
    }
    if link:
        card["linkmarkers"] = [LINK_DIRECTIONS[marker] for marker in link]
    return card


def copy_existing_pool(mods, content, korean_ids, translations):
    cards = []
    archetypes = {}
    changed = 0
    for mod_id in PREVIOUS_POOLS:
        previous = mods / mod_id / MOD_CONTENT
        for row in load_json(previous / "cards.json")["cards"]:
            cid = row["konamiId"]
            if cid in korean_ids:
                name, description = korean_text(cid, translations)
                changed += (name, description) != (row["name"], row["description"])
                row.update(name=name, description=description)
            source = (previous / row["image"]).resolve(strict=True)
            if not source.is_relative_to(previous):
                raise ValueError(f"Artwork outside card mod: {source}")
            row["image"] = f"art/{cid}.jpg"
            copyfile(source, content / row["image"])
            cards.append(row)
        for row in load_json(previous / "Archetypes.json")["archetypes"]:
            archetypes[row["code"]] = row
    return cards, archetypes, changed


def build(project, cache):
    mods = (project / "Mods").resolve(strict=True)
    target = mods / MOD_ID
    if target.exists():
        raise FileExistsError(target)

    occupied, installed, _ = original_pool(project)
    korean_ids, product_count = korean_release_ids(cache)
    missing = korean_ids - installed.keys()
    translations = {
        row["konami_id"]: row
        for row in load_json(cache / "yaml-yugi-cards.json")
        if row.get("konami_id") in korean_ids
    }
    official = {
        int(card_id): row for card_id, row in
        load_json(cache / "official-ko-november-overrides.json").items()
    }
    translations.update(official)

    with ZipFile(cache / SOURCE_ARTIFACT) as archive, TemporaryDirectory(
        dir=mods, prefix=".korean-card-pool-"
    ) as directory:
        stage = Path(directory).resolve(strict=True)
        if stage.parent != mods:
            raise ValueError("The card staging directory is outside Mods")
        prepared = stage / MOD_ID
        content = prepared / MOD_CONTENT
        (content / "art").mkdir(parents=True)
        cards, archetypes, localized = copy_existing_pool(mods, content, korean_ids, translations)
        source_cards = json.loads(archive.read(SOURCE_PREFIX + "cards.json"))["cards"]
        sources = {row["konamiId"]: row for row in source_cards if row.get("konamiId")}
        paths = {name.casefold(): name for name in archive.namelist()}

        new_ids = {}
        next_id = max(max(occupied), max(row["id"] for row in source_cards)) + 1
        for cid in sorted(missing):
            preferred = sources.get(cid, {}).get("id")
            if preferred is None or preferred in occupied:
                preferred = next_id
                next_id += 1
            if not 15300 <= preferred <= 0x7FFF:
                raise ValueError(f"Card {cid} needs a supported PC card ID")
            new_ids[cid] = preferred
            occupied.add(preferred)

        id_by_cid = installed | new_ids
        source_id_map = {
            row["id"]: id_by_cid[row["konamiId"]]
            for row in source_cards if row.get("konamiId") in id_by_cid
        }
        material_ids = id_by_cid | source_id_map
        prizes = 0
        for cid in sorted(missing):
            source = sources.get(cid)
            if source is None:
                card = prize_definition(cid, official[cid])
                prizes += 1
            else:
                card = deepcopy(source)
                for key in ("effectScript", "effectClone", "effectLooser"):
                    card.pop(key, None)
                translate_materials(card, material_ids)

            name, description = korean_text(cid, translations)
            card.update(id=new_ids[cid], name=name, description=description,
                        copies=3, image=f"art/{cid}.jpg")
            (content / card["image"]).write_bytes(art_bytes(archive, paths, cache, cid, source or {}))
            cards.append(card)

        engine_overrides = mods / "Master Duel Engine/CARD_PropOverrides_80460.json"
        if engine_overrides.is_file():
            dual_kinds = {row["id"] for row in load_json(engine_overrides)["cards"] if row.get("kind") == 52}
            for card in cards:
                cid = card["konamiId"]
                definition = translations.get(cid, {})
                if cid in dual_kinds and "pendulum_scale" in definition:
                    # Store the scale in the legacy format and restore the
                    # combined Ritual/Pendulum kind through the engine override.
                    card.update(kind="PendulumEffectSpecialSummonOnly", scale=definition["pendulum_scale"])

        used_codes = {code for card in cards for code in card.get("archetypes", [])}
        for row in json.loads(archive.read(SOURCE_PREFIX + "Archetypes.json"))["archetypes"]:
            if row["code"] in used_codes:
                archetypes.setdefault(row["code"], row)
        write_json(content / "Archetypes.json", {"archetypes": list(archetypes.values())})
        write_json(content / "cards.json", {"cards": cards})
        original_content = mods / PREVIOUS_POOLS[0] / MOD_CONTENT
        copyfile(original_content / "unlocks.json", content / "unlocks.json")
        related, related_stats = build_related(project, cache, load_json(original_content / RELATED_FILE), replacement=cards)
        write_related(content / RELATED_FILE, related)
        for filename in ("YGO_2020-Ex.dat", "YGO_2020-Ex.toc"):
            copyfile(mods / PREVIOUS_POOLS[0] / filename, prepared / filename)

        write_json(prepared / "mod.json", {
            "name": "한국판 카드 확장 2026-11-12",
            "version": "1.0",
            "description": "유틸리티 셀렉션까지 국내에 공개된 카드를 추가합니다.",
            "details": f"기존 확장 카드와 추가 카드 {len(missing):,}장을 담았습니다. "
                       "듀얼 중 카드 효과는 설치된 Master Duel Engine에서 처리합니다.",
            "author": "Konami, Yu-Gi-Oh-Ex, YGOPRODeck, YAML Yugi",
            "requires": ["Yu-Gi-Oh-Cards", "Yu-Gi-Oh-Core/MasterDuelEngine"],
        })
        prepared.rename(target)

    return {
        "mod": MOD_ID,
        "korean_products": product_count,
        "added": len(missing),
        "prize_cards": prizes,
        "existing_text_updates": localized,
        "card_records": len(cards),
        "related_card_links_added": related_stats["new_links"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--catalog", type=Path,
                        default=Path(os.environ["LOCALAPPDATA"]) / "YGO-PC-Full/CardCatalog")
    args = parser.parse_args()
    print(json.dumps(build(args.project, args.catalog)))


if __name__ == "__main__":
    main()
