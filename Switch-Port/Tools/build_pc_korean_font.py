"""Build Pretendard bitmap fonts for the Korean PC card pack."""

import argparse
from functools import cache
from io import BytesIO
import json
import os
from pathlib import Path
from shutil import copyfile
import struct
from tempfile import TemporaryDirectory
from typing import NamedTuple

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from build_card_data import PORT_DIRECTORY, align, index_dat


CARD_PACK = "2026-11-KR-Cards"
FONT_MOD = "Korean-Readable-Font"
ARCHIVE_NAME = "YGO_2020-Ex"
FONT_RECORD = struct.Struct("<5H13fI")
TITLE_FONTS = ("ycj_name", "matrixcaps_21")
PRETENDARD_RELEASE = "https://github.com/orioncactus/pretendard/releases/tag/v1.3.9"


class Glyph(NamedTuple):
    codepoint: int
    mapped_codepoint: int
    flags: int
    pixel_width: int
    pixel_height: int
    width: float
    height: float
    top: float
    left: float
    advance: float
    u0: float
    v0: float
    u1: float
    v1: float
    second_u0: float
    second_v0: float
    second_u1: float
    second_v1: float
    tail: int

    def box(self, width, height):
        return (round(self.u0 * width), round(self.v0 * height),
                round(self.u1 * width), round(self.v1 * height))


def read_font_table(data):
    # The NUL-terminated face name is followed by ten floats and two counted maps.
    header_end = data.index(b"\0", 8) + 1 + 10 * 4
    position = header_end
    maps = []
    for _ in range(2):
        count, = struct.unpack_from("<I", data, position)
        start = position + 4
        position = start + count * FONT_RECORD.size
        records = [Glyph(*values) for values in FONT_RECORD.iter_unpack(data[start:position])]
        codes = [record.codepoint for record in records]
        if len(records) != count or codes != sorted(set(codes)):
            raise ValueError("Invalid bitmap font glyph table")
        maps.append({record.codepoint: record for record in records})
    if position != len(data):
        raise ValueError("Unexpected data after the bitmap font maps")
    return data[:header_end], maps


def write_font_table(header, maps):
    data = bytearray(header)
    for mapping in maps:
        data.extend(struct.pack("<I", len(mapping)))
        for codepoint in sorted(mapping):
            data.extend(FONT_RECORD.pack(*mapping[codepoint]))
    return bytes(data)


def is_hangul(codepoint):
    return (0xAC00 <= codepoint <= 0xD7A3
            or 0x1100 <= codepoint <= 0x11FF
            or 0x3131 <= codepoint <= 0x318E)


def used_hangul(mods, files):
    chars = set()
    for filename in ("bin/card_name_e.bin", "bin/card_desc_e.bin"):
        chars.update(files[filename].read().decode("utf-16-le"))
    config = json.loads((mods / "modlist.json").read_bytes())
    for entry in config["mods"]:
        cards = mods / entry["id"] / "Yu-Gi-Oh-Ex/cards.json"
        if entry["enabled"] and cards.is_file():
            for card in json.loads(cards.read_bytes())["cards"]:
                chars.update(card["name"])
                chars.update(card["description"])
    return {ord(char) for char in chars if is_hangul(ord(char))}


@cache
def face_at_size(path, size):
    return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)


def verify_font_coverage(font_path, codepoints):
    face = face_at_size(font_path, 32)
    missing_glyph = face.getmask("\uffff", mode="L")
    missing_signature = missing_glyph.size, bytes(missing_glyph)
    for codepoint in codepoints:
        glyph = face.getmask(chr(codepoint), mode="L")
        if (glyph.size, bytes(glyph)) == missing_signature or glyph.getbbox() is None:
            raise ValueError(f"{font_path.name} has no visible glyph for U+{codepoint:04X}")


def render_glyph(glyph, font_path, width, height):
    font = face_at_size(font_path, round(glyph.advance))
    bitmap, offset = font.getmask2(chr(glyph.codepoint), mode="L", anchor="ms")
    mask = Image.frombytes("L", bitmap.size, bytes(bitmap))
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError(f"Empty rendered glyph U+{glyph.codepoint:04X}")
    ink = mask.crop(bounds)
    if ink.width > width or ink.height > height:
        ink = ImageOps.contain(ink, (width, height), Image.Resampling.LANCZOS)
    x = width // 2 + offset[0] + bounds[0]
    y = round(-glyph.top) + offset[1] + bounds[1]
    canvas = Image.new("L", (width, height))
    canvas.paste(ink, (max(0, min(x, width - ink.width)), max(0, min(y, height - ink.height))))
    return canvas


def build_atlas(table, png, required, font_path):
    header, maps = read_font_table(table)
    main, second = maps
    korean = {code: glyph for code, glyph in main.items() if is_hangul(code)}
    if not korean or any(second.get(code) != glyph for code, glyph in korean.items()):
        raise ValueError("The font maps disagree on Korean glyphs")
    missing = sorted(required - korean.keys())

    with Image.open(BytesIO(png)) as image:
        palette = image.getpalette()
        colors = image.getcolors(256)
        if image.mode != "P" or not colors or any(
            palette[index * 3:index * 3 + 3] != [255, 255, 255] for _, index in colors
        ):
            raise ValueError("Expected a white, alpha-indexed font texture")
        original = image.convert("RGBA").getchannel("A")

    width, height = original.size
    template = korean[0xAC00]
    cell_width, cell_height = template.pixel_width, template.pixel_height
    step_x, step_y = cell_width + 2, cell_height + 2
    columns = width // step_x
    added_rows = (len(missing) + columns - 1) // columns
    new_height = height + added_rows * step_y
    atlas = Image.new("L", (width, new_height))
    atlas.paste(original, (0, 0))

    for code, glyph in korean.items():
        left, top, right, bottom = glyph.box(width, height)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError(f"Invalid bitmap bounds for U+{code:04X}")
        atlas.paste(render_glyph(glyph, font_path, right - left, bottom - top), (left, top))

    for mapping in maps:
        for code, glyph in mapping.items():
            # Keep the source pixels addressed by the primary texture coordinates.
            mapping[code] = glyph._replace(v0=glyph.v0 * height / new_height,
                                           v1=glyph.v1 * height / new_height)

    for index, code in enumerate(missing):
        row, column = divmod(index, columns)
        left, top = column * step_x + 1, height + row * step_y + 1
        glyph = template._replace(
            codepoint=code, mapped_codepoint=code,
            u0=left / width, u1=(left + cell_width) / width,
            v0=top / new_height, v1=(top + cell_height) / new_height,
        )
        for mapping in maps:
            mapping[code] = glyph
        atlas.paste(render_glyph(glyph, font_path, cell_width, cell_height), (left, top))

    # The source PNG also uses indexed white pixels with an alpha table.
    indexed = Image.frombytes("P", atlas.size, atlas.tobytes())
    indexed.putpalette([255] * (256 * 3))
    image_bytes = BytesIO()
    indexed.save(image_bytes, format="PNG", transparency=bytes(range(256)))
    return write_font_table(header, maps), image_bytes.getvalue(), len(korean), len(missing)


def verify_atlas(source_table, source_png, table, png, required):
    header, old_maps = read_font_table(source_table)
    new_header, new_maps = read_font_table(table)
    if header != new_header:
        raise ValueError("Font header changed")
    with Image.open(BytesIO(source_png)) as image:
        old = image.convert("RGBA").getchannel("A")
    with Image.open(BytesIO(png)) as image:
        new = image.convert("RGBA").getchannel("A")
    for before, after in zip(old_maps, new_maps):
        if not required <= after.keys() or not before.keys() <= after.keys():
            raise ValueError("Missing glyphs after rebuilding font")
        for code, glyph in before.items():
            updated = after[code]
            if glyph[:10] != updated[:10] or glyph[14:] != updated[14:]:
                raise ValueError(f"Existing glyph metrics changed for U+{code:04X}")
            if glyph.box(*old.size) != updated.box(*new.size):
                raise ValueError(f"Existing glyph moved for U+{code:04X}")
        for code in required:
            if new.crop(after[code].box(*new.size)).getbbox() is None:
                raise ValueError(f"Blank Korean bitmap for U+{code:04X}")

    changed = ImageChops.difference(old, new.crop((0, 0, *old.size)))
    non_korean = Image.new("L", old.size)
    draw = ImageDraw.Draw(non_korean)
    for code, glyph in old_maps[0].items():
        if not is_hangul(code):
            left, top, right, bottom = glyph.box(*old.size)
            if right > left and bottom > top:
                draw.rectangle((left, top, right - 1, bottom - 1), fill=255)
    if not changed.getbbox() or ImageChops.multiply(changed, non_korean).getbbox():
        raise ValueError("Unexpected changes to the original atlas pixels")


def build(project, font_directory):
    mods = (project / "Mods").resolve(strict=True)
    target = mods / FONT_MOD
    if target.exists():
        raise FileExistsError(target)
    source_archive = mods / CARD_PACK / f"{ARCHIVE_NAME}.dat"
    files = index_dat(source_archive)
    source_toc = source_archive.with_suffix(".toc").read_bytes()
    archive_paths = {}
    for row in source_toc.decode("utf-8-sig").splitlines()[1:]:
        if row.strip():
            path = row.split(maxsplit=2)[2]
            archive_paths[path.replace("\\", "/").casefold()] = path
    required = used_hangul(mods, files)
    names = sorted(name for name in files if name.startswith("fontbin/") and name.endswith(".fbin"))
    medium = font_directory / "Pretendard-Medium.ttf"
    semibold = font_directory / "Pretendard-SemiBold.ttf"
    for font in (medium, semibold):
        verify_font_coverage(font, required)

    with TemporaryDirectory(dir=mods, prefix=".korean-font-") as directory:
        stage = Path(directory).resolve(strict=True)
        if stage.parent != mods:
            raise ValueError("The font staging directory is outside Mods")
        prepared = stage / FONT_MOD
        prepared.mkdir()
        archive = prepared / f"{ARCHIVE_NAME}.dat"
        newline = "\r\n" if b"\r\n" in source_toc else "\n"
        with archive.open("wb") as dat, archive.with_suffix(".toc").open(
            "w", encoding="ascii", newline=newline
        ) as toc:
            toc.write("UT\n")
            for table_name in names:
                image_name = table_name.removesuffix(".fbin") + ".png"
                table, png = files[table_name].read(), files[image_name].read()
                family = table_name.removesuffix(".fbin").rsplit("_id_", 1)[-1]
                weight = semibold if family in TITLE_FONTS else medium
                new_table, new_png, replaced, added = build_atlas(table, png, required, weight)
                verify_atlas(table, png, new_table, new_png, required)
                for name, data in ((table_name, new_table), (image_name, new_png)):
                    path = archive_paths[name]
                    toc.write(f"{len(data):12x} {len(path):x} {path}\n")
                    dat.write(data)
                    dat.write(bytes(align(len(data), 4) - len(data)))
                print(f"{family}: {replaced} replaced, {added} added", flush=True)
        if len(index_dat(archive)) != 2 * len(names):
            raise ValueError("The prepared font archive is incomplete")
        copyfile(font_directory / "LICENSE", prepared / "OFL-Pretendard.txt")
        metadata = {
            "name": "한국어 글꼴 - 프리텐다드",
            "version": "1.0",
            "author": "Pretendard by Kil Hyung-jin",
            "website": PRETENDARD_RELEASE,
            "description": "카드 효과문과 카드명을 프리텐다드로 표시합니다.",
            "details": "효과문은 Medium, 카드명은 SemiBold를 사용합니다.",
        }
        (prepared / "mod.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        prepared.rename(target)

    print(json.dumps({"font_atlases": len(names), "required_hangul": len(required), "mod": FONT_MOD}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--font-directory", type=Path, default=Path(os.environ["LOCALAPPDATA"]) /
                        "YGO-PC-Full/FontCatalog/Pretendard-1.3.9")
    args = parser.parse_args()
    build(args.project, args.font_directory)


if __name__ == "__main__":
    main()
