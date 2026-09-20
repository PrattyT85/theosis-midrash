#!/usr/bin/env python3
"""Import six additional bilingual aggadic Midrash works."""
import psycopg2
from midrash_config import database_url
from midrash_import import import_edition

WORKS = {
    "Shir HaShirim Rabbah": ("שיר השירים רבה", "Midrash Rabbah", [
        ("en", "The Sefaria Midrash Rabbah, 2022", "CC-BY", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Shir%20HaShirim%20Rabbah/English/The%20Sefaria%20Midrash%20Rabbah%2C%202022.json"),
        ("he", "merged", "Mixed/see metadata", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Shir%20HaShirim%20Rabbah/Hebrew/merged.json")]),
    "Ruth Rabbah": ("רות רבה", "Midrash Rabbah", [
        ("en", "The Sefaria Midrash Rabbah, 2022", "CC-BY", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Ruth%20Rabbah/English/The%20Sefaria%20Midrash%20Rabbah%2C%202022.json"),
        ("he", "merged", "Mixed/see metadata", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Ruth%20Rabbah/Hebrew/merged.json")]),
    "Esther Rabbah": ("אסתר רבה", "Midrash Rabbah", [
        ("en", "The Sefaria Midrash Rabbah, 2022", "CC-BY", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Esther%20Rabbah/English/The%20Sefaria%20Midrash%20Rabbah%2C%202022.json"),
        ("he", "merged", "Mixed/see metadata", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Esther%20Rabbah/Hebrew/merged.json")]),
    "Kohelet Rabbah": ("קהלת רבה", "Midrash Rabbah", [
        ("en", "The Sefaria Midrash Rabbah, 2022", "CC-BY", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Kohelet%20Rabbah/English/The%20Sefaria%20Midrash%20Rabbah%2C%202022.json"),
        ("he", "merged", "Mixed/see metadata", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Kohelet%20Rabbah/Hebrew/merged.json")]),
    "Eikhah Rabbah": ("איכה רבה", "Midrash Rabbah", [
        ("en", "The Sefaria Midrash Rabbah, 2022", "CC-BY", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Eikhah%20Rabbah/English/The%20Sefaria%20Midrash%20Rabbah%2C%202022.json"),
        ("he", "merged", "Mixed/see metadata", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Eikhah%20Rabbah/Hebrew/merged.json")]),
    "Midrash Mishlei": ("מדרש משלי", "Aggadah", [
        ("en", "Sefaria Community Translation", "CC0", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Mishlei/English/Sefaria%20Community%20Translation.json"),
        ("he", "merged", "Mixed/see metadata", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Mishlei/Hebrew/merged.json")]),
}

with psycopg2.connect(database_url(), options="-c client_encoding=UTF8") as conn:
    conn.set_client_encoding("UTF8")
    with conn.cursor() as cur:
        for title, (hebrew, corpus, editions) in WORKS.items():
            cur.execute("""
                INSERT INTO works(sefaria_title,hebrew_title,categories,corpus,source_url)
                VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(sefaria_title) DO UPDATE SET hebrew_title=EXCLUDED.hebrew_title
                RETURNING id
            """, (title, hebrew, ["Midrash", "Aggadah", corpus], "aggadic", "https://www.sefaria.org/" + title.replace(" ", "_")))
            work_id = cur.fetchone()[0]
            for edition in editions:
                import_edition(cur, work_id, title, *edition)
    conn.commit()
print("Megillot and Midrash Mishlei import complete")
