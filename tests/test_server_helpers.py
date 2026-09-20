import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from midrash_server import clean, clean_query, normalize_hebrew  # noqa: E402


def test_server_clean_decodes_numeric_entities_and_strips_escaped_markup():
    assert clean("<b>שלום</b>&nbsp;&#x27; &lt;i&gt;escaped&lt;/i&gt;") == "שלום ' escaped"


def test_normalize_hebrew_removes_marks_and_normalizes_final_letters():
    assert normalize_hebrew("מֶלֶךְ") == "מלכ"


def test_clean_query_removes_punctuation_but_keeps_hebrew():
    assert clean_query("Bereshit! בראשית?") == "Bereshit  בראשית"
