"""Build the Atmosphère 2× game clock patch for Link Evolution 1.0.1."""

import argparse
import hashlib
from pathlib import Path
import struct
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


PORT_DIRECTORY = Path(__file__).resolve().parents[1]
BUILD_ID = bytes.fromhex("cdc49702ee3df923fb3773bf77f33102").ljust(32, b"\0")
NSO_HEADER_SIZE = 0x100
CLOCK_DELTA_OFFSET = 0xB52964
CLOCK_DELTA_ORIGINAL = bytes.fromhex("e80f00f9 e80f40f9")
# lsl x8, x8, #1; str x8, [sp, #0x18]. The original 100 ms cap follows.
CLOCK_DELTA_DOUBLE = bytes.fromhex("08f97fd3 e80f00f9")


def decompress_lz4(data, expected_size):
    cursor = 0
    output = bytearray()

    def read_length(length):
        nonlocal cursor
        if length == 15:
            while True:
                extension = data[cursor]
                cursor += 1
                length += extension
                if extension != 255:
                    break
        return length

    while cursor < len(data):
        token = data[cursor]
        cursor += 1
        length = read_length(token >> 4)
        end = cursor + length
        if end > len(data) or len(output) + length > expected_size:
            raise ValueError("Invalid LZ4 literal length in main NSO")
        output.extend(data[cursor:end])
        cursor = end
        if cursor == len(data):
            break

        distance = struct.unpack_from("<H", data, cursor)[0]
        cursor += 2
        length = read_length(token & 15) + 4
        if not 0 < distance <= len(output) or len(output) + length > expected_size:
            raise ValueError("Invalid LZ4 match in main NSO")
        start = len(output) - distance
        if length <= distance:
            output.extend(output[start:start + length])
        else:
            match = output[start:]
            repeats, remainder = divmod(length, distance)
            output.extend(match * repeats + match[:remainder])

    if len(output) != expected_size:
        raise ValueError("The decompressed NSO text length does not match its header")
    return bytes(output)


def read_main_text(path):
    nso = path.read_bytes()
    if len(nso) < NSO_HEADER_SIZE or nso[:4] != b"NSO0" or nso[0x40:0x60] != BUILD_ID:
        raise ValueError("Expected the main NSO from Link Evolution 1.0.1")

    flags, file_offset, address, size = struct.unpack_from("<IIII", nso, 0x0C)
    if address != 0 or not CLOCK_DELTA_OFFSET + len(CLOCK_DELTA_ORIGINAL) <= size <= 32 * 1024 * 1024:
        raise ValueError("Unexpected NSO text segment layout")
    if flags & 1:
        stored_size, = struct.unpack_from("<I", nso, 0x60)
        text = decompress_lz4(nso[file_offset:file_offset + stored_size], size)
    else:
        text = nso[file_offset:file_offset + size]
    if len(text) != size or hashlib.sha256(text).digest() != nso[0xA0:0xC0]:
        raise ValueError("The NSO text hash does not match its header")
    return text


def write_patch(main, output):
    text = read_main_text(main)
    end = CLOCK_DELTA_OFFSET + len(CLOCK_DELTA_ORIGINAL)
    if text[CLOCK_DELTA_OFFSET:end] != CLOCK_DELTA_ORIGINAL:
        raise ValueError("The original game clock instructions differ from the expected build")

    record = struct.pack(">IH", CLOCK_DELTA_OFFSET + NSO_HEADER_SIZE, len(CLOCK_DELTA_DOUBLE))
    patch = b"IPS32" + record + CLOCK_DELTA_DOUBLE + b"EEOF"
    module_id = BUILD_ID.rstrip(b"\0").hex().upper()
    patch_path = f"atmosphere/exefs_patches/LinkEvolution-2x/{module_id}.ips"

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as staging:
        archive_path = Path(staging.name)
    try:
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            archive.writestr(patch_path, patch)
        archive_path.replace(output)
    finally:
        archive_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=PORT_DIRECTORY / "1.0.1/ExeFS/main")
    parser.add_argument("--output", type=Path, default=PORT_DIRECTORY / "Link-Evolution-1.0.1-2x.zip")
    args = parser.parse_args()
    write_patch(args.main, args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
