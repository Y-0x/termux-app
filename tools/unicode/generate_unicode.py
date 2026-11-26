#!/usr/bin/env python3
"""
Generates UnicodeTables.java from the official Unicode data files.

The files are downloaded from unicode.org and parsed. Every code point gets one packed property value, the width, the
general category, the grapheme break property, the indic conjunct break property and the emoji flags. The values are
kept in a two stage table, as CPython and kitty do, so that a property is found with a few array reads and no search.
Only the Python standard library is used.

Usage, from the project root:

    python3 tools/unicode/generate_unicode.py               # latest Unicode, write the Java file
    python3 tools/unicode/generate_unicode.py --check       # fail if the Java file is out of date
    python3 tools/unicode/generate_unicode.py --version 16.0.0
    python3 tools/unicode/generate_unicode.py --source-dir DIR   # read the files from DIR, no network

The files that are read:

    extracted/DerivedEastAsianWidth.txt      wide and fullwidth characters, with the unassigned ones that default to wide
    extracted/DerivedGeneralCategory.txt     the general category
    auxiliary/GraphemeBreakProperty.txt      the grapheme cluster break property
    DerivedCoreProperties.txt                the indic conjunct break property and the default ignorable characters
    emoji/emoji-data.txt                     Emoji, Emoji_Presentation, Emoji_Modifier, Emoji_Modifier_Base, Extended_Pictographic
    emoji/emoji-variation-sequences.txt      characters that U+FE0E and U+FE0F can change
"""

import argparse
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUTPUT = os.path.join(PROJECT_ROOT, "terminal-emulator", "src", "main", "java", "com", "termux", "terminal",
                              "UnicodeTables.java")
DEFAULT_CACHE = os.path.join(PROJECT_ROOT, "tools", "unicode", ".cache")

BASE_URL = "https://www.unicode.org/Public/%s/ucd/"
LATEST = "UCD/latest"

# Path of every source file below the base url.
FILES = {
    "east_asian_width": "extracted/DerivedEastAsianWidth.txt",
    "general_category": "extracted/DerivedGeneralCategory.txt",
    "grapheme_break": "auxiliary/GraphemeBreakProperty.txt",
    "derived_core": "DerivedCoreProperties.txt",
    "emoji": "emoji/emoji-data.txt",
    "emoji_variation": "emoji/emoji-variation-sequences.txt",
}

DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_CODE_POINT = 0x10FFFF
CODE_POINT_COUNT = MAX_CODE_POINT + 1

LINE_PATTERN = re.compile(r"^\s*([0-9A-Fa-f]{4,6})(?:\.\.([0-9A-Fa-f]{4,6}))?\s*;\s*([A-Za-z_]+)")
# A line of DerivedCoreProperties.txt, for example "094D          ; InCB; Linker # Mn       DEVANAGARI SIGN VIRAMA".
INCB_PATTERN = re.compile(r"^\s*([0-9A-Fa-f]{4,6})(?:\.\.([0-9A-Fa-f]{4,6}))?\s*;\s*InCB\s*;\s*([A-Za-z_]+)")
# A line of emoji-variation-sequences.txt, for example "0023 FE0F  ; emoji style;  # (1.1) NUMBER SIGN".
VARIATION_PATTERN = re.compile(r"^\s*([0-9A-Fa-f]{4,6})\s+(FE0E|FE0F)\s*;\s*(text|emoji) style")
# The version is in the header, either as "# Version: 18.0.0" or in the file name "# EastAsianWidth-18.0.0.txt".
VERSION_PATTERNS = (
    re.compile(r"^#\s*Version:\s*(\d+(?:\.\d+){1,2})\s*$"),
    re.compile(r"^#\s*[A-Za-z]+(?:-[A-Za-z]+)*-(\d+(?:\.\d+){1,2})\.txt\s*$"),
    re.compile(r"^#\s*Used with Emoji Version\s+(\d+(?:\.\d+){1,2})\b"),
)
HEADER_LINES = 30

# The values of the properties, the order is the number that is stored. The default of a code point that no line of
# the file names is Cn for the category and Other for the grapheme break.
CATEGORIES = ("Lu", "Ll", "Lt", "Lm", "Lo", "Mn", "Mc", "Me", "Nd", "Nl", "No", "Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po",
              "Sm", "Sc", "Sk", "So", "Zs", "Zl", "Zp", "Cc", "Cf", "Cs", "Co", "Cn")
DEFAULT_CATEGORY = "Cn"
GRAPHEME_BREAKS = ("Other", "Prepend", "CR", "LF", "Control", "Extend", "Regional_Indicator", "SpacingMark",
                   "L", "V", "T", "LV", "LVT", "ZWJ")
INDIC_CONJUNCT_BREAKS = ("None", "Linker", "Consonant", "Extend")
SOFT_HYPHEN = 0x00AD
HANGUL_CHOSEONG_FILLER = 0x115F

# The layout of the packed property value, a field is a number of bits and a flag is one bit.
FIELDS = (
    ("WIDTH", 2),
    ("CATEGORY", 5),
    ("GRAPHEME_BREAK", 4),
    ("INDIC_CONJUNCT_BREAK", 2),
)
FLAGS = ("EXTENDED_PICTOGRAPHIC", "EMOJI", "EMOJI_PRESENTATION", "EMOJI_MODIFIER", "EMOJI_MODIFIER_BASE", "VARIATION_BASE")


def field_layout():
    """The shift and the number of bits of every field and every flag in the packed value."""
    layout, shift = {}, 0
    for name, bits in FIELDS:
        layout[name] = (shift, bits)
        shift += bits
    for name in FLAGS:
        layout[name] = (shift, 1)
        shift += 1
    return layout


LAYOUT = field_layout()


def source_url(version, key):
    return (BASE_URL % (LATEST if version == "latest" else version)) + FILES[key]


def download(url, target):
    last_error = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "termux-unicode-generator"})
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                data = response.read()
            if not data:
                raise ValueError("empty response")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Write to a temporary file first, so that an interrupted download never leaves a broken cache file.
            handle, temporary = tempfile.mkstemp(dir=os.path.dirname(target))
            with os.fdopen(handle, "wb") as out:
                out.write(data)
            os.replace(temporary, target)
            return
        except (urllib.error.URLError, OSError, ValueError) as error:
            last_error = error
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(2 * attempt)
    sys.exit("cannot download %s: %s" % (url, last_error))


def fetch_sources(args):
    """Returns the text of every source file, from the source dir, the cache or the network."""
    texts = {}
    for key, relative in FILES.items():
        if args.source_dir:
            path = os.path.join(args.source_dir, relative)
            if not os.path.isfile(path):
                path = os.path.join(args.source_dir, os.path.basename(relative))
        else:
            path = os.path.join(args.cache_dir, args.version, relative)
            # The files of "latest" change with every release, so they are never taken from the cache unless asked.
            stale = args.refresh or args.version == "latest"
            if not args.offline and (stale or not os.path.isfile(path)):
                download(source_url(args.version, key), path)
        if not os.path.isfile(path):
            sys.exit("missing source file %s" % path)
        with open(path, encoding="utf-8") as f:
            texts[key] = f.read()
    return texts


def file_version(text, name):
    """The Unicode version from the header of a file, as a tuple like (18, 0, 0)."""
    for line in text.splitlines()[:HEADER_LINES]:
        for pattern in VERSION_PATTERNS:
            match = pattern.match(line)
            if match:
                parts = [int(part) for part in match.group(1).split(".")]
                return tuple(parts + [0] * (3 - len(parts)))
    sys.exit("cannot read the version of %s, the header format changed" % name)


def common_version(texts):
    """The Unicode version of all files, they must agree, or the tables would mix two versions."""
    versions = {key: file_version(text, FILES[key]) for key, text in texts.items()}
    if len(set(versions.values())) != 1:
        sys.exit("the Unicode data files have different versions: %s" % ", ".join(
            "%s %s" % (FILES[key], ".".join(map(str, version))) for key, version in sorted(versions.items())))
    return ".".join(map(str, next(iter(versions.values()))))


def parse_ranges(text, pattern, wanted, name):
    """Collects the ranges of the lines whose property is in wanted, as a dict property to a list of ranges."""
    result = {value: [] for value in wanted}
    for line in text.splitlines():
        match = pattern.match(line)
        if not match or match.group(3) not in result:
            continue
        first = int(match.group(1), 16)
        last = int(match.group(2) or match.group(1), 16)
        if first > last or last > MAX_CODE_POINT:
            sys.exit("bad range in %s: %s" % (name, line))
        result[match.group(3)].append((first, last))
    return result


def parse_variation_bases(text):
    """The characters that have an emoji style and a text style sequence."""
    emoji_style, text_style = set(), set()
    for line in text.splitlines():
        match = VARIATION_PATTERN.match(line)
        if match:
            (emoji_style if match.group(3) == "emoji" else text_style).add(int(match.group(1), 16))
    # Every character with one style has the other one too, a difference means that the file is not read right.
    if emoji_style != text_style:
        sys.exit("the variation sequences have different characters for the emoji and the text style")
    return emoji_style


def assign(ranges_by_value, default):
    """A list with one value for every code point, taken from the ranges of every value."""
    table = [default] * CODE_POINT_COUNT
    for value, ranges in ranges_by_value.items():
        for first, last in ranges:
            for code_point in range(first, last + 1):
                table[code_point] = value
    return table


def width_of(code_point, category, east_asian_width, grapheme_break, default_ignorable):
    """The number of columns of a character on its own, 0, 1 or 2."""
    # Marks, format characters, separators, controls and the default ignorable characters do not move the cursor, as in
    # glibc and in wcwidth. The soft hyphen has a width, and so has the Hangul choseong filler, which wcwidth takes as
    # wide. A prepended format character, such as the Arabic number sign, is drawn in front of the characters that follow.
    if code_point not in (SOFT_HYPHEN, HANGUL_CHOSEONG_FILLER) and grapheme_break != "Prepend" \
            and (category in ("Mn", "Me", "Cf", "Zl", "Zp", "Cc") or default_ignorable):
        return 0
    # The two regional indicators of a flag are one cell of 2 columns, the first one takes it.
    if grapheme_break == "Regional_Indicator":
        return 2
    return 2 if east_asian_width in ("W", "F") else 1


def pack(width, category, grapheme_break, indic_conjunct_break, flags):
    value = 0
    for name, number in (("WIDTH", width), ("CATEGORY", CATEGORIES.index(category)),
                         ("GRAPHEME_BREAK", GRAPHEME_BREAKS.index(grapheme_break)),
                         ("INDIC_CONJUNCT_BREAK", INDIC_CONJUNCT_BREAKS.index(indic_conjunct_break))):
        shift, bits = LAYOUT[name]
        if number >= 1 << bits:
            sys.exit("the value %d does not fit the field %s" % (number, name))
        value |= number << shift
    for name in FLAGS:
        if name in flags:
            value |= 1 << LAYOUT[name][0]
    return value


def build_properties(texts):
    """One packed property value for every code point."""
    widths = parse_ranges(texts["east_asian_width"], LINE_PATTERN, ("W", "F"), FILES["east_asian_width"])
    wide = assign(widths, "N")
    categories = assign(parse_ranges(texts["general_category"], LINE_PATTERN, CATEGORIES, FILES["general_category"]),
                        DEFAULT_CATEGORY)
    breaks = assign(parse_ranges(texts["grapheme_break"], LINE_PATTERN, GRAPHEME_BREAKS[1:], FILES["grapheme_break"]),
                    GRAPHEME_BREAKS[0])
    conjuncts = assign(parse_ranges(texts["derived_core"], INCB_PATTERN, INDIC_CONJUNCT_BREAKS[1:],
                                    FILES["derived_core"]), INDIC_CONJUNCT_BREAKS[0])
    ignorable = assign(parse_ranges(texts["derived_core"], LINE_PATTERN, ("Default_Ignorable_Code_Point",),
                                    FILES["derived_core"]), None)
    emoji = parse_ranges(texts["emoji"], LINE_PATTERN,
                         ("Extended_Pictographic", "Emoji", "Emoji_Presentation", "Emoji_Modifier",
                          "Emoji_Modifier_Base"), FILES["emoji"])
    variation_bases = parse_variation_bases(texts["emoji_variation"])

    flags = [set() for _ in range(CODE_POINT_COUNT)]
    for name, flag in (("Extended_Pictographic", "EXTENDED_PICTOGRAPHIC"), ("Emoji", "EMOJI"),
                       ("Emoji_Presentation", "EMOJI_PRESENTATION"), ("Emoji_Modifier", "EMOJI_MODIFIER"),
                       ("Emoji_Modifier_Base", "EMOJI_MODIFIER_BASE")):
        for first, last in emoji[name]:
            for code_point in range(first, last + 1):
                flags[code_point].add(flag)
    for code_point in variation_bases:
        flags[code_point].add("VARIATION_BASE")

    return [pack(width_of(code_point, categories[code_point], wide[code_point], breaks[code_point],
                          ignorable[code_point] is not None),
                 categories[code_point], breaks[code_point], conjuncts[code_point], flags[code_point])
            for code_point in range(CODE_POINT_COUNT)]


def split_two_stage(indexes):
    """
    Splits the sequence into blocks of the same size and keeps every different block once, as CPython does for its
    Unicode tables. The block size with the smallest result is used. Returns the shift, the table of the block numbers
    and the table of the blocks.
    """
    best = None
    for shift in range(1, 13):
        size = 1 << shift
        known, first_stage, second_stage = {}, [], []
        for start in range(0, len(indexes), size):
            block = tuple(indexes[start:start + size])
            if block not in known:
                known[block] = len(second_stage) // size
                second_stage.extend(block)
            first_stage.append(known[block])
        # Both stages are stored as 16 bit characters.
        cost = (len(first_stage) + len(second_stage)) * 2
        if best is None or cost < best[0]:
            best = (cost, shift, first_stage, second_stage)
    _, shift, first_stage, second_stage = best
    if max(first_stage) > 0xFFFF or max(second_stage) > 0xFFFF:
        sys.exit("a table has a value that does not fit 16 bits")
    return shift, first_stage, second_stage


def build_tables(texts):
    properties = build_properties(texts)
    palette, indexes, numbers = [], [], {}
    for value in properties:
        if value not in numbers:
            numbers[value] = len(palette)
            palette.append(value)
        indexes.append(numbers[value])
    shift, first_stage, second_stage = split_two_stage(indexes)
    tables = {"shift": shift, "first": first_stage, "second": second_stage, "palette": palette}
    check_tables(tables, properties)
    return tables


def lookup(tables, code_point):
    """The same reads that the Java code does."""
    shift = tables["shift"]
    block = tables["first"][code_point >> shift]
    return tables["palette"][tables["second"][(block << shift) | (code_point & ((1 << shift) - 1))]]


def field(value, name):
    shift, bits = LAYOUT[name]
    return (value >> shift) & ((1 << bits) - 1)


def check_tables(tables, properties):
    """The tables must give back the property of every code point, and a few known facts must hold."""
    for code_point, expected in enumerate(properties):
        if lookup(tables, code_point) != expected:
            sys.exit("the table lookup of U+%04X gives a wrong value, this is a bug of the generator" % code_point)

    def category(code_point):
        return CATEGORIES[field(properties[code_point], "CATEGORY")]

    def grapheme_break(code_point):
        return GRAPHEME_BREAKS[field(properties[code_point], "GRAPHEME_BREAK")]

    def conjunct(code_point):
        return INDIC_CONJUNCT_BREAKS[field(properties[code_point], "INDIC_CONJUNCT_BREAK")]

    def width(code_point):
        return field(properties[code_point], "WIDTH")

    def flag(code_point, name):
        return bool(properties[code_point] >> LAYOUT[name][0] & 1)

    facts = [
        (width(0x0041), 1), (category(0x0041), "Lu"), (grapheme_break(0x0041), "Other"),
        (width(0x0301), 0), (category(0x0301), "Mn"), (grapheme_break(0x0301), "Extend"),
        (width(0x4E00), 2), (width(0xFF21), 2), (width(0x00AD), 1), (width(0x0600), 1), (width(0x0600), 1), (width(0x200B), 0), (width(0x000A), 0),
        (grapheme_break(0x000D), "CR"), (grapheme_break(0x000A), "LF"), (grapheme_break(0x200D), "ZWJ"),
        (grapheme_break(0x1F1E6), "Regional_Indicator"), (width(0x1F1E6), 2), (grapheme_break(0x0600), "Prepend"),
        (grapheme_break(0xAC00), "LV"), (grapheme_break(0x1100), "L"), (grapheme_break(0x1161), "V"),
        (grapheme_break(0x11A8), "T"), (grapheme_break(0x0903), "SpacingMark"),
        (conjunct(0x094D), "Linker"), (conjunct(0x0915), "Consonant"), (conjunct(0x0041), "None"),
        (width(0x1F600), 2), (flag(0x1F600, "EXTENDED_PICTOGRAPHIC"), True), (flag(0x1F600, "EMOJI"), True),
        (flag(0x1F600, "EMOJI_PRESENTATION"), True), (flag(0x263A, "EMOJI_PRESENTATION"), False),
        (flag(0x263A, "VARIATION_BASE"), True), (flag(0x1F600, "VARIATION_BASE"), False),
        (flag(0x1F3FB, "EMOJI_MODIFIER"), True), (flag(0x1F44D, "EMOJI_MODIFIER_BASE"), True),
        (flag(0x1F600, "EMOJI_MODIFIER_BASE"), False), (width(0x1160), 0), (width(0x115F), 2), (width(0xE0001), 0), (flag(0x0041, "EXTENDED_PICTOGRAPHIC"), False),
    ]
    for number, (got, expected) in enumerate(facts, 1):
        if got != expected:
            sys.exit("check %d failed: got %r, expected %r, the data format may have changed" % (number, got, expected))


# The stage tables are Java strings, because the compiler limits a method to 64 KB of code, which an array of this
# size would exceed, and a constant string to 64 KB, so the strings are cut into parts.
CHARS_PER_STRING = 8000
CHARS_PER_LINE = 12


def java_char(value):
    """A character of a Java string literal. The escapes of the line break, the quote and the backslash are spelled
    out, because the compiler reads a unicode escape before it reads the literal."""
    special = {0x0A: "\\n", 0x0D: "\\r", 0x22: '\\"', 0x5C: "\\\\"}
    if value in special:
        return special[value]
    if 0x20 <= value < 0x7F:
        return chr(value)
    return "\\u%04x" % value


def java_strings(values):
    """The values as the lines of an array of Java strings."""
    lines = []
    for start in range(0, len(values), CHARS_PER_STRING):
        chunk = values[start:start + CHARS_PER_STRING]
        pieces = ["".join(java_char(v) for v in chunk[i:i + CHARS_PER_LINE]) for i in range(0, len(chunk), CHARS_PER_LINE)]
        lines.append('        "' + '"\n                + "'.join(pieces) + '",')
    return "\n".join(lines)


def java_constants(names, prefix):
    return "\n".join("    static final int %s_%s = %d;" % (prefix, name.upper(), number)
                     for number, name in enumerate(names))


def java_layout():
    lines = []
    for name, (shift, bits) in LAYOUT.items():
        lines.append("    private static final int %s_SHIFT = %d;" % (name, shift))
        if bits > 1:
            lines.append("    private static final int %s_MASK = 0x%x;" % (name, (1 << bits) - 1))
    return "\n".join(lines)


JAVA_TEMPLATE = """\
// This file is generated by tools/unicode/generate_unicode.py, do not edit it.
// Unicode data: version %(version)s of EastAsianWidth, DerivedGeneralCategory, GraphemeBreakProperty,
// DerivedCoreProperties, emoji-data and emoji-variation-sequences.
package com.termux.terminal;

/**
 * The properties of every code point that the terminal depends on, in a two stage table. The first stage gives the
 * number of a block of {@code 1 << SHIFT} code points, the second stage gives the number of the property value of a
 * code point in that block, and the same blocks are stored once. A property is found with a few array reads.
 */
final class UnicodeTables {

    private UnicodeTables() {
    }

    /** The version of the Unicode data that the tables were made from. */
    static final String UNICODE_VERSION = "%(version)s";

%(layout)s

    /** The general categories. */
%(categories)s

    /** The values of the grapheme cluster break property. */
%(breaks)s

    /** The values of the indic conjunct break property. */
%(conjuncts)s

    private static final int SHIFT = %(shift)d;
    private static final int MASK = (1 << SHIFT) - 1;
    private static final int LAST_CODE_POINT = 0x10FFFF;

    private static final String[] FIRST_STAGE_DATA = {
%(first)s
    };

    private static final String[] SECOND_STAGE_DATA = {
%(second)s
    };

    /** Every different property value, the second stage has the numbers of them. */
    private static final int[] PROPERTIES = {
%(palette)s
    };

    private static final char[] FIRST_STAGE = decode(FIRST_STAGE_DATA, %(first_length)d);
    private static final char[] SECOND_STAGE = decode(SECOND_STAGE_DATA, %(second_length)d);

    private static char[] decode(String[] data, int length) {
        final char[] result = new char[length];
        int position = 0;
        for (String part : data) {
            part.getChars(0, part.length(), result, position);
            position += part.length();
        }
        return result;
    }

    /** The packed properties of a code point, a value that is not a code point has the properties of an unassigned one. */
    static int properties(int codePoint) {
        if (codePoint < 0 || codePoint > LAST_CODE_POINT) return PROPERTIES[SECOND_STAGE[0]];
        return PROPERTIES[SECOND_STAGE[(FIRST_STAGE[codePoint >> SHIFT] << SHIFT) | (codePoint & MASK)]];
    }

    /** The width of a character on its own, 0, 1 or 2. */
    static int width(int properties) {
        return (properties >> WIDTH_SHIFT) & WIDTH_MASK;
    }

    static int category(int properties) {
        return (properties >> CATEGORY_SHIFT) & CATEGORY_MASK;
    }

    static int graphemeBreak(int properties) {
        return (properties >> GRAPHEME_BREAK_SHIFT) & GRAPHEME_BREAK_MASK;
    }

    static int indicConjunctBreak(int properties) {
        return (properties >> INDIC_CONJUNCT_BREAK_SHIFT) & INDIC_CONJUNCT_BREAK_MASK;
    }

    static boolean isExtendedPictographic(int properties) {
        return (properties >> EXTENDED_PICTOGRAPHIC_SHIFT & 1) != 0;
    }

    static boolean isEmoji(int properties) {
        return (properties >> EMOJI_SHIFT & 1) != 0;
    }

    /** The emoji that are drawn as an emoji when nothing says otherwise, Emoji_Presentation. */
    static boolean isEmojiPresentation(int properties) {
        return (properties >> EMOJI_PRESENTATION_SHIFT & 1) != 0;
    }

    static boolean isEmojiModifier(int properties) {
        return (properties >> EMOJI_MODIFIER_SHIFT & 1) != 0;
    }

    /** The emoji that a skin tone modifier can follow, Emoji_Modifier_Base. */
    static boolean isEmojiModifierBase(int properties) {
        return (properties >> EMOJI_MODIFIER_BASE_SHIFT & 1) != 0;
    }

    /** Characters with an emoji and a text style variation sequence, U+FE0F and U+FE0E change their look. */
    static boolean hasVariationSequence(int properties) {
        return (properties >> VARIATION_BASE_SHIFT & 1) != 0;
    }

}
"""


def render_java(tables, version):
    palette = ["0x%05x" % value for value in tables["palette"]]
    palette_lines = []
    for start in range(0, len(palette), 8):
        palette_lines.append("        " + ", ".join(palette[start:start + 8]) + ",")
    values = {
        "version": version,
        "layout": java_layout(),
        "categories": java_constants(CATEGORIES, "CATEGORY"),
        "breaks": java_constants(GRAPHEME_BREAKS, "GRAPHEME_BREAK"),
        "conjuncts": java_constants(INDIC_CONJUNCT_BREAKS, "INDIC_CONJUNCT_BREAK"),
        "shift": tables["shift"],
        "first": java_strings(tables["first"]),
        "second": java_strings(tables["second"]),
        "palette": "\n".join(palette_lines),
        "first_length": len(tables["first"]),
        "second_length": len(tables["second"]),
    }
    return JAVA_TEMPLATE % values


def write_atomically(path, text):
    """Writes through a temporary file, so that a failure never leaves a half written Java file."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def main():
    parser = argparse.ArgumentParser(description="Generate UnicodeTables.java from the official Unicode data files.")
    parser.add_argument("--version", default="latest", help="Unicode version like 16.0.0, default is latest")
    parser.add_argument("--source-dir", help="read the data files from this directory instead of the network")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE, help="where downloaded files are kept")
    parser.add_argument("--refresh", action="store_true", help="download the files again even if they are cached")
    parser.add_argument("--offline", action="store_true", help="use only the cached files, no download")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="the Java file to write")
    parser.add_argument("--check", action="store_true", help="do not write, fail if the Java file differs")
    args = parser.parse_args()

    texts = fetch_sources(args)
    version = common_version(texts)
    source = render_java(build_tables(texts), version)

    if args.check:
        current = open(args.output, encoding="utf-8").read() if os.path.isfile(args.output) else ""
        if current != source:
            sys.exit("%s is out of date, run tools/unicode/generate_unicode.py" % args.output)
        print("up to date")
        return
    write_atomically(args.output, source)
    print("wrote %s, Unicode %s" % (args.output, version))


if __name__ == "__main__":
    main()
