#include "MsgFontSafe.hpp"

#include <cstdint>
#include <cstring>

namespace smoap::util {

namespace {

// UTF-8 decoder. On a well-formed codepoint, advances `pos` and returns the
// codepoint. On a malformed lead/continuation byte, advances `pos` by one
// (resync) and returns `kBadCp` so the caller emits '?'. End-of-input
// returns 0 (the NUL terminator).
constexpr char32_t kBadCp = 0xFFFFFFFFu;

char32_t decodeUtf8(const char* src, std::size_t len, std::size_t& pos) {
    if (pos >= len) return 0;
    const auto b0 = static_cast<unsigned char>(src[pos]);
    if (b0 == 0) return 0;
    if (b0 < 0x80) {
        ++pos;
        return b0;
    }
    char32_t cp;
    int extra;
    if ((b0 & 0xE0) == 0xC0) {
        cp = b0 & 0x1F;
        extra = 1;
    } else if ((b0 & 0xF0) == 0xE0) {
        cp = b0 & 0x0F;
        extra = 2;
    } else if ((b0 & 0xF8) == 0xF0) {
        cp = b0 & 0x07;
        extra = 3;
    } else {
        ++pos;
        return kBadCp;
    }
    if (pos + 1 + static_cast<std::size_t>(extra) > len) {
        ++pos;
        return kBadCp;
    }
    for (int i = 0; i < extra; ++i) {
        const auto b = static_cast<unsigned char>(src[pos + 1 + i]);
        if ((b & 0xC0) != 0x80) {
            ++pos;
            return kBadCp;
        }
        cp = (cp << 6) | (b & 0x3F);
    }
    pos += 1 + static_cast<std::size_t>(extra);
    return cp;
}

// ASCII chars [0x20..0x7E] WITHOUT a glyph in MessageFont38.bffnt. Verified by
// scripts/inspect_smo_font.py.
bool isMissingAscii(char32_t cp) {
    switch (cp) {
        case '#': case '$':
        case ';': case '<': case '=': case '>':
        case '[': case '\\': case ']':
        case '^': case '`':
        case '{': case '|': case '}': case '~':
            return true;
        default:
            return false;
    }
}

// The 9 non-ASCII codepoints MessageFont38 natively ships: © Å á è é í ó — …
// CJK / Hiragana / Katakana ARE also in the font, but we don't extend
// passthrough to them — English-locale slot names that incidentally contain
// CJK are vanishingly rare, and excluding them keeps unknown-Unicode output
// uniformly '?' instead of a confusing partial render.
bool isPassthroughNonAscii(char32_t cp) {
    switch (cp) {
        case 0x00A9:   // ©
        case 0x00C5:   // Å
        case 0x00E1:   // á
        case 0x00E8:   // è
        case 0x00E9:   // é
        case 0x00ED:   // í
        case 0x00F3:   // ó
        case 0x2014:   // — em dash
        case 0x2026:   // … horizontal ellipsis
            return true;
        default:
            return false;
    }
}

// Re-encode a passthrough non-ASCII codepoint into 2-3 UTF-8 bytes.
// Caller has already verified the codepoint is in the passthrough set, so
// only U+0080..U+FFFF needs handling (no 4-byte path).
int encodeUtf8Short(char32_t cp, char* out3) {
    if (cp < 0x800) {
        out3[0] = static_cast<char>(0xC0 | (cp >> 6));
        out3[1] = static_cast<char>(0x80 | (cp & 0x3F));
        return 2;
    }
    out3[0] = static_cast<char>(0xE0 | (cp >> 12));
    out3[1] = static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
    out3[2] = static_cast<char>(0x80 | (cp & 0x3F));
    return 3;
}

// Substitution table for codepoints we want to actively rewrite. Every
// `replacement` string is ASCII-only AND contains no character from the
// 15-char missing-ASCII set, so emitting it is unconditionally safe.
//
// Linear scan — table is small (<60 entries) and called once per input
// codepoint, well below the speech-bubble's frame budget.
struct CpSub {
    char32_t cp;
    const char* replacement;
};

constexpr CpSub kSubs[] = {
    // --- Missing ASCII -> visually similar supported ASCII --------------
    // # -> "No."     (typographic intent: "track #4" -> "track No.4")
    // $ -> "S"       (currency hint, single supported char)
    // ; -> ","       (sentence pause is close enough)
    // < > -> "(" ")" (angle brackets become parens)
    // = -> "-"       (closest single supported glyph)
    // [ ] -> "(" ")" (brackets become parens)
    // \ -> "/"       (path/slash conflation is intuitive)
    // ^ -> "'"       (caret has no good ASCII analog; apostrophe is least bad)
    // ` -> "'"       (backtick -> apostrophe)
    // { } -> "(" ")" (braces become parens)
    // | -> "/"       (pipe -> slash)
    // ~ -> "-"       (tilde -> hyphen)
    {U'#',  "No."},
    {U'$',  "S"},
    {U';',  ","},
    {U'<',  "("},
    {U'=',  "-"},
    {U'>',  ")"},
    {U'[',  "("},
    {U'\\', "/"},
    {U']',  ")"},
    {U'^',  "'"},
    {U'`',  "'"},
    {U'{',  "("},
    {U'|',  "/"},
    {U'}',  ")"},
    {U'~',  "-"},

    // --- Latin-1 punctuation (none of these have glyphs) ----------------
    {0x00A0, " "},        // NBSP -> space
    {0x00A1, "!"},        // ¡ -> !
    {0x00A2, "c"},        // ¢ -> c
    {0x00A3, "L"},        // £ -> L
    {0x00A5, "Y"},        // ¥ -> Y
    {0x00A7, "S"},        // § -> S
    {0x00AB, "\""},       // « -> "
    {0x00AC, "-"},        // ¬ -> -
    {0x00AD, ""},         // soft hyphen -> drop
    {0x00AE, "(R)"},      // ® -> (R)
    {0x00AF, "-"},        // ¯ -> -
    {0x00B0, " deg"},     // ° -> " deg"  (leading space avoids "85deg")
    {0x00B1, "+/-"},      // ± -> +/-
    {0x00B2, "2"},        // ² -> 2
    {0x00B3, "3"},        // ³ -> 3
    {0x00B4, "'"},        // ´ -> '
    {0x00B5, "u"},        // µ -> u
    {0x00B6, "P"},        // ¶ -> P
    {0x00B7, "."},        // · -> .
    {0x00B8, ""},         // ¸ -> drop (cedilla mark on its own)
    {0x00B9, "1"},        // ¹ -> 1
    {0x00BB, "\""},       // » -> "
    {0x00BC, "1/4"},      // ¼ -> 1/4
    {0x00BD, "1/2"},      // ½ -> 1/2
    {0x00BE, "3/4"},      // ¾ -> 3/4
    {0x00BF, "?"},        // ¿ -> ?
    {0x00D7, "x"},        // × -> x
    {0x00F7, "/"},        // ÷ -> /

    // --- Latin-1 accented letters (ASCII-fold; the 6 native-supported
    // ones — Å á è é í ó — are handled by isPassthroughNonAscii and
    // never reach this table) ---
    {0x00C0, "A"}, {0x00C1, "A"}, {0x00C2, "A"}, {0x00C3, "A"}, {0x00C4, "A"},
    {0x00C6, "AE"},
    {0x00C7, "C"},
    {0x00C8, "E"}, {0x00C9, "E"}, {0x00CA, "E"}, {0x00CB, "E"},
    {0x00CC, "I"}, {0x00CD, "I"}, {0x00CE, "I"}, {0x00CF, "I"},
    {0x00D0, "D"},
    {0x00D1, "N"},
    {0x00D2, "O"}, {0x00D3, "O"}, {0x00D4, "O"}, {0x00D5, "O"}, {0x00D6, "O"},
    {0x00D8, "O"},
    {0x00D9, "U"}, {0x00DA, "U"}, {0x00DB, "U"}, {0x00DC, "U"},
    {0x00DD, "Y"},
    {0x00DE, "Th"},
    {0x00DF, "ss"},
    {0x00E0, "a"}, {0x00E2, "a"}, {0x00E3, "a"}, {0x00E4, "a"}, {0x00E5, "a"},
    {0x00E6, "ae"},
    {0x00E7, "c"},
    {0x00EA, "e"}, {0x00EB, "e"},
    {0x00EC, "i"}, {0x00EE, "i"}, {0x00EF, "i"},
    {0x00F0, "d"},
    {0x00F1, "n"},
    {0x00F2, "o"}, {0x00F4, "o"}, {0x00F5, "o"}, {0x00F6, "o"},
    {0x00F8, "o"},
    {0x00F9, "u"}, {0x00FA, "u"}, {0x00FB, "u"}, {0x00FC, "u"},
    {0x00FD, "y"}, {0x00FE, "th"}, {0x00FF, "y"},

    // --- General Punctuation (U+2010..U+206F) — em-dash + ellipsis pass
    // through; everything else folds. Smart quotes are by far the most
    // common offender (autocorrect in Steam usernames). ---
    {0x2010, "-"}, {0x2011, "-"}, {0x2012, "-"}, {0x2013, "-"},
    {0x2015, "-"},
    {0x2018, "'"}, {0x2019, "'"}, {0x201A, ","}, {0x201B, "'"},
    {0x201C, "\""}, {0x201D, "\""}, {0x201E, "\""}, {0x201F, "\""},
    {0x2022, "*"},                                   // bullet
    {0x2032, "'"}, {0x2033, "\""}, {0x2034, "\"'"},  // primes
    {0x2039, "'"}, {0x203A, "'"},                    // single angle quotes

    // --- Trademark / service mark ---
    {0x2122, "(TM)"},
    {0x2120, "(SM)"},
};

// Lookup a substitution. Returns nullptr if `cp` isn't in the table.
const char* findSubstitution(char32_t cp) {
    for (const auto& sub : kSubs) {
        if (sub.cp == cp) return sub.replacement;
    }
    return nullptr;
}

// Append `n` bytes from `src` into `dst[*out..dst_cap)`, reserving 1 byte
// for the NUL terminator. Returns false if the write would overflow (caller
// stops emitting further codepoints; no partial write occurs).
bool appendBytes(char* dst, std::size_t dst_cap, std::size_t& out,
                 const char* src, std::size_t n) {
    if (out + n + 1 > dst_cap) return false;
    std::memcpy(dst + out, src, n);
    out += n;
    return true;
}

}  // namespace

std::size_t sanitizeForMsgFont(const char* src,
                               char* dst,
                               std::size_t dst_cap) {
    if (!dst || dst_cap == 0) return 0;
    dst[0] = '\0';
    if (!src) return 0;

    const std::size_t src_len = std::strlen(src);
    std::size_t in = 0;
    std::size_t out = 0;

    while (in < src_len) {
        const char32_t cp = decodeUtf8(src, src_len, in);
        if (cp == 0) break;

        // Native passthrough — ASCII present + the 9 supported non-ASCII
        // codepoints. We must emit them as their original UTF-8 byte
        // sequence to round-trip through utf8ToUtf16 cleanly.
        if (cp == ' ' || (cp >= 0x21 && cp <= 0x7E && !isMissingAscii(cp))) {
            const char b = static_cast<char>(cp);
            if (!appendBytes(dst, dst_cap, out, &b, 1)) break;
            continue;
        }
        if (isPassthroughNonAscii(cp)) {
            char tmp[3];
            const int n = encodeUtf8Short(cp, tmp);
            if (!appendBytes(dst, dst_cap, out, tmp, static_cast<std::size_t>(n))) {
                break;
            }
            continue;
        }

        // Active substitution.
        if (const char* rep = findSubstitution(cp)) {
            const std::size_t n = std::strlen(rep);
            if (!appendBytes(dst, dst_cap, out, rep, n)) break;
            continue;
        }

        // Unknown / control char / malformed UTF-8 -> '?' so the player
        // sees an unambiguous "something was here" marker rather than a
        // silent gap.
        const char q = '?';
        if (!appendBytes(dst, dst_cap, out, &q, 1)) break;
    }

    dst[out] = '\0';
    return out;
}

}  // namespace smoap::util
