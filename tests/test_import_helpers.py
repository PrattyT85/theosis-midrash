import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from midrash_import import clean, flatten, prepare_records, ref_for  # noqa: E402


def test_clean_removes_footnotes_and_decodes_entities():
    value = '<b>Text</b>&nbsp;&amp; <i class="footnote">omit</i>&#x27;'
    assert clean(value) == "Text & '"


def test_flatten_preserves_nested_source_path():
    assert list(flatten({"0_Chapter": ["first", "second"]})) == [
        (("0_Chapter", "0"), "first"),
        (("0_Chapter", "1"), "second"),
    ]


def test_reference_rules_for_complex_works():
    assert ref_for(
        "Midrash Tanchuma",
        ("0_Bereshit", "1_Chapter", "2_Paragraph"),
        "ignored",
    ) == "Midrash Tanchuma, Bereshit 2:3"
    assert ref_for("Midrash Tehillim", ("4_Psalm", "2_Comment"), "") == "Midrash Tehillim 5:3"
    assert ref_for("Kohelet Rabbah", ("1_Parasha", "2_Chapter", "3_Comment"), "") == "Kohelet Rabbah 2:3:4"


def test_prepare_records_rejects_reference_collisions():
    with pytest.raises(ValueError, match="Reference collision"):
        prepare_records(
            "Demo",
            {
                "0_Chapter": {"0_Paragraph": "one"},
                "0_Section": {"0_Paragraph": "two"},
            },
        )


def test_prepare_records_returns_clean_text_and_paths():
    records = prepare_records(
        "Demo",
        {"0_Chapter": {"0_Paragraph": "<b>one</b>"}, "0_Section": {"1_Paragraph": "  two  "}},
    )
    assert records == [
        ("Demo 1:1", ("0_Chapter", "0_Paragraph"), "one"),
        ("Demo 1:2", ("0_Section", "1_Paragraph"), "two"),
    ]
