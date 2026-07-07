from __future__ import annotations

from app import MAX_CHARS_PER_CHUNK
from app import chunk_text
from app import chunk_text_with_offsets
from app import find_word_start_offset
from app import sentence_split
from app import split_long_piece


class TestSentenceSplit:
    def test_period(self):
        result = sentence_split("Hello world. Goodbye world.")
        assert result == ["Hello world.", "Goodbye world."]

    def test_question_mark(self):
        result = sentence_split("What is this? It is a test.")
        assert result == ["What is this?", "It is a test."]

    def test_exclamation(self):
        result = sentence_split("Wow! Amazing!")
        assert result == ["Wow!", "Amazing!"]

    def test_semicolon(self):
        result = sentence_split("First clause; second clause.")
        assert result == ["First clause;", "second clause."]

    def test_colon(self):
        result = sentence_split("Note: this is important.")
        assert result == ["Note:", "this is important."]

    def test_newline_paragraphs(self):
        result = sentence_split("Paragraph one.\n\nParagraph two.\n\nParagraph three.")
        assert result == ["Paragraph one.", "Paragraph two.", "Paragraph three."]

    def test_empty(self):
        result = sentence_split("")
        assert result == []

    def test_leading_trailing_whitespace(self):
        result = sentence_split("  Hello.  ")
        assert result == ["Hello."]


class TestSplitLongPiece:
    def test_under_limit_passes_through(self):
        result = split_long_piece("short text", 100)
        assert result == ["short text"]

    def test_splits_on_comma(self):
        piece = "First part, which is fairly long, and then continues, until it finally ends."
        result = split_long_piece(piece, 50)
        for chunk in result:
            assert len(chunk) <= 50

    def test_splits_on_closing_paren(self):
        piece = "A sentence (with parenthetical content) that is quite long and needs splitting."
        result = split_long_piece(piece, 50)
        for chunk in result:
            assert len(chunk) <= 50

    def test_word_level_split_long_wordless_string(self):
        piece = "a b c d e f g h i j k l m n o p q r s t u v w x y z" * 10
        result = split_long_piece(piece, 20)
        for chunk in result:
            assert len(chunk) <= 20

    def test_clause_accumulator_merges(self):
        piece = "short, and another short part."
        result = split_long_piece(piece, 20)
        assert len(result) >= 1

    def test_empty_string(self):
        result = split_long_piece("", 10)
        assert result == [""]


class TestChunkText:
    def test_empty_text(self):
        result = chunk_text("")
        assert result == []

    def test_single_short_sentence(self):
        result = chunk_text("Hello world.")
        assert result == ["Hello world."]

    def test_multi_sentence_merging(self):
        text = "Short. Another short. Third."
        result = chunk_text(text, 200)
        assert len(result) == 1

    def test_single_long_sentence_split_across_clauses(self):
        text = "This is a very long sentence that keeps going and going on forever, plus more content here, finally wrapping up to the end."
        result = chunk_text(text, 50)
        for chunk in result:
            assert len(chunk) <= 50

    def test_mixed_short_and_long(self):
        text = "Hi. This is a much longer sentence that contains quite a number of words, commas, and continues past the limit, yes it does. Bye."
        result = chunk_text(text, 60)
        for chunk in result:
            assert len(chunk) <= 60
        assert len(result) >= 2


class TestSplitLongPieceEdgeCases:
    def test_empty_clause_skipped(self):
        result = split_long_piece("a, , b, c", 10)
        combined = " ".join(result)
        assert "a" in combined
        assert "b" in combined

    def test_clause_with_paren_split(self):
        piece = "Hello (world) there"
        result = split_long_piece(piece, 50)
        assert len(result) >= 1

    def test_long_clause_word_split_stores_current(self):
        piece = "keep, " + "w1 " * 15 + "w2 " * 15
        result = split_long_piece(piece, 30)
        assert len(result) >= 1

    def test_single_word_longer_than_max(self):
        result = split_long_piece("supercalifragilisticexpialidocious", 10)
        assert len(result) >= 1

    def test_word_chunk_with_current_appended(self):
        piece = "a " * 5 + "b " * 2 + "c " * 15
        result = split_long_piece(piece, 8)
        for chunk in result:
            assert len(chunk) <= 8


class TestChunkTextWithOffsetsEdgeCases:
    def test_effective_start_none_returns_empty(self):
        result = chunk_text_with_offsets("hello world", max_chars=200, start_offset=100)
        assert result == []

    def test_current_word_chunk_with_current_saved(self):
        text = "keep this, " + "a " * 50
        result = chunk_text_with_offsets(text, max_chars=40)
        assert len(result) >= 1


class TestChunkTextWithOffsets:
    def test_empty_text(self):
        result = chunk_text_with_offsets("")
        assert result == []

    def test_text_shorter_than_max(self):
        text = "Hello world."
        result = chunk_text_with_offsets(text, MAX_CHARS_PER_CHUNK)
        assert len(result) == 1
        assert result[0].text == "Hello world."
        assert result[0].start == 0
        assert result[0].end == len(text)

    def test_multi_chunk_offset_tracking(self):
        words = " ".join(["word"] * 200)
        result = chunk_text_with_offsets(words, 50)
        assert len(result) > 1
        for i, chunk in enumerate(result):
            assert chunk.start < chunk.end
            assert len(chunk.text) <= 50
            if i > 0:
                assert chunk.start >= result[i - 1].end

    def test_start_offset_skips_initial_words(self):
        text = "first second third fourth fifth sixth seventh"
        result = chunk_text_with_offsets(text, 30, start_offset=12)
        assert result
        assert "first" not in result[0].text or result[0].start >= 12

    def test_exact_word_boundary_start(self):
        text = "hello world here we go"
        result = chunk_text_with_offsets(text, 200, start_offset=6)
        assert result[0].text.startswith("world")


class TestFindWordStartOffset:
    def test_start_of_word(self):
        assert find_word_start_offset("hello world", 0) == 0

    def test_middle_of_word(self):
        assert find_word_start_offset("hello world", 3) == 0

    def test_end_of_text(self):
        assert find_word_start_offset("hello world", 11) is None

    def test_beyond_text_bounds(self):
        assert find_word_start_offset("hello world", 100) is None

    def test_empty_text(self):
        assert find_word_start_offset("", 0) is None
