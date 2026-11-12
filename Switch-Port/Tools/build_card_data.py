"""Convert the PC card additions into Switch 1.0.1 card tables and artwork."""

import argparse
from dataclasses import dataclass
from itertools import chain
import json
from pathlib import Path
import struct
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


PORT_DIRECTORY = Path(__file__).resolve().parents[1]
FIRST_CARD_ID = 3900
LAST_STOCK_CARD_ID = 14968
FIRST_ID_AFTER_RESERVED_EFFECTS = 15235
LAST_CARD_ID = 16383
STOCK_CARD_COUNT = 10165
LANGUAGES = "EFGIJRS"
ART_FILE = "2020.patch.illust_j.jpg.zib"

CARD_KIND = {
    "Normal": 0, "Effect": 1, "FusionEffect": 3, "RitualEffect": 5,
    "Toon": 6, "Union": 8, "Gemini": 9, "Spell": 13, "Trap": 14,
    "TunerEffect": 16, "SynchroEffect": 18, "SynchroTunerEffect": 19,
    "XyzEffect": 23, "FlipEffect": 24, "PendulumEffect": 26,
    "EffectSpecialSummonOnly": 27, "ToonSpecialSummonOnly": 28,
    "SpiritSpecialSummonOnly": 29, "PendulumTunerEffect": 33,
    "XyzPendulumEffect": 34, "FusionTuner": 39,
    "PendulumEffectSpecialSummonOnly": 40, "FusionPendulumEffect": 41,
    "LinkEffect": 43,
}
MONSTER_TYPE = {name: code for code, name in enumerate((
    "None", "Dragon", "Zombie", "Fiend", "Pyro", "SeaSerpent", "Rock",
    "Machine", "Fish", "Dinosaur", "Insect", "Beast", "BeastWarrior",
    "Plant", "Aqua", "Warrior", "WingedBeast", "Fairy", "Spellcaster",
    "Thunder", "Reptile", "Psychic", "Wyrm", "Cyberse", "DivineBeast",
    "CreatorGod",
))}
ATTRIBUTE = {
    "Light": 1, "Dark": 2, "Water": 3, "Fire": 4, "Earth": 5, "Wind": 6,
    "Divine": 7,
}
ICON = {
    "None": 0, "Normal": 0, "Counter": 1, "Field": 2, "Equip": 3,
    "Continuous": 4, "QuickPlay": 5, "Ritual": 6,
}
LINK_MARKER = {name: 1 << bit for bit, name in enumerate((
    "Top-Left", "Top", "Top-Right", "Left", "Right",
    "Bottom-Left", "Bottom", "Bottom-Right",
))}


@dataclass(frozen=True)
class FileSlice:
    path: Path
    offset: int
    size: int

    def read(self):
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(self.size)
        if len(data) != self.size:
            raise ValueError(f"Unexpected end of {self.path}")
        return data


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


def index_dat(path):
    with path.with_suffix(".toc").open(encoding="utf-8-sig") as table:
        if table.readline().strip() != "UT":
            raise ValueError(f"Invalid table header for {path}")
        offset = 0
        end = 0
        files = {}
        for row in table:
            if not row.strip():
                continue
            size_hex, _, filename = row.strip().split(maxsplit=2)
            size = int(size_hex, 16)
            name = filename.replace("\\", "/").casefold()
            if name in files:
                raise ValueError(f"Duplicate DAT entry {filename}")
            files[name] = FileSlice(path, offset, size)
            end = offset + size
            offset = align(end, 4)
    if not end <= path.stat().st_size <= offset:
        raise ValueError(f"DAT size does not match the table for {path}")
    return files


def load_cards(project):
    sources = ("2020-2021-Cards", "Anime-Sanctity")
    cards = {}
    for name in sources:
        directory = (project / "Mods" / name / "Yu-Gi-Oh-Ex").resolve()
        content = json.loads((directory / "cards.json").read_text(encoding="utf-8-sig"))
        for card in content["cards"]:
            pc_id = card["id"]
            if type(pc_id) is not int or pc_id <= 0 or pc_id in cards:
                raise ValueError(f"Invalid or duplicate PC card ID {pc_id!r}")
            image = (directory / card["image"]).resolve()
            if not image.is_relative_to(directory) or not image.is_file():
                raise ValueError(f"Missing art for PC card {pc_id}")
            cards[pc_id] = (card, image)
    return sorted(cards.values(), key=lambda entry: entry[0]["id"])


def assign_ids(stock_ids, cards):
    allowed = set(range(FIRST_CARD_ID, LAST_CARD_ID + 1))
    allowed.difference_update(range(LAST_STOCK_CARD_ID + 1, FIRST_ID_AFTER_RESERVED_EFFECTS))
    available = allowed - stock_ids
    ids = {}
    for card, _ in cards:
        original = card.get("konamiId")
        if original in available:
            ids[card["id"]] = original
            available.remove(original)

    upper_ids = range(FIRST_ID_AFTER_RESERVED_EFFECTS, LAST_CARD_ID + 1)
    lower_ids = range(FIRST_CARD_ID, LAST_STOCK_CARD_ID + 1)
    free_ids = (target for target in chain(upper_ids, lower_ids) if target in available)
    for card, _ in cards:
        if card["id"] not in ids:
            try:
                ids[card["id"]] = next(free_ids)
            except StopIteration as error:
                raise ValueError("The card IDs do not fit in the Switch property format") from error
    return ids


def packed_stat(value):
    if value in ("?", -1):
        return 511
    if type(value) is not int or not 0 <= value <= 5100 or value % 10:
        raise ValueError(f"Invalid ATK or DEF value {value!r}")
    return value // 10


def pack_property(card, switch_id):
    kind = CARD_KIND[card["kind"]]
    icon = ICON[card.get("icon", "None")]
    if card["kind"] in ("Spell", "Trap"):
        attribute, race = (8, 30) if card["kind"] == "Spell" else (9, 31)
        level = attack = defense = 0
    else:
        attribute = ATTRIBUTE[card["attribute"]]
        race = MONSTER_TYPE[card["type"]]
        level = card["level"]
        attack = packed_stat(card.get("atk", 0))
        if card["kind"] == "LinkEffect":
            markers = set(card["linkmarkers"])
            defense = sum(LINK_MARKER[marker] for marker in markers)
            if len(markers) != level:
                raise ValueError(f"Invalid Link Rating for PC card {card['id']}")
        else:
            defense = packed_stat(card.get("def", 0))

    scale = card.get("scale", 0)
    if not 0 <= level <= 15 or not 0 <= scale <= 15:
        raise ValueError(f"Level or Pendulum Scale is out of range for PC card {card['id']}")
    first = switch_id | (attack << 14) | (defense << 23)
    second = 1 | (kind << 1) | (attribute << 7) | (level << 11)
    second |= (icon << 15) | (race << 18) | (scale << 23) | (scale << 27)
    return struct.pack("<II", first, second)


def stock_card_tables(files):
    props = files["bin/card_prop.bin"].read()
    lookup = files["bin/card_intid.bin"].read()
    record_ids = [first & LAST_CARD_ID for first, _ in struct.iter_unpack("<II", props)]
    ids = set(record_ids[1:])
    if len(record_ids) != STOCK_CARD_COUNT + 1 or record_ids[0] or len(ids) != STOCK_CARD_COUNT:
        raise ValueError("Expected the stock Switch 1.0.1 card properties")
    if len(lookup) != 2 * (LAST_STOCK_CARD_ID - FIRST_CARD_ID + 1):
        raise ValueError("Unexpected Switch 1.0.1 card ID table size")
    for index, card_id in enumerate(record_ids[1:], 1):
        if not FIRST_CARD_ID <= card_id <= LAST_STOCK_CARD_ID:
            raise ValueError(f"Unexpected stock card ID {card_id}")
        if struct.unpack_from("<H", lookup, 2 * (card_id - FIRST_CARD_ID))[0] != index:
            raise ValueError(f"Card ID lookup disagrees with the property table for {card_id}")
    return props, lookup, ids


def append_text(buffer, value):
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("Card text must be a string without embedded NULs")
    offset = len(buffer)
    buffer.extend(value.encode("utf-16-le") + b"\0\0")
    buffer.extend(bytes(align(len(buffer), 4) - len(buffer)))
    return offset


def expanded_text(files, language, cards):
    index_path = f"bin/CARD_Indx_{language}.bin"
    name_path = f"bin/CARD_Name_{language}.bin"
    desc_path = f"bin/CARD_Desc_{language}.bin"
    index = files[index_path.casefold()].read()
    names = bytearray(files[name_path.casefold()].read())
    descriptions = bytearray(files[desc_path.casefold()].read())
    if (len(index) != 8 * (STOCK_CARD_COUNT + 2)
            or struct.unpack_from("<II", index, len(index) - 8) != (len(names), len(descriptions))):
        raise ValueError(f"Unexpected card text table for {language}")
    expanded = bytearray(index[:-8])
    for card, _ in cards:
        text = card.get("text", {}).get(language, {})
        name_offset = append_text(names, text.get("name", card["name"]))
        desc_offset = append_text(descriptions, text.get("description", card["description"]))
        expanded.extend(struct.pack("<II", name_offset, desc_offset))
    expanded.extend(struct.pack("<II", len(names), len(descriptions)))
    return {index_path: expanded, name_path: names, desc_path: descriptions}


def read_zib_images(entry):
    with entry.path.open("rb") as stream:
        stream.seek(entry.offset)
        first, = struct.unpack(">I", stream.read(4))
        count = first // 64
        if count == 0 or (first & ~15) != 64 * count + 16:
            raise ValueError("Unexpected Switch artwork archive header")
        stream.seek(entry.offset)
        table = stream.read(64 * count)
    images = {}
    end = first & ~15
    for index, (address, size, field) in enumerate(struct.iter_unpack(">II56s", table)):
        offset = address & ~15
        name = field.split(b"\0", 1)[0].decode("ascii")
        if (not name.endswith(".jpg") or name in images or offset < end
                or offset + size > entry.size or address & 15 != (1 if index == 0 else 0)):
            raise ValueError("Invalid entry in the Switch artwork archive")
        images[name] = FileSlice(entry.path, entry.offset + offset, size)
        end = offset + size
    return images


def write_zib(archive, images):
    ordered = sorted(images.items())
    header = bytearray()
    offset = 64 * len(ordered) + 16
    for index, (name, image) in enumerate(ordered):
        header.extend(struct.pack(">II56s", offset | (1 if index == 0 else 0),
                                  image.size, name.encode("ascii")))
        offset = align(offset + image.size, 16)
    with archive.open(ART_FILE, "w") as output:
        output.write(header)
        output.write(bytes(16))
        for name, image in ordered:
            data = image.read()
            if not data.startswith(b"\xff\xd8"):
                raise ValueError(f"Card artwork is not JPEG: {name}")
            output.write(data)
            output.write(bytes(align(len(data), 16) - len(data)))


def build(project, romfs, output):
    files = index_dat(romfs / "YGO_DATA.dat") | index_dat(romfs / "YGO_2020.dat")
    cards = load_cards(project)
    original_properties, original_lookup, stock_ids = stock_card_tables(files)
    switch_ids = assign_ids(stock_ids, cards)
    images = read_zib_images(files[ART_FILE])

    properties = bytearray(original_properties)
    lookup = bytearray(original_lookup)
    last_id = max(LAST_STOCK_CARD_ID, max(switch_ids.values(), default=FIRST_CARD_ID))
    required_size = 2 * (last_id - FIRST_CARD_ID + 1)
    lookup.extend(bytes(required_size - len(lookup)))
    mapping = []
    for card, image in cards:
        target = switch_ids[card["id"]]
        offset = 2 * (target - FIRST_CARD_ID)
        if struct.unpack_from("<H", lookup, offset)[0] != 0:
            raise ValueError(f"Card ID {target} is already in use")
        slot = len(properties) // 8
        struct.pack_into("<H", lookup, offset, slot)
        properties.extend(pack_property(card, target))

        filename = f"{target}.jpg"
        if filename in images:
            raise ValueError(f"Card artwork {filename} is already in use")
        images[filename] = FileSlice(image, 0, image.stat().st_size)
        mapping.append({
            "pc_id": card["id"],
            "konami_id": card.get("konamiId"),
            "switch_id": target,
            "record_index": slot,
            "name": card["name"],
            "source_image": image.relative_to(project).as_posix(),
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        with ZipFile(staged, "w", ZIP_DEFLATED) as archive:
            archive.writestr("bin/CARD_Prop.bin", properties)
            archive.writestr("bin/CARD_IntID.bin", lookup)
            for language in LANGUAGES:
                for name, data in expanded_text(files, language, cards).items():
                    archive.writestr(name, data)
            archive.writestr("card-map.json", json.dumps({
                "version": "1.0.1",
                "stock_cards": STOCK_CARD_COUNT,
                "native_code_changes_required": True,
                "cards": mapping,
            }, ensure_ascii=False, indent=2))
            archive.compression = ZIP_STORED
            write_zib(archive, images)
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    return len(mapping)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--romfs", type=Path, default=PORT_DIRECTORY / "1.0.1/RomFS")
    parser.add_argument("--output", type=Path, default=PORT_DIRECTORY / "Link-Evolution-1.0.1-card-data.zip")
    args = parser.parse_args()
    count = build(args.project.resolve(), args.romfs, args.output)
    print(f"{count} added cards converted to {args.output.resolve()}")


if __name__ == "__main__":
    main()
