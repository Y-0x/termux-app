# Unicode tables generator

`generate_unicode.py` downloads the official Unicode data files, parses them and writes
`terminal-emulator/src/main/java/com/termux/terminal/UnicodeTables.java`. `WcWidth` reads the width of every
character from these tables, so a new Unicode version needs no hand edit.

| Data file | Used for |
| --- | --- |
| `EastAsianWidth.txt` | wide and fullwidth characters, 2 columns |
| `extracted/DerivedGeneralCategory.txt` | nonspacing and enclosing marks, 0 columns |
| `emoji/emoji-data.txt` | `Extended_Pictographic`, the emoji that a zero width joiner can connect |
| `emoji/emoji-variation-sequences.txt` | the characters that U+FE0F makes wide and U+FE0E makes narrow |

## Use

Python 3 is enough, there are no packages to install. Run it from the project root:

```
python3 tools/unicode/generate_unicode.py                  # latest Unicode
python3 tools/unicode/generate_unicode.py --version 16.0.0 # one version
python3 tools/unicode/generate_unicode.py --source-dir DIR # files from a folder, no network
python3 tools/unicode/generate_unicode.py --check          # exit code 1 when the Java file is out of date
```

The files of `latest` are downloaded on every run, because they change with every release. The files of a fixed
version are kept in `tools/unicode/.cache`, which `tools/unicode/.gitignore` ignores, and `--refresh` downloads them
again. `--offline` uses only the cached files. The four files must have the same Unicode version, the tool stops if
they do not, so that the tables never mix two versions.

## Run it with the build

`UnicodeTables.java` is not stored in git, `.gitignore` ignores it. Every build has to make it first.

* The GitHub workflows run `python3 tools/unicode/generate_unicode.py` before gradle.
* On a development machine run the same command once after a clone, and again to get a newer Unicode version.
* Builds that cannot run python or reach unicode.org, like a JitPack build, need the generated file made before
  they start, or the generator run in their own setup step.

## When the format of a data file changes

The tool stops with an error instead of writing wrong tables: the header with the version must be found, and a few known
characters must be in the right tables, for example U+4E00 wide and U+0301 without width.
