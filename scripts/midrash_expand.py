#!/usr/bin/env python3
"""Import the next bilingual Midrash corpus batch from Sefaria Export."""
from __future__ import annotations
import json
import psycopg2
from psycopg2.extras import Json
from midrash_config import database_url
from midrash_import import CORE, import_edition, ref_for, clean

EXT = {
    "Mekhilta DeRabbi Yishmael": {
        "hebrew_title": "מכילתא דרבי ישמעאל",
        "categories": ["Midrash", "Halakhah"], "corpus": "halakhic",
        "editions": [
            ("en", "Mechilta, translated by Rabbi Shraga Silverstein", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Mekhilta%20DeRabbi%20Yishmael/English/Mechilta%2C%20translated%20by%20Rabbi%20Shraga%20Silverstein.json"),
            ("he", "merged", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Mekhilta%20DeRabbi%20Yishmael/Hebrew/merged.json"),
        ],
    },
    "Mekhilta DeRabbi Shimon Ben Yochai": {
        "hebrew_title": "מכילתא דרבי שמעון בן יוחאי",
        "categories": ["Midrash", "Halakhah"], "corpus": "halakhic",
        "editions": [
            ("en", "Lauterbach", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Mekhilta%20DeRabbi%20Shimon%20Ben%20Yochai/English/Lauterbach.json"),
            ("he", "merged", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Mekhilta%20DeRabbi%20Shimon%20Ben%20Yochai/Hebrew/merged.json"),
        ],
    },
    "Sifra": {
        "hebrew_title": "ספרא",
        "categories": ["Midrash", "Halakhah"], "corpus": "halakhic",
        "editions": [
            ("en", "Sifra by Rabbi Shraga Silverstein", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Sifra/English/Sifra%20by%20Rabbi%20Shraga%20Silverstein.json"),
            ("he", "merged", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Sifra/Hebrew/merged.json"),
        ],
    },
    "Sifrei Bamidbar": {
        "hebrew_title": "ספרי במדבר",
        "categories": ["Midrash", "Halakhah"], "corpus": "halakhic",
        "editions": [
            ("en", "Sifrei by Rabbi Shraga Silverstein", "CC-BY", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Sifrei%20Bamidbar/English/Sifrei%20by%20Rabbi%20Shraga%20Silverstein.json"),
            ("he", "Wikisource", "CC-BY-SA", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Sifrei%20Bamidbar/Hebrew/Wikisource.json"),
        ],
    },
    "Sifrei Devarim": {
        "hebrew_title": "ספרי דברים",
        "categories": ["Midrash", "Halakhah"], "corpus": "halakhic",
        "editions": [
            ("en", "Trans. by Marty Jaffee, 2015", "CC-BY-NC", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Sifrei%20Devarim/English/Trans.%20by%20Marty%20Jaffee%2C%202015.json"),
            ("he", "merged", "Public Domain", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Sifrei%20Devarim/Hebrew/merged.json"),
        ],
    },
    "Pesikta DeRav Kahana": {
        "hebrew_title": "פסיקתא דרב כהנא",
        "categories": ["Midrash", "Aggadah"], "corpus": "aggadic",
        "editions": [
            ("en", "Sefaria Community Translation", "CC0", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Pesikta%20DeRav%20Kahana/English/Sefaria%20Community%20Translation.json"),
            ("he", "Pesikta de Rav Kahana according to an Oxford manuscript, Dov Mandelbaum ed., N.Y. 1987", "CC-BY", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Pesikta%20DeRav%20Kahana/Hebrew/Pesikta%20de%20Rav%20Kahana%20according%20to%20an%20Oxford%20manuscript%2C%20Dov%20Mandelbaum%20ed.%2C%20N.Y.%201987.json"),
        ],
    },
    "Pesikta Rabbati": {
        "hebrew_title": "פסיקתא רבתי",
        "categories": ["Midrash", "Aggadah"], "corpus": "aggadic",
        "editions": [
            ("en", "Sefaria Community Translation", "CC0", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Pesikta%20Rabbati/English/Sefaria%20Community%20Translation.json"),
            ("he", "merged", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Pesikta%20Rabbati/Hebrew/merged.json"),
        ],
    },
    "Midrash Tehillim": {
        "hebrew_title": "מדרש תהילים",
        "categories": ["Midrash", "Aggadah"], "corpus": "aggadic",
        "editions": [
            ("en", "Sefaria Community Translation", "CC0", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Tehillim/English/Sefaria%20Community%20Translation.json"),
            ("he", "OYW", "Public Domain", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Tehillim/Hebrew/OYW.json"),
        ],
    },
}


def main():
    with psycopg2.connect(database_url()) as conn:
        conn.set_client_encoding("UTF8")
        with conn.cursor() as cur:
            for title, meta in EXT.items():
                cur.execute("""
                    INSERT INTO works(sefaria_title, hebrew_title, categories, corpus, source_url)
                    VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(sefaria_title) DO UPDATE SET
                      hebrew_title=EXCLUDED.hebrew_title,
                      categories=EXCLUDED.categories,
                      corpus=EXCLUDED.corpus
                    RETURNING id
                """, (title, meta["hebrew_title"], meta["categories"], meta["corpus"],
                      "https://www.sefaria.org/" + title.replace(" ", "_")))
                work_id = cur.fetchone()[0]
                for edition in meta["editions"]:
                    import_edition(cur, work_id, title, *edition)
        conn.commit()
    print("Extended corpus import complete")


if __name__ == "__main__":
    main()
