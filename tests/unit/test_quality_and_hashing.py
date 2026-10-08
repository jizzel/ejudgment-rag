import uuid

from ejudgment.ingestion.hashing import stable_id, stable_json_hash
from ejudgment.ingestion.quality import assess_text, is_viewer_boilerplate, strip_leading_navigation
from tests.fixtures.legacy_fixture import VIEWER_BOILERPLATE


def test_viewer_boilerplate_detected() -> None:
    assert is_viewer_boilerplate(VIEWER_BOILERPLATE)
    assert is_viewer_boilerplate("Skip to document content\nSearch")
    assert not is_viewer_boilerplate(None)


def test_judgment_mentioning_viewer_words_is_not_boilerplate() -> None:
    text = "Skip to document content\nSearch\nThe appellant said: Download PDF of the contract."
    assert not is_viewer_boilerplate(text)


def test_strip_leading_navigation_keeps_body_unchanged() -> None:
    body = "IN THE SUPREME COURT\nSearch warrants were issued."
    text, removed = strip_leading_navigation(f"Skip to document content\nSummary\nSearch\n{body}")
    assert removed
    assert text == body  # a body line that starts with "Search" is untouched
    assert strip_leading_navigation(body) == (body, False)


def test_assess_text_flags_without_dropping() -> None:
    assert assess_text("   ").flags == ["empty"]
    assert "mojibake" in assess_text("AFRICAN COMMISSION Â session").flags
    assert "replacement_characters" in assess_text("ab��" * 10).flags
    assert assess_text("A clean judgment.").flags == []


def test_stable_json_hash_ignores_key_order() -> None:
    assert stable_json_hash({"a": 1, "b": [1, 2]}) == stable_json_hash({"b": [1, 2], "a": 1})
    assert stable_json_hash({"a": 1}) != stable_json_hash({"a": 2})


def test_stable_id_is_deterministic() -> None:
    first = stable_id("judgment", "/akn/gh/judgment/ghasc/1963/1/eng@1963-06-17")
    assert first == stable_id("judgment", "/akn/gh/judgment/ghasc/1963/1/eng@1963-06-17")
    assert first.version == 5
    # Pinned: a change here means the ID namespace changed and every stored ID would move.
    assert first == uuid.UUID("28e6b7a3-66bc-5131-917a-82c1a37bcaa8")
    # Parts are separated, so ("ab", "c") and ("a", "bc") differ.
    assert stable_id("ab", "c") != stable_id("a", "bc")
