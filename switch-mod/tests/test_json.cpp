// Host-compiler tests for smoap::util::json::Reader.
//
// Build (any host compiler — no devkitPro):
//   g++ -std=c++20 -Wall -Wextra -O0 -g
//       switch-mod/tests/test_json.cpp switch-mod/src/util/Json.cpp
//       -Iswitch-mod/src -o test_json
//   ./test_json
//
// Exercises the AP wire-protocol message shapes from docs/wire-protocol.md.

#include "util/Json.hpp"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <string_view>

using smoap::util::json::Encoder;
using smoap::util::json::LineBuffer;
using smoap::util::json::Reader;

namespace {

int g_failures = 0;
const char* g_current_test = "";

#define EXPECT(cond) do {                                                       \
    if (!(cond)) {                                                              \
        std::fprintf(stderr, "[%s] FAIL %s:%d: %s\n",                            \
                     g_current_test, __FILE__, __LINE__, #cond);                 \
        ++g_failures;                                                           \
    }                                                                           \
} while (0)

#define EXPECT_EQ_SV(actual, expected) do {                                     \
    std::string_view _a = (actual);                                             \
    std::string_view _e = (expected);                                           \
    if (_a != _e) {                                                             \
        std::fprintf(stderr, "[%s] FAIL %s:%d: \"%.*s\" != \"%.*s\"\n",         \
                     g_current_test, __FILE__, __LINE__,                        \
                     (int)_a.size(), _a.data(), (int)_e.size(), _e.data());     \
        ++g_failures;                                                           \
    }                                                                           \
} while (0)

#define EXPECT_EQ_I(actual, expected) do {                                      \
    auto _a = (actual);                                                         \
    auto _e = (expected);                                                       \
    if (_a != _e) {                                                             \
        std::fprintf(stderr, "[%s] FAIL %s:%d: %lld != %lld\n",                 \
                     g_current_test, __FILE__, __LINE__,                        \
                     (long long)_a, (long long)_e);                             \
        ++g_failures;                                                           \
    }                                                                           \
} while (0)

// Helper: make a writable buffer from a literal (Reader decodes escapes in
// place, so the buffer must be mutable).
struct Buf {
    std::string s;
    explicit Buf(std::string_view lit) : s(lit) {}
    char* data() { return s.data(); }
    std::size_t size() const { return s.size(); }
};

#define TEST(name) static void name(); \
    struct name##_runner { name##_runner() { g_current_test = #name; name(); } } name##_instance; \
    static void name()

// --------------------------------------------------------------------------
// Switch -> Bridge messages
// --------------------------------------------------------------------------

TEST(hello) {
    Buf b(R"({"t":"hello","mod_ver":"0.1.0+abc1234","smo_ver":"1.3.0","cap_table_hash":"sha1:deadbeef"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");              EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "hello");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "mod_ver");        EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "0.1.0+abc1234");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "smo_ver");        EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "1.3.0");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "cap_table_hash"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "sha1:deadbeef");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(check_moon) {
    Buf b(R"({"t":"check","kind":"moon","kingdom":"Cascade","shine_id":"Our First Power Moon"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");        EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "check");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kind");     EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "moon");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kingdom");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Cascade");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "shine_id"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Our First Power Moon");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(check_capture) {
    Buf b(R"({"t":"check","kind":"capture","cap":"Goomba"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");    EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "check");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kind"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "capture");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "cap");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Goomba");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(status) {
    Buf b(R"({"t":"status","kingdom":"Metro","scenario":2,"moons_collected":47})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");       EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "status");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kingdom"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Metro");
    std::int64_t n = 0;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "scenario");        EXPECT(r.nextInt(n)); EXPECT_EQ_I(n, 2);
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "moons_collected"); EXPECT(r.nextInt(n)); EXPECT_EQ_I(n, 47);
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(goal) {
    Buf b(R"({"t":"goal"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "goal");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(ping_large_ts) {
    Buf b(R"({"t":"ping","ts_ms":1731536400000})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "ping");
    std::int64_t ts = 0;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "ts_ms"); EXPECT(r.nextInt(ts)); EXPECT_EQ_I(ts, 1731536400000LL);
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(log_msg) {
    Buf b(R"({"t":"log","level":"info","msg":"hook installed for ShineGet at 0x..."})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");     EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "log");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "level"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "info");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "msg");   EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "hook installed for ShineGet at 0x...");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

// --------------------------------------------------------------------------
// Bridge -> Switch messages
// --------------------------------------------------------------------------

TEST(hello_ack) {
    Buf b(R"({"t":"hello_ack","ok":true,"seed":"X4F2","slot":"Mario","cap_table_hash":"sha1:abc"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "hello_ack");
    bool ok = false;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "ok");   EXPECT(r.nextBool(ok)); EXPECT(ok == true);
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "seed"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "X4F2");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "slot"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Mario");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "cap_table_hash"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "sha1:abc");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(checked_replay) {
    Buf b(R"({"t":"checked_replay","ids":[{"kind":"moon","kingdom":"Cascade","shine_id":"Our First Power Moon"},{"kind":"capture","cap":"Frog"}]})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "checked_replay");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "ids");
    EXPECT(r.enterArray());
    // First entry
    EXPECT(r.hasMoreInArray());
    EXPECT(r.enterObject());
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kind");     EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "moon");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kingdom");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Cascade");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "shine_id"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Our First Power Moon");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
    // Second entry
    EXPECT(r.hasMoreInArray());
    EXPECT(r.enterObject());
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kind"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "capture");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "cap");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Frog");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
    EXPECT(!r.hasMoreInArray());
    EXPECT(r.exitArray());
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(checked_replay_empty) {
    Buf b(R"({"t":"checked_replay","ids":[]})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "checked_replay");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "ids"); EXPECT(r.enterArray());
    EXPECT(!r.hasMoreInArray());
    EXPECT(r.exitArray());
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(item_moon) {
    Buf b(R"({"t":"item","kind":"moon","kingdom":"Sand","shine_id":"PoolUnderwater","from":"Bob"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");        EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "item");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kind");     EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "moon");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kingdom");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Sand");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "shine_id"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "PoolUnderwater");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "from");     EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Bob");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(print_msg) {
    Buf b(R"json({"t":"print","text":"Bob found Mario's Power Moon (Lake)"})json");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");    EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "print");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "text"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "Bob found Mario's Power Moon (Lake)");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(ap_state_msg) {
    Buf b(R"({"t":"ap_state","conn":"ready"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");    EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "ap_state");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "conn"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "ready");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(err_msg) {
    Buf b(R"({"t":"err","code":"unknown_kind","ctx":"check"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");    EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "err");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "code"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "unknown_kind");
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "ctx");  EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "check");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

// --------------------------------------------------------------------------
// Edge cases
// --------------------------------------------------------------------------

TEST(escape_sequences) {
    // Contains: quote, backslash, newline, tab, BMP unicode (é = U+00E9).
    Buf b(R"({"text":"a\"b\\c\nd\teéf"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "text");
    EXPECT(r.nextString(v));
    static const char kExpected[] = "a\"b\\c\nd\te\xC3\xA9" "f";
    EXPECT_EQ_SV(v, std::string_view(kExpected, sizeof(kExpected) - 1));
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(negative_int) {
    Buf b(R"({"v":-42})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k;
    EXPECT(r.nextField(k));
    std::int64_t n = 0;
    EXPECT(r.nextInt(n)); EXPECT_EQ_I(n, -42);
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(bool_and_null) {
    Buf b(R"({"a":true,"b":false,"c":null,"d":"x"})");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "a"); bool a = false; EXPECT(r.nextBool(a)); EXPECT(a);
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "b"); bool bv = true; EXPECT(r.nextBool(bv)); EXPECT(!bv);
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "c"); EXPECT(r.isNull());
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "d"); EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "x");
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(whitespace_tolerant) {
    Buf b(" {  \"a\" : 1 ,\n\t\"b\" : [ 1 , 2 , 3 ] } ");
    Reader r(b.data(), b.size());
    EXPECT(r.enterObject());
    std::string_view k;
    std::int64_t n = 0;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "a"); EXPECT(r.nextInt(n)); EXPECT_EQ_I(n, 1);
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "b"); EXPECT(r.enterArray());
    EXPECT(r.hasMoreInArray()); EXPECT(r.nextInt(n)); EXPECT_EQ_I(n, 1);
    EXPECT(r.hasMoreInArray()); EXPECT(r.nextInt(n)); EXPECT_EQ_I(n, 2);
    EXPECT(r.hasMoreInArray()); EXPECT(r.nextInt(n)); EXPECT_EQ_I(n, 3);
    EXPECT(!r.hasMoreInArray());
    EXPECT(r.exitArray());
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(reject_unterminated_string) {
    Buf b(R"({"t":"hel)");
    Reader r(b.data(), b.size());
    std::string_view k, v;
    EXPECT(r.enterObject());
    EXPECT(r.nextField(k));
    EXPECT(!r.nextString(v));
}

TEST(reject_truncated_object) {
    Buf b(R"({"t":"check","kind":)");
    Reader r(b.data(), b.size());
    std::string_view k, v;
    EXPECT(r.enterObject());
    EXPECT(r.nextField(k));
    EXPECT(r.nextString(v));
    EXPECT(r.nextField(k));
    // The value is missing; nextString should fail (and subsequent ops too).
    EXPECT(!r.nextString(v));
}

TEST(reject_float_value) {
    Buf b(R"({"x":1.5})");
    Reader r(b.data(), b.size());
    std::string_view k;
    EXPECT(r.enterObject());
    EXPECT(r.nextField(k));
    std::int64_t n = 0;
    EXPECT(!r.nextInt(n));
}

// --------------------------------------------------------------------------
// Encoder
//
// These exercise the depth-tracking path that previously used
// `std::vector<bool>::push_back`. Pushing past the libstdc++ allocator's
// broken TLS slot in our subsdk9 link crashed the worker on 2026-05-16;
// the encoder now uses a fixed-size `bool[]`. The Switch crash is not
// reproducible on host, but these tests pin the output of the new
// scaffolding so any silent corruption in the bookkeeping shows up here.
// --------------------------------------------------------------------------

#define EXPECT_EQ_VIEW(buf, expected) do {                                      \
    std::string_view _a((buf).data(), (buf).size());                            \
    std::string_view _e(expected);                                              \
    if (_a != _e) {                                                             \
        std::fprintf(stderr, "[%s] FAIL %s:%d: \"%.*s\" != \"%.*s\"\n",         \
                     g_current_test, __FILE__, __LINE__,                        \
                     (int)_a.size(), _a.data(), (int)_e.size(), _e.data());     \
        ++g_failures;                                                           \
    }                                                                           \
} while (0)

TEST(encode_hello) {
    // Mirrors the actual sendHello payload that crashed in Ryujinx.
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject()
        .key("t").value("hello")
        .key("mod_ver").value("0.1.0")
        .key("smo_ver").value("1.0.0")
        .key("cap_table_hash").value("")
     .endObject();
    EXPECT_EQ_VIEW(buf,
        R"({"t":"hello","mod_ver":"0.1.0","smo_ver":"1.0.0","cap_table_hash":""})");
    EXPECT(!buf.truncated());
}

TEST(encode_empty_object) {
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject().endObject();
    EXPECT_EQ_VIEW(buf, "{}");
}

TEST(encode_empty_array) {
    LineBuffer buf;
    Encoder e{buf};
    e.beginArray().endArray();
    EXPECT_EQ_VIEW(buf, "[]");
}

TEST(encode_array_of_objects) {
    // checked_replay shape: top-level object with an "ids" array of objects.
    // Without the cross-frame "needs comma" fix this emits "[{...}{...}]".
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject()
        .key("t").value("checked_replay")
        .key("ids").beginArray()
            .beginObject()
                .key("kind").value("moon")
                .key("kingdom").value("Cascade")
            .endObject()
            .beginObject()
                .key("kind").value("capture")
                .key("cap").value("Frog")
            .endObject()
        .endArray()
     .endObject();
    EXPECT_EQ_VIEW(buf,
        R"({"t":"checked_replay","ids":[{"kind":"moon","kingdom":"Cascade"},{"kind":"capture","cap":"Frog"}]})");
}

TEST(encode_mixed_value_types) {
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject()
        .key("s").value("x")
        .key("i").value(static_cast<std::int64_t>(-1))
        .key("ii").value(42)
        .key("b").value(true)
        .key("bb").value(false)
        .key("big").value(static_cast<std::int64_t>(1731536400000LL))
     .endObject();
    EXPECT_EQ_VIEW(buf,
        R"({"s":"x","i":-1,"ii":42,"b":true,"bb":false,"big":1731536400000})");
}

TEST(encode_int64_boundary) {
    // INT64_MIN/MAX hit the 20-char path inside our snprintf buffer (size 24).
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject()
        .key("min").value(static_cast<std::int64_t>(INT64_MIN))
        .key("max").value(static_cast<std::int64_t>(INT64_MAX))
     .endObject();
    EXPECT_EQ_VIEW(buf,
        R"({"min":-9223372036854775808,"max":9223372036854775807})");
}

TEST(encode_string_escapes) {
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject().key("s").value("a\"b\\c\nd\re\tf").endObject();
    EXPECT_EQ_VIEW(buf, R"({"s":"a\"b\\c\nd\re\tf"})");
}

TEST(encode_nested_deep) {
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject()
        .key("a").beginObject()
            .key("b").beginArray()
                .beginObject()
                    .key("c").beginArray()
                        .value(1).value(2).value(3)
                    .endArray()
                .endObject()
            .endArray()
        .endObject()
     .endObject();
    EXPECT_EQ_VIEW(buf, R"({"a":{"b":[{"c":[1,2,3]}]}})");
}

TEST(encode_round_trip_then_parse) {
    // Any subtle comma/quote bug in the new encoder should make this fail to
    // parse with our own Reader.
    LineBuffer buf;
    {
        Encoder e{buf};
        e.beginObject()
            .key("t").value("snapshot_chunk")
            .key("seq").value(7)
            .key("entries").beginArray()
                .beginObject().key("kind").value("moon").key("id").value("obj214").endObject()
                .beginObject().key("kind").value("capture").key("id").value("Frog").endObject()
                .beginObject().key("kind").value("moon").key("id").value("obj100").endObject()
            .endArray()
         .endObject();
    }
    // Reader mutates buffer in-place during escape decoding — copy first.
    std::string copy(buf.data(), buf.size());
    Reader r(copy.data(), copy.size());
    EXPECT(r.enterObject());
    std::string_view k, v;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "t");   EXPECT(r.nextString(v)); EXPECT_EQ_SV(v, "snapshot_chunk");
    std::int64_t n = 0;
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "seq"); EXPECT(r.nextInt(n));    EXPECT_EQ_I(n, 7);
    EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "entries"); EXPECT(r.enterArray());
    int count = 0;
    while (r.hasMoreInArray()) {
        EXPECT(r.enterObject());
        EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "kind"); EXPECT(r.nextString(v));
        EXPECT(r.nextField(k)); EXPECT_EQ_SV(k, "id");   EXPECT(r.nextString(v));
        EXPECT(!r.nextField(k));
        EXPECT(r.exitObject());
        ++count;
    }
    EXPECT_EQ_I(count, 3);
    EXPECT(r.exitArray());
    EXPECT(!r.nextField(k));
    EXPECT(r.exitObject());
}

TEST(encode_depth_overflow_does_not_corrupt_outer) {
    LineBuffer buf;
    Encoder e{buf};
    constexpr int kPush = Encoder::kMaxDepth + 4;
    for (int i = 0; i < kPush; ++i) {
        if (i > 0) e.key("k");
        e.beginObject();
    }
    for (int i = 0; i < kPush; ++i) {
        e.endObject();
    }
    int opens = 0, closes = 0;
    for (std::size_t i = 0; i < buf.size(); ++i) {
        if (buf.data()[i] == '{') ++opens;
        if (buf.data()[i] == '}') ++closes;
    }
    EXPECT_EQ_I(opens, kPush);
    EXPECT_EQ_I(closes, kPush);
}

TEST(encode_reuse_buffer_after_clear) {
    // The bug pattern: same code path firing repeatedly across many
    // (re)connections. A LineBuffer reused across iterations must produce
    // identical output to a fresh one each time.
    LineBuffer buf;
    for (int iter = 0; iter < 32; ++iter) {
        buf.clear();
        Encoder e{buf};
        e.beginObject().key("n").value(iter).endObject();
        char expected[32];
        std::snprintf(expected, sizeof(expected), R"({"n":%d})", iter);
        EXPECT_EQ_VIEW(buf, expected);
        EXPECT(!buf.truncated());
    }
}

TEST(encode_overflow_sets_truncated_flag) {
    // Pump bytes until LineBuffer overflows. The flag must trip, and we
    // must not crash. Caller-side: kMaxLineBytes (8 KiB) is far larger than
    // any actual wire message, so this is a guard against future growth.
    LineBuffer buf;
    Encoder e{buf};
    e.beginObject().key("payload").value(std::string(LineBuffer::kCap, 'x'));
    e.endObject();
    EXPECT(buf.truncated());
    EXPECT_EQ_I(buf.size(), LineBuffer::kCap);
}

}  // namespace

int main() {
    if (g_failures != 0) {
        std::fprintf(stderr, "\n%d failure(s)\n", g_failures);
        return 1;
    }
    std::fprintf(stdout, "All tests passed.\n");
    return 0;
}
