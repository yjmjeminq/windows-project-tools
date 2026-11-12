#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <detours.h>

#include <cstdint>
#include <cstring>

#pragma comment(linker, "/export:DetourFinishHelperProcess,@1,NONAME")

namespace
{
    // The shipped 2020 Link Evolution executable and the custom Core in this package.
    constexpr DWORD kGameTimestamp = 0x5e5eabc6;
    constexpr DWORD kGameImageSize = 0x35a3000;
    constexpr DWORD kCoreTimestamp = 0x6af4789b;
    constexpr DWORD kCoreImageSize = 0x10f000;

    constexpr std::uintptr_t kGameUiFlagsRva = 0x278ef38;
    constexpr std::uintptr_t kCoreBusyCallbackRva = 0x555d0;
    constexpr std::uint32_t kCardListOpen = 0x10000;
    constexpr std::uint32_t kDialogAnimation = 55;

    using BusyCallback = std::int64_t(__fastcall*)(std::uint32_t);
    BusyCallback OriginalBusy = nullptr;
    const std::uint32_t* DuelUiFlags = nullptr;

    bool MatchesImage(HMODULE module, DWORD timestamp, DWORD size)
    {
        if (!module)
            return false;

        const auto* base = reinterpret_cast<const std::uint8_t*>(module);
        const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
        if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0)
            return false;

        const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
        return nt->Signature == IMAGE_NT_SIGNATURE
            && nt->FileHeader.Machine == IMAGE_FILE_MACHINE_AMD64
            && nt->FileHeader.TimeDateStamp == timestamp
            && nt->OptionalHeader.SizeOfImage == size;
    }

    std::int64_t __fastcall IsBusy(std::uint32_t animation)
    {
        // Master Duel waits on animation 55 for both prompts and card lists.
        // Link Evolution's list widget sets its own flag until the UI submits its
        // index, selection order and result, including when the user cancels.
        if (animation == kDialogAnimation && (*DuelUiFlags & kCardListOpen) != 0)
            return 1;

        return OriginalBusy(animation);
    }

    bool Install(HMODULE game, HMODULE core)
    {
        if (!MatchesImage(game, kGameTimestamp, kGameImageSize)
            || !MatchesImage(core, kCoreTimestamp, kCoreImageSize))
            return false;

        const auto* gameBase = reinterpret_cast<const std::uint8_t*>(game);
        const auto* coreBase = reinterpret_cast<const std::uint8_t*>(core);
        constexpr std::uint8_t busyPrologue[] = {
            0x80, 0x3d, 0x8b, 0x7e, 0x0a, 0x00, 0x00, 0x74, 0x06
        };
        const auto* callback = coreBase + kCoreBusyCallbackRva;
        if (std::memcmp(callback, busyPrologue, sizeof busyPrologue) != 0)
            return false;

        DuelUiFlags = reinterpret_cast<const std::uint32_t*>(gameBase + kGameUiFlagsRva);
        OriginalBusy = reinterpret_cast<BusyCallback>(callback);
        if (DetourTransactionBegin() != NO_ERROR)
            return false;

        if (DetourUpdateThread(GetCurrentThread()) != NO_ERROR
            || DetourAttach(reinterpret_cast<PVOID*>(&OriginalBusy), reinterpret_cast<PVOID>(&IsBusy)) != NO_ERROR)
        {
            DetourTransactionAbort();
            return false;
        }
        return DetourTransactionCommit() == NO_ERROR;
    }
}

#ifdef YGO_FIX_TEST
extern "C" __declspec(dllexport) BOOL InstallForTest(HMODULE game, HMODULE core)
{
    return Install(game, core);
}
#endif

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH && !DetourIsHelperProcess())
    {
        DetourRestoreAfterWith();
#ifndef YGO_FIX_TEST
        const HMODULE game = GetModuleHandleW(nullptr);
        const HMODULE core = GetModuleHandleW(L"Yu-Gi-Oh-Core.dll");
        if (Install(game, core))
            OutputDebugStringA("Yu-Gi-Oh-OfflineDuelFix: card list wait installed.\n");
        else
            OutputDebugStringA("Yu-Gi-Oh-OfflineDuelFix: supported game or Core build not found.\n");
#endif
    }
    return TRUE;
}
