// Font sanitizer for SMO's speech-bubble + cutscene-label rendering path.
//
// Why this exists: MessageFont38.bffnt (the font behind every CapMessage
// balloon and `TxtScenario` pane) is missing 15 of the 95 ASCII printable
// glyphs and almost all common non-ASCII punctuation. Codepoints with no
// glyph render as blanks at best — at worst, the bubble drops the line tail
// at the first missing char (observed for player slot names containing `~`
// or smart quotes). The mod feeds the font three uncontrolled streams:
// AP-server slot names (`item.from`), Talkatoo speech substitutions, and
// system bubbles like the connect/disconnect notifications. This module
// folds those streams to glyphs the font actually ships.
//
// Coverage table (USen MessageFont38.bffnt, verified via
// scripts/inspect_smo_font.py against SMO 1.0.0):
//
//   ASCII printable present (80):
//     space ! " % & ' ( ) * + , - . / 0-9 : ? @ A-Z _ a-z
//   ASCII printable MISSING (15):
//     # $ ; < = > [ \ ] ^ ` { | } ~
//   Native non-ASCII supported (9): © Å á è é í ó — …
//   Everything else (smart quotes, en-dash, bullet, ™, °, Latin-1 accents
//   not in the 9 above, all CJK we don't care about in English bubbles, ...)
//   has no glyph.
//
// Pure function, host-testable, no allocations. Output is guaranteed to
// contain only codepoints the font supports.

#pragma once

#include <cstddef>

namespace smoap::util {

// Sanitize a UTF-8 input into a UTF-8 output containing only MessageFont38-
// supported codepoints. `dst` is always NUL-terminated when `dst_cap > 0`.
// Returns the number of bytes written, NOT including the NUL.
//
// Substitution policy (see MsgFontSafe.cpp for the full table):
//   - 80 ASCII printable supported chars      -> passthrough
//   - 15 missing ASCII printable (#$;<=>[\]^`{|}~) -> visual ASCII fallback
//   - Native non-ASCII (©Åáèéíó—…)            -> passthrough (UTF-8 bytes)
//   - Smart quotes / en-dash / bullet / ™ / ° -> ASCII equivalents
//   - Latin-1 accented letters (À-ÿ)          -> ASCII-fold (Á→A, ñ→n, ...)
//   - Anything else (CJK, control chars, malformed UTF-8) -> '?'
//
// When the output would overflow `dst_cap - 1`, sanitize stops at the last
// fully-emitted codepoint substitution (it never writes a partial multi-byte
// sequence) and NUL-terminates. The CapMessage pipeline is forgiving of
// mid-word truncation; the formatter's outer fit-check is the primary length
// gate.
std::size_t sanitizeForMsgFont(const char* src,
                               char* dst,
                               std::size_t dst_cap);

}  // namespace smoap::util
