"""Check which card image the Link Evolution activation popup requests without starting the game."""

import argparse
import ctypes as c
from hashlib import sha256
from pathlib import Path
import struct

import pefile

from test_pc_duel_effects import CASES, OfflineDuel, PORT_DIRECTORY
from test_pc_recent_card_families import CASES as RECENT_CASES


GAME_BASE = 0x140000000
GAME_HASH = "ae3b151cf14aa01f8d44ecb3ad95e1ab84862d20ab7fab282a1b17454eda551d"
CORE_HASH = "22f3cdb4e42caaf2d04a87b0e50732bd29b060faed2099740b99318d284d6b74"
CORE_CALLBACK = 0x55040
CORE_MIRROR = 0x54C20
CORE_DISPLAY_IDS = 0xFD1F8
CORE_ENGINE_IDS = 0xFD1E0
CORE_LOG_LEVEL = 0xFD488
CARD_ACTIVATE = 35
ANIMATION = c.WINFUNCTYPE(c.c_int64, c.c_int64, c.c_int64, c.c_uint32, c.c_int64)


def bind(dll, name, result_type, *arg_types):
    function = getattr(dll, name)
    function.restype = result_type
    function.argtypes = arg_types
    return function


class ActivationPopup:
    def __init__(self, project):
        game_path = project / "YuGiOh.exe"
        core_path = project / "WolfX-1.6.1/Plugins/Yu-Gi-Oh-Core.dll"
        for path, expected in ((game_path, GAME_HASH), (core_path, CORE_HASH)):
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Unsupported fixture binary: {path}")

        kernel = c.WinDLL("kernel32", use_last_error=True)
        allocate = bind(kernel, "VirtualAlloc", c.c_void_p, c.c_void_p, c.c_size_t, c.c_ulong, c.c_ulong)
        map_module = bind(kernel, "LoadLibraryExW", c.c_void_p, c.c_wchar_p, c.c_void_p, c.c_ulong)
        self.protect = bind(kernel, "VirtualProtect", c.c_int, c.c_void_p, c.c_size_t,
                            c.c_ulong, c.POINTER(c.c_ulong))
        self.flush = bind(kernel, "FlushInstructionCache", c.c_int, c.c_void_p, c.c_void_p, c.c_size_t)

        game = pefile.PE(str(game_path), fast_load=True)
        size = game.OPTIONAL_HEADER.SizeOfImage
        image = game.get_memory_mapped_image(max_virtual_address=size)
        self.game = allocate(GAME_BASE, size, 0x3000, 0x40)
        assert self.game == GAME_BASE
        c.memmove(self.game, image, len(image))

        self.core = map_module(str(core_path), None, 1)  # DONT_RESOLVE_DLL_REFERENCES
        assert self.core, c.WinError(c.get_last_error())
        core = c.WinDLL(str(core_path), handle=self.core)
        self.set_display_id = bind(core, "Core_EngineSetDisplayId", None, c.c_int, c.c_int)
        self.display_ids = (c.c_uint16 * 65536)()
        self.engine_ids = (c.c_uint16 * 65536)()
        c.c_void_p.from_address(self.core + CORE_DISPLAY_IDS).value = c.addressof(self.display_ids)
        c.c_void_p.from_address(self.core + CORE_ENGINE_IDS).value = c.addressof(self.engine_ids)
        c.c_int.from_address(self.core + CORE_LOG_LEVEL).value = 0
        self.replace(self.core + CORE_MIRROR, b"\xc3")
        self.animate = ANIMATION(self.core + CORE_CALLBACK)
        self.draw = c.WINFUNCTYPE(None, c.c_void_p)(self.game + 0x791D20)

        # Keep the native CardActivate dispatcher and popup draw method. Stub
        # only the allocator, UI plumbing, and graphics calls in this process.
        self.objects = []
        self.requests = []
        self.draws = []
        self.callbacks = [
            c.WINFUNCTYPE(c.c_void_p, c.c_size_t)(self.allocate_popup),
            c.WINFUNCTYPE(None, c.c_uint32)(self.requests.append),
            c.WINFUNCTYPE(None, c.c_uint32)(self.draws.append),
        ]
        for rva, callback in zip((0x90D2B8, 0x752500, 0x873FA0), self.callbacks):
            address = c.cast(callback, c.c_void_p).value
            self.replace(self.game + rva, b"\x48\xb8" + struct.pack("<Q", address) + b"\xff\xe0")
        for rva in (0x7694F0, 0x7EB320, 0x78B8F0, 0x7748F0, 0x76FB50,
                    0x76FB80, 0x7A7980, 0x8758C0, 0x875A30, 0x8751E0):
            self.replace(self.game + rva, b"\x31\xc0\xc3")

    def replace(self, address, code):
        original = c.c_ulong()
        assert self.protect(address, len(code), 0x40, c.byref(original))
        c.memmove(address, code, len(code))
        assert self.protect(address, len(code), original.value, c.byref(c.c_ulong()))
        assert self.flush(c.c_void_p(-1), address, len(code))

    def allocate_popup(self, size):
        self.objects.append(c.create_string_buffer(size))
        return c.addressof(self.objects[-1])

    def requested_card(self, event):
        self.objects.clear()
        self.requests.clear()
        self.draws.clear()
        assert self.animate(*event) == 1 and len(self.objects) == 1
        popup = c.addressof(self.objects[0])
        c.c_float.from_address(popup + 0x80).value = 1
        self.draw(popup)
        assert len(self.requests) == 1 and self.requests == self.draws
        return self.requests[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PORT_DIRECTORY.parent)
    parser.add_argument("--test-plugin", required=True, type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    engine = OfflineDuel(project)
    cases = {
        "reinforcement": [5328],
        "ash_negation": [23497, 12950],
        "dark_summon": [23500],
        "destiny_hero_effect": [23345],
        "synchro_effect": [23501],
        "xyz_effect": [23502],
    }
    recent = {
        "ashtra_search_and_trap": [23379, 23395],
        "ars_magna_search": [23383],
        "blitzclique_trap_and_trigger": [23000, 22960],
        "call_of_the_haunted_support": [22346, 4989],
        "phantasm_fusion_from_graveyard": [23015],
        "medius_special_summon_and_search": [23339, 21812],
    }
    activations = {}
    scenarios = CASES | RECENT_CASES
    for case, card_ids in (cases | recent).items():
        engine.events.clear()
        scenarios[case](engine)
        for cid in card_ids:
            activations[cid] = next(event[:4] for event in engine.events
                                    if event[0] == CARD_ACTIVATE and event[2] == cid)

    popup = ActivationPopup(project)
    # The popup receives short IDs allocated for the duel. Give the imported
    # cards distinct short IDs in this fixture.
    borrowed = {cid: slot for slot, cid in enumerate((cid for cid in activations if cid in engine.cards), 4038)}
    for engine_id, display_id in borrowed.items():
        popup.set_display_id(engine_id, display_id)
        row = engine.cards[engine_id]
        art = project / "Mods/2026-11-KR-Cards/Yu-Gi-Oh-Ex" / row["image"]
        assert row["id"] != engine_id and art.read_bytes().startswith(b"\xff\xd8\xff"), engine_id

    for cid, event in activations.items():
        assert popup.requested_card(event) == cid

    fix = c.WinDLL(str(args.test_plugin.resolve(strict=True)))
    install = bind(fix, "InstallForTest", c.c_int, c.c_void_p, c.c_void_p)
    assert not install(popup.game, None)
    assert install(popup.game, popup.core)
    for cid, event in activations.items():
        expected = borrowed.get(cid, cid)
        assert popup.requested_card(event) == expected
        print(f"Activation {cid}: texture request {cid} -> {expected}")
    replacement = max(borrowed.values()) + 1
    popup.set_display_id(23497, replacement)
    assert popup.requested_card(activations[23497]) == replacement


if __name__ == "__main__":
    main()
