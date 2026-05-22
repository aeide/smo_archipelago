// Host-compiler tests for smoap::util::sanitizeForMsgFont.
//
// Build (msys2 g++ — same toolchain as the other host tests; see
// .claude/skills/smo-host-tests/SKILL.md). Single-line so it doesn't trip
// -Wcomment:
//   "C:/msys64/mingw64/bin/g++.exe" -std=c++20 -Wall -Wextra -O0 -g -DSMOAP_HOST_TEST -Iswitch-mod/src switch-mod/tests/test_msg_font_safe.cpp switch-mod/src/util/MsgFontSafe.cpp -o test_msg_font_safe.exe
//
// Covers the four behavioral classes of the sanitizer:
//   1. ASCII passthrough (the 80 supported chars stay verbatim)
//   2. Missing-ASCII substitution (the 15 chars get visual fallback)
//   3. Latin-1 / General-Punctuation fold (smart quotes, dashes, accents)
//   4. Native non-ASCII passthrough (©Åáèéíó—…)
//   5. Buffer-cap / NUL termination / null-src safety
//   6. Realistic AP slot-name inputs (smart quotes from Steam autocorrect,
//      Latin-1 accents from real player names, mojibake bytes)

#define SMOAP_HOST_TEST 1

#include "util/MsgFontSafe.hpp"

#include <cstdio>
#include <cstring>
#include <string>

using namespace smoap::util;

namespace {

int g_failures = 0;
const char* g_current_test = "";

#define EXPECT(cond) do {                                                       \
    if (!(cond)) {                                                              \
        std::fprintf(stderr, "[%s] FAIL %s:%d: %s\n",                           \
                     g_current_test, __FILE__, __LINE__, #cond);                \
        ++g_failures;                                                           \
    }                                                                           \
} while (0)

#define EXPECT_EQ_S(actual, expected) do {                                      \
    std::string _a = (actual);                                                  \
    std::string _e = (expected);                                                \
    if (_a != _e) {                                                             \
        std::fprintf(stderr, "[%s] FAIL %s:%d: \"%s\" != \"%s\"\n",             \
                     g_current_test, __FILE__, __LINE__, _a.c_str(), _e.c_str()); \
        ++g_failures;                                                           \
    }                                                                           \
} while (0)

#define EXPECT_EQ_I(actual, expected) do {                                      \
    long long _a = (long long)(actual);                                         \
    long long _e = (long long)(expected);                                       \
    if (_a != _e) {                                                             \
        std::fprintf(stderr, "[%s] FAIL %s:%d: %lld != %lld\n",                 \
                     g_current_test, __FILE__, __LINE__, _a, _e);               \
        ++g_failures;                                                           \
    }                                                                           \
} while (0)

#define TEST(name) static void name();                                          \
    struct name##_runner { name##_runner() { g_current_test = #name; name(); } } name##_instance; \
    static void name()

std::string sanitize(const char* src) {
    char buf[256];
    sanitizeForMsgFont(src, buf, sizeof(buf));
    return std::string(buf);
}

}  // namespace

// --------------------------------------------------------------------------
// ASCII passthrough
// --------------------------------------------------------------------------

TEST(ascii_basic_passthrough) {
    EXPECT_EQ_S(sanitize("Got Cascade Power Moon from Alice!"),
                "Got Cascade Power Moon from Alice!");
}

TEST(ascii_all_80_present_chars_pass_through) {
    // All 80 supported printable chars (per scripts/inspect_smo_font.py).
    const char* all =
        " !\"%&'()*+,-./0123456789:?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "_abcdefghijklmnopqrstuvwxyz";
    EXPECT_EQ_S(sanitize(all), std::string(all));
}

TEST(ascii_empty_string) {
    EXPECT_EQ_S(sanitize(""), "");
}

// --------------------------------------------------------------------------
// Missing-ASCII substitutions (the 15 chars without glyphs)
// --------------------------------------------------------------------------

TEST(missing_ascii_hash_becomes_No_dot) {
    EXPECT_EQ_S(sanitize("track #4"), "track No.4");
}

TEST(missing_ascii_dollar_becomes_S) {
    EXPECT_EQ_S(sanitize("$Mario"), "SMario");
}

TEST(missing_ascii_semicolon_becomes_comma) {
    EXPECT_EQ_S(sanitize("a;b"), "a,b");
}

TEST(missing_ascii_angle_brackets_become_parens) {
    EXPECT_EQ_S(sanitize("<tag>"), "(tag)");
}

TEST(missing_ascii_equals_becomes_hyphen) {
    EXPECT_EQ_S(sanitize("x=1"), "x-1");
}

TEST(missing_ascii_square_brackets_become_parens) {
    EXPECT_EQ_S(sanitize("[AFK] Bob"), "(AFK) Bob");
}

TEST(missing_ascii_backslash_becomes_slash) {
    EXPECT_EQ_S(sanitize("a\\b"), "a/b");
}

TEST(missing_ascii_caret_becomes_apostrophe) {
    EXPECT_EQ_S(sanitize("x^2"), "x'2");
}

TEST(missing_ascii_backtick_becomes_apostrophe) {
    EXPECT_EQ_S(sanitize("`code`"), "'code'");
}

TEST(missing_ascii_curly_braces_become_parens) {
    EXPECT_EQ_S(sanitize("{x}"), "(x)");
}

TEST(missing_ascii_pipe_becomes_slash) {
    EXPECT_EQ_S(sanitize("a|b"), "a/b");
}

TEST(missing_ascii_tilde_becomes_hyphen) {
    EXPECT_EQ_S(sanitize("~Mario~"), "-Mario-");
}

TEST(missing_ascii_all_15_at_once) {
    // Every missing char in one shot — verifies the table is complete and
    // none of them silently pass through. Per-char mapping:
    //   # $ ; < = > [ \ ] ^ ` { | } ~
    //   No. S , ( - ) ( / ) ' ' ( / ) -
    EXPECT_EQ_S(sanitize("#$;<=>[\\]^`{|}~"),
                "No.S,(-)(/)''(/)-");
}

// --------------------------------------------------------------------------
// Smart-quote / typographic fold (the most common offender — autocorrect
// turns straight quotes into curly ones in Steam display names).
// --------------------------------------------------------------------------

TEST(smart_single_quotes_fold) {
    // U+2018 LSQUO, U+2019 RSQUO -> '
    EXPECT_EQ_S(sanitize("\xE2\x80\x98hi\xE2\x80\x99"), "'hi'");
}

TEST(smart_double_quotes_fold) {
    // U+201C LDQUO, U+201D RDQUO -> "
    EXPECT_EQ_S(sanitize("\xE2\x80\x9Chi\xE2\x80\x9D"), "\"hi\"");
}

TEST(en_dash_folds_to_hyphen) {
    // U+2013 EN DASH -> -
    EXPECT_EQ_S(sanitize("a\xE2\x80\x93""b"), "a-b");
}

TEST(em_dash_passes_through_natively) {
    // U+2014 EM DASH is in the font — round-trip the UTF-8 bytes verbatim.
    EXPECT_EQ_S(sanitize("a\xE2\x80\x94""b"), "a\xE2\x80\x94""b");
}

TEST(unicode_ellipsis_passes_through_natively) {
    // U+2026 HORIZONTAL ELLIPSIS — present in MessageFont38. Even though
    // the formatter uses ASCII "..." for its own truncation marker, an
    // ellipsis arriving from outside should round-trip.
    EXPECT_EQ_S(sanitize("hi\xE2\x80\xA6"), "hi\xE2\x80\xA6");
}

TEST(bullet_folds_to_asterisk) {
    // U+2022 BULLET -> *
    EXPECT_EQ_S(sanitize("\xE2\x80\xA2 item"), "* item");
}

TEST(trademark_folds_to_paren_TM) {
    EXPECT_EQ_S(sanitize("Mario\xE2\x84\xA2"), "Mario(TM)");
}

// --------------------------------------------------------------------------
// Latin-1 supplement
// --------------------------------------------------------------------------

TEST(latin1_native_supported_pass_through) {
    // Å á è é í ó © are the natively-supported non-ASCII codepoints. They
    // should NOT be folded — passthrough preserves SMO's own moon-name
    // strings ("Forêt" — wait, ê is U+00EA, not supported; use the
    // supported ones here instead).
    // © U+00A9, Å U+00C5, á U+00E1, è U+00E8, é U+00E9, í U+00ED, ó U+00F3
    const char* in = "\xC2\xA9 \xC3\x85 \xC3\xA1 \xC3\xA8 \xC3\xA9 \xC3\xAD \xC3\xB3";
    EXPECT_EQ_S(sanitize(in), in);
}

TEST(latin1_uppercase_E_acute_folds_to_E) {
    // U+00C9 Latin Capital Letter E with Acute is NOT in the font (only
    // the lowercase é is). Fold to plain "E".
    EXPECT_EQ_S(sanitize("\xC3\x89lite"), "Elite");
}

TEST(latin1_n_tilde_folds_to_n) {
    // ñ U+00F1 -> n
    EXPECT_EQ_S(sanitize("ma\xC3\xB1""ana"), "manana");
}

TEST(latin1_c_cedilla_folds_to_c) {
    // ç U+00E7 -> c
    EXPECT_EQ_S(sanitize("gar\xC3\xA7on"), "garcon");
}

TEST(latin1_e_circumflex_folds_to_e) {
    // ê U+00EA -> e
    EXPECT_EQ_S(sanitize("for\xC3\xAAt"), "foret");
}

TEST(latin1_u_diaeresis_folds_to_u) {
    // ü U+00FC -> u. The "" splits prevent the next hex digit from being
    // absorbed into the \x escape ("\xBCber" reads as one giant hex value).
    EXPECT_EQ_S(sanitize("\xC3\xBC" "ber"), "uber");
}

TEST(latin1_sharp_s_folds_to_ss) {
    // ß U+00DF -> ss
    EXPECT_EQ_S(sanitize("Stra\xC3\x9F" "e"), "Strasse");
}

TEST(latin1_inverted_punctuation_folds) {
    // ¡ U+00A1 -> !  ¿ U+00BF -> ?  (é U+00E9 is NATIVE — passes through)
    EXPECT_EQ_S(sanitize("\xC2\xA1" "Hola! \xC2\xBF" "qu\xC3\xA9?"),
                "!Hola! ?qu\xC3\xA9?");
}

TEST(latin1_degree_folds_to_space_deg) {
    // ° U+00B0 -> " deg" (leading space avoids "85deg" looking like a word)
    EXPECT_EQ_S(sanitize("85\xC2\xB0"), "85 deg");
}

TEST(latin1_registered_folds_to_paren_R) {
    EXPECT_EQ_S(sanitize("Brand\xC2\xAE"), "Brand(R)");
}

TEST(latin1_pound_yen_cent_fold) {
    // £ ¥ ¢ -> L Y c
    EXPECT_EQ_S(sanitize("\xC2\xA3""5 \xC2\xA5""500 \xC2\xA2""50"),
                "L5 Y500 c50");
}

TEST(latin1_fraction_folds) {
    // ¼ ½ ¾
    EXPECT_EQ_S(sanitize("\xC2\xBC \xC2\xBD \xC2\xBE"), "1/4 1/2 3/4");
}

TEST(latin1_soft_hyphen_drops) {
    // U+00AD SOFT HYPHEN -> "" (drop; it's a typesetting hint, not visible)
    EXPECT_EQ_S(sanitize("a\xC2\xAD" "b"), "ab");
}

TEST(latin1_nbsp_becomes_space) {
    // U+00A0 NBSP -> regular space (so the byte budget matches what's
    // rendered).
    EXPECT_EQ_S(sanitize("a\xC2\xA0" "b"), "a b");
}

// --------------------------------------------------------------------------
// Unknown / control / malformed -> '?'
// --------------------------------------------------------------------------

TEST(cjk_becomes_question_mark) {
    // 日本 U+65E5 U+672C — outside our coverage; the player sees "??"
    // (clearer than silent dropping).
    EXPECT_EQ_S(sanitize("\xE6\x97\xA5\xE6\x9C\xAC"), "??");
}

TEST(emoji_becomes_question_marks) {
    // 🍄 U+1F344 — 4-byte UTF-8, becomes one '?'
    EXPECT_EQ_S(sanitize("\xF0\x9F\x8D\x84"), "?");
}

TEST(control_chars_become_question_marks) {
    // 0x01..0x1F are control chars; no glyph anywhere. tab (0x09), newline
    // (0x0A) get '?' too — bubble text is single-line.
    char buf[8];
    sanitizeForMsgFont("a\tb\nc", buf, sizeof(buf));
    EXPECT_EQ_S(std::string(buf), "a?b?c");
}

TEST(malformed_utf8_continuation_emits_question_mark) {
    // Lone continuation byte 0x80.
    EXPECT_EQ_S(sanitize("\x80hi"), "?hi");
}

TEST(malformed_utf8_truncated_multibyte) {
    // 0xC3 expects a continuation byte; followed by 'Z' (high bit clear)
    // is a malformed sequence — emit '?' and resync.
    EXPECT_EQ_S(sanitize("\xC3Z"), "?Z");
}

TEST(del_char_becomes_question_mark) {
    // 0x7F DEL has no glyph; fold to '?'.
    char in[] = {'a', 0x7F, 'b', 0};
    EXPECT_EQ_S(sanitize(in), "a?b");
}

// --------------------------------------------------------------------------
// Buffer safety
// --------------------------------------------------------------------------

TEST(null_dst_returns_zero) {
    EXPECT_EQ_I(sanitizeForMsgFont("hi", nullptr, 64), 0);
}

TEST(zero_cap_returns_zero_and_does_not_write) {
    char buf[4] = {'X', 'Y', 'Z', 'W'};
    EXPECT_EQ_I(sanitizeForMsgFont("hi", buf, 0), 0);
    EXPECT_EQ_I(buf[0], 'X');  // untouched
}

TEST(null_src_emits_empty_nul_terminated) {
    char buf[8] = {'A', 'B', 'C', 0};
    EXPECT_EQ_I(sanitizeForMsgFont(nullptr, buf, sizeof(buf)), 0);
    EXPECT_EQ_I(buf[0], '\0');
}

TEST(cap_respected_no_partial_multibyte_write) {
    // Input: "abc—defghi". em-dash is 3 UTF-8 bytes. dst_cap=8 reserves
    // 1 byte for NUL, so at most 7 content bytes.
    // Trace with appendBytes invariant `out + n + 1 <= dst_cap`:
    //   'a' -> out=1; 'b' -> 2; 'c' -> 3; '—'(3) -> 6; 'd' -> 7;
    //   'e' check 7+1+1=9 > 8 -> stop. Output is "abc—d".
    // Verifies (a) no partial multibyte sequence is written, and (b) the
    // NUL is always at buf[n].
    const char* in = "abc\xE2\x80\x94" "defghi";
    char buf[8];
    const auto n = sanitizeForMsgFont(in, buf, sizeof(buf));
    EXPECT_EQ_I(buf[n], '\0');
    EXPECT_EQ_S(std::string(buf), std::string("abc\xE2\x80\x94" "d"));
}

TEST(cap_respected_substitution_overflow_truncates_cleanly) {
    // # -> "No." (3 bytes). With dst_cap=3 we have 2 bytes for content,
    // and "No." won't fit cleanly — the function should stop before
    // writing the partial substitution.
    const char* in = "a#b";
    char buf[3];
    const auto n = sanitizeForMsgFont(in, buf, sizeof(buf));
    // "a" fits (out=1, 1 byte left for NUL); "#" would emit "No." (3
    // bytes), needs 4 bytes including NUL — won't fit. Stop after 'a'.
    EXPECT_EQ_I(n, 1);
    EXPECT_EQ_S(std::string(buf), "a");
}

TEST(single_byte_cap_only_nul) {
    char buf[1] = {'X'};
    const auto n = sanitizeForMsgFont("hi", buf, sizeof(buf));
    EXPECT_EQ_I(n, 0);
    EXPECT_EQ_I(buf[0], '\0');
}

// --------------------------------------------------------------------------
// Realistic AP slot-name inputs (the actual reason this module exists)
// --------------------------------------------------------------------------

TEST(realistic_steam_smart_quote_username) {
    // Steam Big Picture autocorrect produces curly apostrophes. The user
    // sees "Got Frog from Bob's!" rather than the bubble cutting at the
    // missing glyph.
    const char* in = "Bob\xE2\x80\x99s";
    EXPECT_EQ_S(sanitize(in), "Bob's");
}

TEST(realistic_afk_tag_slot_name) {
    EXPECT_EQ_S(sanitize("[AFK] Mario_42"), "(AFK) Mario_42");
}

TEST(realistic_pipe_separator_slot_name) {
    EXPECT_EQ_S(sanitize("clan|playername"), "clan/playername");
}

TEST(realistic_player_name_with_accented_chars) {
    // Mixed-support Latin-1 name: é (U+00E9) passes through; ü (U+00FC)
    // folds to 'u'. "" string splits prevent \xBCn from being parsed as
    // a single oversized hex escape.
    EXPECT_EQ_S(sanitize("Caf\xC3\xA9_Br\xC3\xBC" "nhild"),
                "Caf\xC3\xA9_Brunhild");
}

TEST(realistic_japanese_username_falls_back_safely) {
    // A Japanese slot name like "マリオ" (Mario in katakana) becomes "???".
    // The English-locale font supports katakana but we don't extend
    // passthrough — see policy note in MsgFontSafe.cpp.
    EXPECT_EQ_S(sanitize("\xE3\x83\x9E\xE3\x83\xAA\xE3\x82\xAA"), "???");
}

TEST(realistic_long_smart_quote_name_stays_within_buf) {
    // Belt-and-braces: smart quotes 3-byte each, sanitize to 1-byte each.
    // Verifies the output is shorter than (or equal to) the input even
    // when input is densely Unicode.
    const char* in = "\xE2\x80\x98\xE2\x80\x99\xE2\x80\x9C\xE2\x80\x9D"
                     "\xE2\x80\x98\xE2\x80\x99\xE2\x80\x9C\xE2\x80\x9D";
    EXPECT_EQ_S(sanitize(in), "''\"\"''\"\"");
}

// --------------------------------------------------------------------------
// main
// --------------------------------------------------------------------------

int main() {
    if (g_failures == 0) {
        std::printf("test_msg_font_safe: ALL PASS\n");
        return 0;
    }
    std::fprintf(stderr, "test_msg_font_safe: %d FAILURES\n", g_failures);
    return 1;
}
