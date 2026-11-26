package com.termux.terminal;

/**
 * The extended grapheme cluster boundaries of Unicode Standard Annex 29, rules GB3 to GB999, decided with the properties
 * of {@link UnicodeTables}. A decision looks at the code point before the boundary and, for the rules that need it, at the
 * characters before that one, so that no state has to be kept between two calls.
 *
 * Printable ASCII always starts a cell, also after a prepended character. A terminal has to keep the letters that a
 * person types in their own cells, so rule GB9b does not apply to them.
 */
final class GraphemeBreak {

    private GraphemeBreak() {
    }

    /**
     * Tells if there is a boundary between {@code chars[from, end)} and {@code codePoint}. The characters before
     * {@code from} are not looked at, and the range must not be empty.
     */
    static boolean isBoundary(char[] chars, int from, int end, int codePoint) {
        if (codePoint >= 0x20 && codePoint < 0x7F) return true;
        final int before = Character.codePointBefore(chars, end);
        final int beforeProperties = UnicodeTables.properties(before);
        final int properties = UnicodeTables.properties(codePoint);
        final int left = UnicodeTables.graphemeBreak(beforeProperties);
        final int right = UnicodeTables.graphemeBreak(properties);

        // GB3, GB4 and GB5.
        if (left == UnicodeTables.GRAPHEME_BREAK_CR && right == UnicodeTables.GRAPHEME_BREAK_LF) return false;
        if (isControl(left) || isControl(right)) return true;
        // GB6, GB7 and GB8, the syllables of Hangul.
        if (left == UnicodeTables.GRAPHEME_BREAK_L && (right == UnicodeTables.GRAPHEME_BREAK_L || right == UnicodeTables.GRAPHEME_BREAK_V
            || right == UnicodeTables.GRAPHEME_BREAK_LV || right == UnicodeTables.GRAPHEME_BREAK_LVT)) return false;
        if ((left == UnicodeTables.GRAPHEME_BREAK_LV || left == UnicodeTables.GRAPHEME_BREAK_V)
            && (right == UnicodeTables.GRAPHEME_BREAK_V || right == UnicodeTables.GRAPHEME_BREAK_T)) return false;
        if ((left == UnicodeTables.GRAPHEME_BREAK_LVT || left == UnicodeTables.GRAPHEME_BREAK_T)
            && right == UnicodeTables.GRAPHEME_BREAK_T) return false;
        // A skin tone is part of the cell before it only when that is an emoji that can have one, as in UTS #51. Anywhere
        // else it is an emoji of its own.
        if (UnicodeTables.isEmojiModifier(properties) && !UnicodeTables.isEmojiModifierBase(beforeProperties)) return true;
        // GB9 and GB9a.
        if (right == UnicodeTables.GRAPHEME_BREAK_EXTEND || right == UnicodeTables.GRAPHEME_BREAK_ZWJ
            || right == UnicodeTables.GRAPHEME_BREAK_SPACINGMARK) return false;
        // GB9b.
        if (left == UnicodeTables.GRAPHEME_BREAK_PREPEND) return false;
        // GB9c.
        if (UnicodeTables.indicConjunctBreak(properties) == UnicodeTables.INDIC_CONJUNCT_BREAK_CONSONANT
            && followsConjunctLinker(chars, from, end)) return false;
        // GB11.
        if (left == UnicodeTables.GRAPHEME_BREAK_ZWJ && UnicodeTables.isExtendedPictographic(properties)
            && followsPictographic(chars, from, end - Character.charCount(before))) return false;
        // GB12 and GB13, the two letters of a flag.
        if (left == UnicodeTables.GRAPHEME_BREAK_REGIONAL_INDICATOR && right == UnicodeTables.GRAPHEME_BREAK_REGIONAL_INDICATOR) {
            return regionalIndicatorsBefore(chars, from, end) % 2 == 0;
        }
        // GB999.
        return true;
    }

    private static boolean isControl(int graphemeBreak) {
        return graphemeBreak == UnicodeTables.GRAPHEME_BREAK_CONTROL || graphemeBreak == UnicodeTables.GRAPHEME_BREAK_CR
            || graphemeBreak == UnicodeTables.GRAPHEME_BREAK_LF;
    }

    /** The number of regional indicators in a row that end at {@code end}. */
    private static int regionalIndicatorsBefore(char[] chars, int from, int end) {
        int count = 0;
        for (int i = end; i > from; ) {
            final int previous = Character.codePointBefore(chars, i);
            if (UnicodeTables.graphemeBreak(UnicodeTables.properties(previous)) != UnicodeTables.GRAPHEME_BREAK_REGIONAL_INDICATOR) break;
            count++;
            i -= Character.charCount(previous);
        }
        return count;
    }

    /** Tells if an extended pictographic character and then only extending characters end at {@code end}. */
    private static boolean followsPictographic(char[] chars, int from, int end) {
        for (int i = end; i > from; ) {
            final int previous = Character.codePointBefore(chars, i);
            final int properties = UnicodeTables.properties(previous);
            if (UnicodeTables.isExtendedPictographic(properties)) return true;
            if (UnicodeTables.graphemeBreak(properties) != UnicodeTables.GRAPHEME_BREAK_EXTEND) return false;
            i -= Character.charCount(previous);
        }
        return false;
    }

    /**
     * Tells if a consonant, then extending characters and linkers with at least one linker end at {@code end}, so that
     * a consonant after them continues the conjunct.
     */
    private static boolean followsConjunctLinker(char[] chars, int from, int end) {
        boolean linker = false;
        for (int i = end; i > from; ) {
            final int previous = Character.codePointBefore(chars, i);
            final int conjunctBreak = UnicodeTables.indicConjunctBreak(UnicodeTables.properties(previous));
            if (conjunctBreak == UnicodeTables.INDIC_CONJUNCT_BREAK_CONSONANT) return linker;
            if (conjunctBreak == UnicodeTables.INDIC_CONJUNCT_BREAK_LINKER) linker = true;
            else if (conjunctBreak != UnicodeTables.INDIC_CONJUNCT_BREAK_EXTEND) return false;
            i -= Character.charCount(previous);
        }
        return false;
    }

}
