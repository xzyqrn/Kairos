"""
tests/test_cog_quiz_helpers.py — Unit tests for cogs/quiz.py helper functions.

Tests the pure _parse_question() function directly without Discord mocking.
"""

from __future__ import annotations

import json

from cogs.quiz import _parse_question


def _make_raw(
    question: str = "Who built the ark?",
    options: list[str] | None = None,
    answer: str = "B",
    explanation: str = "Genesis 6.",
    wrap_fence: bool = False,
) -> str:
    if options is None:
        options = ["Moses", "Noah", "Abraham", "David"]
    obj = {
        "question": question,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }
    raw = json.dumps(obj)
    if wrap_fence:
        raw = f"```json\n{raw}\n```"
    return raw


# ── TestParseQuestion ─────────────────────────────────────────────────────────

class TestParseQuestion:
    def test_valid_json_returns_dict(self):
        result = _parse_question(_make_raw())
        assert result is not None

    def test_all_required_keys_present(self):
        result = _parse_question(_make_raw())
        assert set(result.keys()) == {"question", "options", "answer", "explanation"}

    def test_answer_normalised_to_uppercase(self):
        result = _parse_question(_make_raw(answer="b"))
        assert result["answer"] == "B"

    def test_strips_markdown_code_fence(self):
        result = _parse_question(_make_raw(wrap_fence=True))
        assert result is not None
        assert result["answer"] == "B"

    def test_valid_answer_letters_a_through_d(self):
        for letter in ["A", "B", "C", "D"]:
            result = _parse_question(_make_raw(answer=letter))
            assert result is not None

    def test_invalid_answer_letter_returns_none(self):
        result = _parse_question(_make_raw(answer="E"))
        assert result is None

    def test_missing_required_key_returns_none(self):
        raw = json.dumps({"question": "Q?", "options": ["A", "B", "C", "D"], "answer": "A"})
        # Missing "explanation"
        result = _parse_question(raw)
        assert result is None

    def test_options_must_have_exactly_4_items(self):
        result = _parse_question(_make_raw(options=["A", "B", "C"]))
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_question("")
        assert result is None

    def test_non_json_string_returns_none(self):
        result = _parse_question("This is not JSON at all.")
        assert result is None

    def test_options_coerced_to_strings(self):
        raw = json.dumps({
            "question": "What number?",
            "options": [1, 2, 3, 4],
            "answer": "A",
            "explanation": "It is 1.",
        })
        result = _parse_question(raw)
        assert result is not None
        assert all(isinstance(o, str) for o in result["options"])

    def test_json_with_surrounding_text(self):
        inner = json.dumps({
            "question": "Q?",
            "options": ["A", "B", "C", "D"],
            "answer": "A",
            "explanation": "Exp.",
        })
        raw = f"Here is the question:\n{inner}\nHope you enjoy!"
        result = _parse_question(raw)
        assert result is not None
