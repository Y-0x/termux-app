# Unicode tables generator

`generate_unicode.py` downloads the official Unicode data files, parses them and writes
`terminal-emulator/src/main/java/com/termux/terminal/UnicodeTables.java`. `WcWidth` reads the width of every
character from these tables, so a new Unicode version needs no hand edit.

| Data file | Used for |
| --- | --- |
| `EastAsianWidth.txt` | wide and fullwidth characters, 2 columns |
| `extracted/DerivedGeneralCategory.txt` | nonspacing and enclosing marks, 0 columns |
| `emoji/emoji-data.txt` | `Extended_Pictographic` for emoji sequences, `Emoji` and `Emoji_Presentation` for U+FE0F |

## Use

Python 3 is enough, there are no packages to install. Run it from the project root:

```
python3 tools/unicode/generate_unicode.py                  # latest Unicode
python3 tools/unicode/generate_unicode.py --version 16.0.0 # one version
python3 tools/unicode/generate_unicode.py --source-dir DIR # files from a folder, no network
python3 tools/unicode/generate_unicode.py --check          # exit code 1 when the Java file is out of date
```

Downloaded files are kept in `tools/unicode/.cache`, which `tools/unicode/.gitignore` ignores. `--refresh` downloads them again.

## Run it with the build

Network access in a normal build is not wanted, F-Droid style builds forbid it, so the generated file is committed and
the tool is run by hand or by a CI job with `--check`. A Gradle task for a local build that always uses the newest data,
for `terminal-emulator/build.gradle`:

```groovy
tasks.register('generateUnicodeTables', Exec) {
    workingDir rootProject.projectDir
    commandLine 'python3', 'tools/unicode/generate_unicode.py'
}

if (project.hasProperty('updateUnicode')) {
    preBuild.dependsOn generateUnicodeTables
}
```

Then `./gradlew assembleDebug -PupdateUnicode` fetches the newest data before it compiles.

## When the format of a data file changes

The tool stops with an error instead of writing wrong tables: the header with the version must be found, and a few known
characters must be in the right tables, for example U+4E00 wide and U+0301 without width.
