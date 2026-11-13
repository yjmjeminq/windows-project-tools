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
    constexpr std::uintptr_t kCoreAnimationCallbackRva = 0x55040;
    constexpr std::uintptr_t kCoreBusyCallbackRva = 0x555d0;
    constexpr std::uintptr_t kCoreDuelStatePtrRva = 0xfd480;
    constexpr std::uintptr_t kGetOptionTextRva = 0x77ae30;
    constexpr std::uintptr_t kWStringAssignRva = 0x751310;
    constexpr std::uintptr_t kGetCardDescRva = 0x819fb0;
    constexpr std::uintptr_t kOptionBufferRva = 0x349b460;

    constexpr std::uint32_t kCardListOpen = 0x10000;
    constexpr std::uint32_t kDialogAnimation = 55;
    constexpr std::uint32_t kCardListAnimation = 56;
    constexpr std::int64_t kCardActivateAnimation = 35;
    constexpr std::uint32_t kCardIdMask = 0xffff;
    constexpr int kMaxDuelDisplayId = 0x3fff;
    constexpr std::uint32_t kCustomOptionTagBase = 0xE000;

    struct GameWString
    {
        union {
            wchar_t buf[8];
            wchar_t* ptr;
        };
        size_t size;
        size_t capacity;
    };

    struct OptionChoiceInfo
    {
        uint32_t card_id;
        uint32_t effect_idx;
        bool is_card_effect;
    };

    using BusyCallback = std::int64_t(__fastcall*)(std::uint32_t);
    using AnimationCallback = std::int64_t(__fastcall*)(std::int64_t, std::int64_t, std::uint32_t, std::int64_t);
    using DisplayIdLookup = int(__cdecl*)(int);
    using GetOptionTextFn = GameWString*(__fastcall*)(GameWString*, uint32_t);
    using WStringAssignFn = GameWString*(__fastcall*)(GameWString*, const wchar_t*, size_t);
    using GetCardDescFn = const wchar_t*(__fastcall*)(uint32_t);

    using DuelSetPlayerTypeFn = void(__cdecl*)(int, int);
    using DuelDlgCanYesNoSkipFn = int(__cdecl*)();
    using DuelDlgSetResultFn = void(__cdecl*)(int);
    using DuelListSetIndexFn = void(__cdecl*)(int);

    BusyCallback OriginalBusy = nullptr;
    AnimationCallback OriginalAnimation = nullptr;
    DisplayIdLookup ToDisplayId = nullptr;
    GetOptionTextFn OriginalGetOptionText = nullptr;
    WStringAssignFn GameWStringAssign = nullptr;
    GetCardDescFn GameGetCardDescription = nullptr;

    const std::uint32_t* DuelUiFlags = nullptr;
    const std::uint8_t* const* DuelStatePtr = nullptr;
    uint32_t* OptionBuffer = nullptr;

    DuelSetPlayerTypeFn fnDuelSetPlayerType = nullptr;
    DuelDlgCanYesNoSkipFn fnDuelDlgCanYesNoSkip = nullptr;
    DuelDlgSetResultFn fnDuelDlgSetResult = nullptr;
    DuelListSetIndexFn fnDuelListSetIndex = nullptr;

    OptionChoiceInfo g_OptionChoices[16] = {};
    int g_OptionChoiceCount = 0;

    void EnsureDuelExports()
    {
        if (fnDuelSetPlayerType)
            return;

        const HMODULE duel = GetModuleHandleW(L"duel.dll");
        if (!duel)
            return;

        fnDuelSetPlayerType = reinterpret_cast<DuelSetPlayerTypeFn>(GetProcAddress(duel, "DLL_DuelSetPlayerType"));
        fnDuelDlgCanYesNoSkip = reinterpret_cast<DuelDlgCanYesNoSkipFn>(GetProcAddress(duel, "DLL_DuelDlgCanYesNoSkip"));
        fnDuelDlgSetResult = reinterpret_cast<DuelDlgSetResultFn>(GetProcAddress(duel, "DLL_DuelDlgSetResult"));
        fnDuelListSetIndex = reinterpret_cast<DuelListSetIndexFn>(GetProcAddress(duel, "DLL_DuelListSetIndex"));
    }

    inline int GetAskedPlayer()
    {
        if (!DuelStatePtr || !*DuelStatePtr)
            return 0;
        return *reinterpret_cast<const int*>(*DuelStatePtr + 0x3d00);
    }

    inline int GetDialogType()
    {
        if (!DuelStatePtr || !*DuelStatePtr)
            return 0;
        return *reinterpret_cast<const int*>(*DuelStatePtr + 0x3c94);
    }

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

    GameWString* __fastcall CustomGetOptionText(GameWString* out_str, uint32_t text_id)
    {
        int opt_idx = -1;
        if (text_id >= kCustomOptionTagBase && text_id < kCustomOptionTagBase + 16)
        {
            opt_idx = static_cast<int>(text_id - kCustomOptionTagBase);
        }

        if (opt_idx >= 0 && opt_idx < g_OptionChoiceCount && g_OptionChoices[opt_idx].is_card_effect)
        {
            const uint32_t card_id = g_OptionChoices[opt_idx].card_id;
            const uint32_t effect_idx = g_OptionChoices[opt_idx].effect_idx;

            if (GameGetCardDescription && GameWStringAssign)
            {
                const wchar_t* desc = GameGetCardDescription(card_id);
                if (desc && desc[0] != L'\0')
                {
                    uint32_t total_bullets = 0;
                    for (const wchar_t* s = desc; *s; s++)
                    {
                        if (*s == L'\x25cf')
                            total_bullets++;
                    }

                    uint32_t target_bullet = effect_idx;
                    if (total_bullets > 0 && target_bullet >= total_bullets)
                    {
                        if (static_cast<uint32_t>(opt_idx) < total_bullets)
                            target_bullet = static_cast<uint32_t>(opt_idx);
                        else
                            target_bullet = 0;
                    }

                    const wchar_t* bullet_start = nullptr;
                    const wchar_t* bullet_end = nullptr;

                    if (total_bullets > 0)
                    {
                        const wchar_t* p = desc;
                        uint32_t cur = 0;
                        while (*p)
                        {
                            if (*p == L'\x25cf')
                            {
                                p++;
                                while (*p == L' ' || *p == L'\t')
                                    p++;
                                if (cur == target_bullet)
                                {
                                    bullet_start = p;
                                    while (*p && *p != L'\r' && *p != L'\n' && *p != L'\x25cf')
                                        p++;
                                    bullet_end = p;
                                    break;
                                }
                                cur++;
                            }
                            else
                            {
                                p++;
                            }
                        }
                    }
                    else
                    {
                        uint32_t target_circle_idx = (effect_idx < 20) ? effect_idx : static_cast<uint32_t>(opt_idx);
                        wchar_t circle = static_cast<wchar_t>(0x2460 + target_circle_idx);
                        const wchar_t* p = desc;
                        while (*p)
                        {
                            if (*p == circle)
                            {
                                p++;
                                if (*p == L':' || *p == L'：')
                                    p++;
                                while (*p == L' ' || *p == L'\t')
                                    p++;
                                bullet_start = p;
                                while (*p && *p != L'\r' && *p != L'\n' && !(*p >= 0x2460 && *p <= 0x2473))
                                    p++;
                                bullet_end = p;
                                break;
                            }
                            p++;
                        }
                    }

                    if (bullet_start && bullet_end && bullet_end > bullet_start)
                    {
                        while (bullet_end > bullet_start &&
                               (bullet_end[-1] == L' ' || bullet_end[-1] == L'\t' ||
                                bullet_end[-1] == L'\r' || bullet_end[-1] == L'\n'))
                        {
                            bullet_end--;
                        }
                        const size_t len = static_cast<size_t>(bullet_end - bullet_start);
                        if (len > 0)
                        {
                            out_str->capacity = 7;
                            out_str->size = 0;
                            out_str->buf[0] = 0;
                            GameWStringAssign(out_str, bullet_start, len);
                            return out_str;
                        }
                    }
                }
            }

            // Fallback for custom tag if extraction somehow found nothing:
            return OriginalGetOptionText(out_str, 0x1ac);
        }

        return OriginalGetOptionText(out_str, text_id);
    }

    std::int64_t __fastcall IsBusy(std::uint32_t animation)
    {
        EnsureDuelExports();
        if (fnDuelSetPlayerType)
        {
            fnDuelSetPlayerType(0, 0);
            fnDuelSetPlayerType(1, 1);
        }

        if (animation == kDialogAnimation && (*DuelUiFlags & kCardListOpen) != 0)
            return 1;

        return OriginalBusy(animation);
    }

    std::int64_t __fastcall ShowAnimation(
        std::int64_t animation, std::int64_t position, std::uint32_t detail, std::int64_t instance)
    {
        EnsureDuelExports();
        if (fnDuelSetPlayerType)
        {
            fnDuelSetPlayerType(0, 0);
            fnDuelSetPlayerType(1, 1);
        }

        const int askedPlayer = GetAskedPlayer();
        const int dialogType = GetDialogType();

        // 1. If asked player is CPU (player 1) or position is 1, do NOT prompt player 0
        if (askedPlayer == 1 || position == 1)
        {
            if (animation == kCardListAnimation)
            {
                if (fnDuelListSetIndex)
                    fnDuelListSetIndex(0);
                return 0;
            }
            if (animation == kDialogAnimation)
            {
                if (fnDuelDlgSetResult)
                    fnDuelDlgSetResult(0);
                return 0;
            }
        }

        // 2. Mandatory effect auto-confirmation for human player:
        // When duel.dll asks whether to activate an effect (instance == 3 or dialogType == 3),
        // check DLL_DuelDlgCanYesNoSkip(). If it returns 0 (mandatory / cannot skip),
        // automatically confirm with DLL_DuelDlgSetResult(0) and suppress the popup.
        if (animation == kDialogAnimation && (instance == 3 || dialogType == 3))
        {
            if (fnDuelDlgCanYesNoSkip && fnDuelDlgCanYesNoSkip() == 0)
            {
                if (fnDuelDlgSetResult)
                    fnDuelDlgSetResult(0);
                return 0;
            }
        }

        // 3. CardActivate sends an engine card ID in the low word of detail.
        // The artwork loader needs the display ID assigned to that card for this duel.
        if (animation == kCardActivateAnimation && (detail & kCardIdMask) != 0)
        {
            const int displayId = ToDisplayId(static_cast<int>(detail & kCardIdMask));
            if (displayId > 0 && displayId <= kMaxDuelDisplayId)
                detail = (detail & ~kCardIdMask) | static_cast<std::uint32_t>(displayId);
        }

        // 4. Run original animation logic
        std::int64_t result = OriginalAnimation(animation, position, detail, instance);

        // 5. Modal card effect option text resolution fix:
        // When duel.dll sets up options (animation == 55), Core writes option entries
        // into YuGiOh.exe's option buffer (0x14349b460).
        // Because YuGiOh.exe only reads 16-bit text IDs and truncates card IDs to 14 bits,
        // modal choices and modded card IDs (>16383) lose their effect sub-index.
        // We tag each valid card-effect option with (kCustomOptionTagBase + validIdx)
        // so our CustomGetOptionText hook can resolve the distinct bullet text.
        if (animation == kDialogAnimation && DuelStatePtr && *DuelStatePtr)
        {
            const int rawCount = *reinterpret_cast<const int*>(*DuelStatePtr + 0x3cb4);
            if (rawCount > 0 && rawCount <= 16)
            {
                int validIdx = 0;
                for (int i = 0; i < rawCount && validIdx < 6; i++)
                {
                    const uint32_t raw_opt = *reinterpret_cast<const uint32_t*>(*DuelStatePtr + 0x3cb8 + i * 4);
                    if ((raw_opt & 0x80000000) != 0)
                    {
                        const uint32_t engine_card_id = raw_opt & 0xffff;
                        const uint32_t effect_idx = (raw_opt >> 16) & 0xfff;
                        uint32_t display_id = engine_card_id;
                        if (ToDisplayId)
                        {
                            const int mapped = ToDisplayId(static_cast<int>(engine_card_id));
                            if (mapped > 0)
                                display_id = static_cast<uint32_t>(mapped);
                        }
                        g_OptionChoices[validIdx].card_id = display_id;
                        g_OptionChoices[validIdx].effect_idx = effect_idx;
                        g_OptionChoices[validIdx].is_card_effect = true;

                        if (OptionBuffer)
                        {
                            OptionBuffer[1 + validIdx] = 0x10000 | (kCustomOptionTagBase + validIdx);
                        }
                        validIdx++;
                    }
                }
                g_OptionChoiceCount = validIdx;
            }
        }

        return result;
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
        constexpr std::uint8_t animationPrologue[] = {
            0x40, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57
        };
        const auto* busy = coreBase + kCoreBusyCallbackRva;
        const auto* animation = coreBase + kCoreAnimationCallbackRva;
        if (std::memcmp(busy, busyPrologue, sizeof busyPrologue) != 0
            || std::memcmp(animation, animationPrologue, sizeof animationPrologue) != 0)
            return false;

        const auto displayIdLookup = GetProcAddress(core, "Core_EngineToDisplay");
        if (!displayIdLookup)
            return false;

        DuelUiFlags = reinterpret_cast<const std::uint32_t*>(gameBase + kGameUiFlagsRva);
        DuelStatePtr = reinterpret_cast<const std::uint8_t* const*>(coreBase + kCoreDuelStatePtrRva);
        OptionBuffer = reinterpret_cast<uint32_t*>(const_cast<std::uint8_t*>(gameBase) + kOptionBufferRva);

        OriginalBusy = reinterpret_cast<BusyCallback>(busy);
        OriginalAnimation = reinterpret_cast<AnimationCallback>(animation);
        OriginalGetOptionText = reinterpret_cast<GetOptionTextFn>(const_cast<std::uint8_t*>(gameBase) + kGetOptionTextRva);
        GameWStringAssign = reinterpret_cast<WStringAssignFn>(const_cast<std::uint8_t*>(gameBase) + kWStringAssignRva);
        GameGetCardDescription = reinterpret_cast<GetCardDescFn>(const_cast<std::uint8_t*>(gameBase) + kGetCardDescRva);

        ToDisplayId = reinterpret_cast<DisplayIdLookup>(reinterpret_cast<void*>(displayIdLookup));

        if (DetourTransactionBegin() != NO_ERROR)
            return false;

        if (DetourUpdateThread(GetCurrentThread()) != NO_ERROR
            || DetourAttach(reinterpret_cast<PVOID*>(&OriginalBusy), reinterpret_cast<PVOID>(&IsBusy)) != NO_ERROR
            || DetourAttach(reinterpret_cast<PVOID*>(&OriginalAnimation), reinterpret_cast<PVOID>(&ShowAnimation)) != NO_ERROR
            || DetourAttach(reinterpret_cast<PVOID*>(&OriginalGetOptionText), reinterpret_cast<PVOID>(&CustomGetOptionText)) != NO_ERROR)
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
            OutputDebugStringA("Yu-Gi-Oh-OfflineDuelFix: card list, CPU turn, mandatory effect, and modal option text fixes installed.\n");
        else
            OutputDebugStringA("Yu-Gi-Oh-OfflineDuelFix: supported game or Core build not found.\n");
#endif
    }
    return TRUE;
}
