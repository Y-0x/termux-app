package com.termux.terminal;

/**
 * Implementation of wcwidth(3) with the tables of the official Unicode data, with the width of a cell that depends on the characters around it:
 * a zero width joiner, a pair of regional indicators, a skin tone and U+FE0F change the width of the characters.
 *
 * Implementation from https://github.com/jquast/wcwidth but we return 0 for unprintable characters.
 *
 * IMPORTANT:
 * Must be kept in sync with the following:
 * https://github.com/termux/wcwidth
 * https://github.com/termux/libandroid-support
 * https://github.com/termux/termux-packages/tree/master/packages/libandroid-support
 */
public final class WcWidth {

    private static final int VARIATION_SELECTOR_TEXT = 0xFE0E;
    private static final int VARIATION_SELECTOR_EMOJI = 0xFE0F;
    private static final int REGIONAL_INDICATOR_FIRST = 0x1F1E6;
    private static final int REGIONAL_INDICATOR_LAST = 0x1F1FF;
    private static final int KEYCAP = 0x20E3;

    /**
     * The width of a code point on its own when the terminal does not cluster graphemes, as wcwidth(3) of a shell or a
     * line editor has it: a regional indicator is as wide as a letter, so that a flag has the 2 columns of its 2 letters.
     */
    public static int width(int ucs, boolean graphemeClusters) {
        if (!graphemeClusters && REGIONAL_INDICATOR_FIRST <= ucs && ucs <= REGIONAL_INDICATOR_LAST) return 1;
        return width(ucs);
    }

    /** Return the terminal display width of a code point on its own: 0, 1 || 2. */
    public static int width(int ucs) {
        // Printable ASCII is most of the text of a terminal.
        if (ucs >= 0x20 && ucs < 0x7F) return 1;
        return UnicodeTables.width(UnicodeTables.properties(ucs));
    }

    /** The width at an index position in a java char array, see {@link #width(char[], int, int)}. */
    public static int width(char[] chars, int index) {
        return width(chars, index, chars.length);
    }

    /**
     * The width of the code point at an index position in a java char array that is valid up to {@code limit}.
     * The characters around it count, as in a grapheme cluster:
     * <ul>
     * <li>A character that follows a zero width joiner and is an emoji joins the cell before it, so it has width 0.</li>
     * <li>The second regional indicator of a pair, a flag, and a skin tone after an emoji have width 0.</li>
     * <li>A narrow emoji that is followed by U+FE0F gets width 2, a wide one that is followed by U+FE0E gets width 1.</li>
     * </ul>
     */
    public static int width(char[] chars, int index, int limit) {
        return width(chars, index, limit, true);
    }

    /**
     * The width of the code point at an index position, see {@link #width(char[], int, int)}. Without grapheme clustering
     * the characters around it do not count, only the code point does, as it is for wcwidth(3).
     */
    public static int width(char[] chars, int index, int limit, boolean graphemeClusters) {
        final int codePoint = codePointAt(chars, index, limit);
        if (!graphemeClusters) return width(codePoint, false);
        // Only U+FE0F and U+FE0E after a character can change the width of printable ASCII, as in a keycap.
        if (codePoint >= 0x20 && codePoint < 0x7F) {
            final int following = index + 1;
            if (following >= limit || (chars[following] != VARIATION_SELECTOR_EMOJI && chars[following] != VARIATION_SELECTOR_TEXT)) return 1;
        }
        final int properties = UnicodeTables.properties(codePoint);
        final int width = UnicodeTables.width(properties);
        if (width == 0) return 0;
        // A character that is not at a grapheme cluster boundary belongs to the cell before it.
        if (index > 0 && !GraphemeBreak.isBoundary(chars, 0, index, codePoint)) return 0;

        final int next = index + Character.charCount(codePoint);
        if (next < limit && UnicodeTables.hasVariationSequence(properties)) {
            if (width == 1 && chars[next] == VARIATION_SELECTOR_EMOJI) return 2;
            if (width == 2 && chars[next] == VARIATION_SELECTOR_TEXT) return 1;
        }
        return width;
    }

    static boolean isExtendedPictographic(int codePoint) {
        return UnicodeTables.isExtendedPictographic(UnicodeTables.properties(codePoint));
    }

    /** Tells if a code point has an emoji and a text variation sequence, so that U+FE0F and U+FE0E change its look. */
    static boolean hasEmojiVariation(int codePoint) {
        return UnicodeTables.hasVariationSequence(UnicodeTables.properties(codePoint));
    }

    /** Tells if a code point is one of the 26 regional indicators, the two of a pair are a flag. */
    public static boolean isRegionalIndicator(int codePoint) {
        return REGIONAL_INDICATOR_FIRST <= codePoint && codePoint <= REGIONAL_INDICATOR_LAST;
    }

    /**
     * Tells if the code point at an index position is drawn as a color emoji, and not with the font of the terminal.
     * A regional indicator, a keycap and an emoji that is wide or followed by U+FE0F are. A symbol such as the copyright
     * sign is an emoji only with U+FE0F.
     */
    public static boolean isEmojiPresentation(char[] chars, int index, int limit) {
        final int codePoint = codePointAt(chars, index, limit);
        if (codePoint == KEYCAP || (REGIONAL_INDICATOR_FIRST <= codePoint && codePoint <= REGIONAL_INDICATOR_LAST)) return true;
        if (!isExtendedPictographic(codePoint)) return false;
        final int next = index + Character.charCount(codePoint);
        if (next < limit && chars[next] == VARIATION_SELECTOR_EMOJI) return true;
        return width(codePoint) == 2;
    }

    /** Tells if a code point may belong to the cell before it. Printable ASCII always starts a cell. */
    public static boolean mayJoinCell(int codePoint) {
        return codePoint >= 0x80;
    }

    /** Tells if {@code codePoint} can change the width of the cell that it is added to. */
    public static boolean isVariationSelector(int codePoint) {
        return codePoint == VARIATION_SELECTOR_EMOJI || codePoint == VARIATION_SELECTOR_TEXT;
    }

    /**
     * Tells if a code point that follows the cell {@code cell} has no width of its own and joins the cell.
     * This is the same decision that {@link #width(char[], int, int)} makes for a code point in a row.
     */
    public static boolean joinsCell(char[] cell, int cellLength, int codePoint) {
        return cellLength > 0 && !GraphemeBreak.isBoundary(cell, 0, cellLength, codePoint);
    }

    private static int codePointAt(char[] chars, int index, int limit) {
        final char c = chars[index];
        return Character.isHighSurrogate(c) && index + 1 < limit ? Character.toCodePoint(c, chars[index + 1]) : c;
    }

    /**
     * The zero width characters count like combining characters in the `chars` array from start
     * index to end index (exclusive).
     */
    public static int zeroWidthCharsCount(char[] chars, int start, int end) {
        if (start < 0 || start >= chars.length)
            return 0;

        int count = 0;
        for (int i = start; i < end && i < chars.length;) {
            if (width(chars, i, end) <= 0) count++;
            i += Character.isHighSurrogate(chars[i]) ? 2 : 1;
        }
        return count;
    }

}
