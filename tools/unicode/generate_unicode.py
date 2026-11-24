#!/usr/bin/env python3
"""
Generates UnicodeTables.java from the official Unicode data files.

The files are downloaded from unicode.org, parsed, and written as Java range tables for the terminal emulator.
Only the Python standard library is used.

Usage, from the project root:

    python3 tools/unicode/generate_unicode.py               # latest Unicode, write the Java file
    python3 tools/unicode/generate_unicode.py --check       # fail if the Java file is out of date
    python3 tools/unicode/generate_unicode.py --version 16.0.0
    python3 tools/unicode/generate_unicode.py --source-dir DIR   # read the files from DIR, no network

The files that are read:

    EastAsianWidth.txt                 wide and fullwidth characters
    extracted/DerivedGeneralCategory.txt   nonspacing and enclosing marks, which have no width
    emoji/emoji-data.txt               Extended_Pictographic, Emoji and Emoji_Presentation
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
    "east_asian_width": "EastAsianWidth.txt",
    "general_category": "extracted/DerivedGeneralCategory.txt",
    "emoji": "emoji/emoji-data.txt",
}

DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_CODE_POINT = 0x10FFFF

LINE_PATTERN = re.compile(r"^\s*([0-9A-Fa-f]{4,6})(?:\.\.([0-9A-Fa-f]{4,6}))?\s*;\s*([A-Za-z_]+)")
VERSION_PATTERN = re.compile(r"^#\s*[A-Za-z]+(?:-[A-Za-z]+)*-(\d+\.\d+\.\d+)\.txt")


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
            if args.refresh or not os.path.isfile(path):
                download(source_url(args.version, key), path)
        if not os.path.isfile(path):
            sys.exit("missing source file %s" % path)
        with open(path, encoding="utf-8") as f:
            texts[key] = f.read()
    return texts


def file_version(text, name):
    """The Unicode version from the first comment line, for example '# EastAsianWidth-15.1.0.txt'."""
    for line in text.splitlines()[:5]:
        match = VERSION_PATTERN.match(line)
        if match:
            return match.group(1)
    sys.exit("cannot read the version of %s, the header format changed" % name)


def parse_ranges(text, wanted):
    """Collects the ranges of the lines whose property is in wanted, as a dict property to a list of ranges."""
    result = {name: [] for name in wanted}
    for line in text.splitlines():
        match = LINE_PATTERN.match(line)
        if not match or match.group(3) not in result:
            continue
        first = int(match.group(1), 16)
        last = int(match.group(2) or match.group(1), 16)
        if first > last or last > MAX_CODE_POINT:
            sys.exit("bad range in line: %s" % line)
        result[match.group(3)].append((first, last))
    return result


def merge(ranges):
    """Sorts the ranges and joins the ones that touch."""
    merged = []
    for first, last in sorted(ranges):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return merged


def contains(ranges, code_point):
    return any(first <= code_point <= last for first, last in ranges)


def build_tables(texts):
    widths = parse_ranges(texts["east_asian_width"], ("W", "F"))
    categories = parse_ranges(texts["general_category"], ("Mn", "Me"))
    emoji = parse_ranges(texts["emoji"], ("Emoji", "Emoji_Presentation", "Extended_Pictographic"))

    emoji_presentation = merge(emoji["Emoji_Presentation"])
    # Emoji that look like text by default and become emoji with U+FE0F.
    text_style = merge(subtract(emoji["Emoji"], emoji_presentation))

    tables = {
        "ZERO_WIDTH": merge(categories["Mn"] + categories["Me"]),
        "WIDE": merge(widths["W"] + widths["F"]),
        "EXTENDED_PICTOGRAPHIC": merge(emoji["Extended_Pictographic"]),
        "TEXT_STYLE_EMOJI": text_style,
    }
    check_tables(tables)
    return tables


def subtract(ranges, removed):
    """The code points of ranges that are not in removed."""
    remaining = []
    removed = merge(removed)
    for first, last in merge(ranges):
        start = first
        for r_first, r_last in removed:
            if r_last < start or r_first > last:
                continue
            if r_first > start:
                remaining.append((start, r_first - 1))
            start = r_last + 1
            if start > last:
                break
        if start <= last:
            remaining.append((start, last))
    return remaining


def check_tables(tables):
    """A change of a file format would give wrong tables without an error, so a few known facts must hold."""
    facts = [
        ("ZERO_WIDTH", 0x0301, True), ("ZERO_WIDTH", 0x0041, False),
        ("WIDE", 0x4E00, True), ("WIDE", 0x0041, False), ("WIDE", 0x1F600, True),
        ("EXTENDED_PICTOGRAPHIC", 0x1F600, True), ("EXTENDED_PICTOGRAPHIC", 0x0041, False),
        ("TEXT_STYLE_EMOJI", 0x263A, True), ("TEXT_STYLE_EMOJI", 0x1F600, False),
    ]
    for name, code_point, expected in facts:
        if contains(tables[name], code_point) != expected:
            sys.exit("check failed: U+%04X should %sbe in %s, the data format may have changed"
                     % (code_point, "" if expected else "not ", name))
    for name, ranges in tables.items():
        if not ranges:
            sys.exit("table %s is empty" % name)


JAVA_TEMPLATE = """\
// This file is generated by tools/unicode/generate_unicode.py, do not edit it.
// Unicode data: EastAsianWidth %(east_asian_width)s, DerivedGeneralCategory %(general_category)s, emoji-data %(emoji)s.
package com.termux.terminal;

/** The Unicode range tables that the width of a character depends on. */
final class UnicodeTables {

    private UnicodeTables() {
    }

    /** The version of the Unicode data that the tables were made from. */
    static final String UNICODE_VERSION = "%(version)s";

    /** Nonspacing and enclosing marks, they have no width. */
    static final int[][] ZERO_WIDTH = {
%(ZERO_WIDTH)s
    };

    /** East Asian Wide and Fullwidth characters, they take two columns. */
    static final int[][] WIDE = {
%(WIDE)s
    };

    /** Characters with the Extended_Pictographic property, the emoji that a zero width joiner can connect. */
    static final int[][] EXTENDED_PICTOGRAPHIC = {
%(EXTENDED_PICTOGRAPHIC)s
    };

    /**
     * Emoji that are drawn like text by default, so that U+FE0F makes them wide. These are the characters with the
     * Emoji property but without the Emoji_Presentation property.
     */
    static final int[][] TEXT_STYLE_EMOJI = {
%(TEXT_STYLE_EMOJI)s
    };

}
"""


def render_java(tables, versions):
    values = dict(versions)
    values["version"] = max(versions.values(), key=lambda v: tuple(int(p) for p in v.split(".")))
    for name, ranges in tables.items():
        values[name] = "\n".join("        {0x%05x, 0x%05x}," % (first, last) for first, last in ranges)
    return JAVA_TEMPLATE % values


def main():
    parser = argparse.ArgumentParser(description="Generate UnicodeTables.java from the official Unicode data files.")
    parser.add_argument("--version", default="latest", help="Unicode version like 16.0.0, default is latest")
    parser.add_argument("--source-dir", help="read the data files from this directory instead of the network")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE, help="where downloaded files are kept")
    parser.add_argument("--refresh", action="store_true", help="download the files again even if they are cached")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="the Java file to write")
    parser.add_argument("--check", action="store_true", help="do not write, fail if the Java file differs")
    args = parser.parse_args()

    texts = fetch_sources(args)
    versions = {key: file_version(text, FILES[key]) for key, text in texts.items()}
    source = render_java(build_tables(texts), versions)

    if args.check:
        current = open(args.output, encoding="utf-8").read() if os.path.isfile(args.output) else ""
        if current != source:
            sys.exit("%s is out of date, run tools/unicode/generate_unicode.py" % args.output)
        print("up to date")
        return
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(source)
    print("wrote %s, Unicode %s" % (args.output, ", ".join("%s %s" % kv for kv in sorted(versions.items()))))


if __name__ == "__main__":
    main()
