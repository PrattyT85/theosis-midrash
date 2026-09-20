#!/usr/bin/env python3
"""Download selected Sefaria Export editions and import them into midrash."""
from __future__ import annotations
import argparse, hashlib, html, json, os, re, urllib.request
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json

from midrash_config import database_url

BASE = "https://storage.googleapis.com/sefaria-export/"
EXPORT_AT = "2026-09-07T11:53:39Z"

CORE = {
 "Bereshit Rabbah": {
   "hebrew_title":"בראשית רבה", "categories":["Midrash","Aggadah","Midrash Rabbah"], "corpus":"aggadic",
   "editions":[
    ("en","The Sefaria Midrash Rabbah, 2022","CC-BY","https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Bereshit%20Rabbah/English/The%20Sefaria%20Midrash%20Rabbah%2C%202022.json"),
    ("he","merged","unknown","https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/Bereshit%20Rabbah/Hebrew/merged.json") ]},
 "Shemot Rabbah": {"hebrew_title":"שמות רבה","categories":["Midrash","Aggadah","Midrash Rabbah"],"corpus":"aggadic","editions":[]},
 "Vayikra Rabbah": {"hebrew_title":"ויקרא רבה","categories":["Midrash","Aggadah","Midrash Rabbah"],"corpus":"aggadic","editions":[]},
 "Bamidbar Rabbah": {"hebrew_title":"במדבר רבה","categories":["Midrash","Aggadah","Midrash Rabbah"],"corpus":"aggadic","editions":[]},
 "Devarim Rabbah": {"hebrew_title":"דברים רבה","categories":["Midrash","Aggadah","Midrash Rabbah"],"corpus":"aggadic","editions":[]},
 "Midrash Tanchuma": {"hebrew_title":"מדרש תנחומא","categories":["Midrash","Aggadah"],"corpus":"aggadic","editions":[
    ("en","Midrash Tanhuma-Yelammedenu, trans. Samuel A. Berman","CC-BY","https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Tanchuma/English/Midrash%20Tanhuma-Yelammedenu%2C%20trans.%20Samuel%20A.%20Berman.json"),
    ("he","merged","unknown","https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Midrash%20Tanchuma/Hebrew/merged.json")]},
 "Pirkei DeRabbi Eliezer": {"hebrew_title":"פרקי דרבי אליעזר","categories":["Midrash","Aggadah"],"corpus":"aggadic","editions":[
    ("en","Pirke de Rabbi Eliezer, trans. Rabbi Gerald Friedlander, London, 1916","Public Domain","https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Pirkei%20DeRabbi%20Eliezer/English/Pirke%20de%20Rabbi%20Eliezer%2C%20trans.%20Rabbi%20Gerald%20Friedlander%2C%20London%2C%201916.json"),
    ("he","Pirke DeRabbi Eliezer, Sefaria Vocalized Edition","Public Domain","https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Aggadah/Pirkei%20DeRabbi%20Eliezer/Hebrew/Pirke%20DeRabbi%20Eliezer%2C%20Sefaria%20Vocalized%20Edition.json")]}
}

# Fill missing Rabbah editions with stable Sefaria 2022/merged names.
for title, slug, he in [
 ("Shemot Rabbah","Shemot%20Rabbah","Shemot%20Rabbah"),("Vayikra Rabbah","Vayikra%20Rabbah","Vayikra%20Rabbah"),
 ("Bamidbar Rabbah","Bamidbar%20Rabbah","Bamidbar%20Rabbah"),("Devarim Rabbah","Devarim%20Rabbah","Devarim%20Rabbah")]:
 CORE[title]["editions"] = [
  ("en","The Sefaria Midrash Rabbah, 2022","CC-BY",f"{BASE}cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/{slug}/English/The%20Sefaria%20Midrash%20Rabbah%2C%202022.json"),
  ("he","merged","unknown",f"{BASE}cltk-flat/Midrash/Aggadah/Midrash%20Rabbah/{slug}/Hebrew/merged.json")]

def clean(s):
 s = html.unescape(s or "")
 s = re.sub(r'<i class="footnote">.*?</i>', "", s, flags=re.IGNORECASE | re.DOTALL)
 s = re.sub(r'<sup class="footnote-marker">.*?</sup>', "", s, flags=re.IGNORECASE | re.DOTALL)
 s = re.sub(r"<[^>]+>", "", s)
 return re.sub(r"\s+", " ", s).strip()

def flatten(obj, prefix=()):
 if isinstance(obj, dict):
  for key,val in obj.items():
   yield from flatten(val, prefix+(str(key),))
 elif isinstance(obj, list):
  for i,val in enumerate(obj): yield from flatten(val, prefix+(str(i),))
 elif isinstance(obj, str) and clean(obj): yield prefix, obj

def ref_for(title, path, meta):
 # cltk-flat stores a whole path in one key, e.g.
 # "0_Chapter, 14_Paragraph" or "0_Bereshit, 0_Siman, 0_Paragraph".
 # Numeric positions are 0-based in export; Sefaria refs are 1-based.
 components=[]
 for item in path:
  components.extend(part.strip() for part in item.split(","))
 parsed=[]
 for component in components:
  m=re.match(r"^(\d+)_(.*)$", component)
  if m:
   parsed.append((int(m.group(1))+1, m.group(2).strip()))
 if not parsed:
  return title
 nums=[index for index, _label in parsed]
 labels=[label for _index, label in parsed]
 if "Tanchuma" in title:
  parasha = labels[0] if labels else ""
  if len(nums) >= 3:
   return f"{title}, {parasha} {nums[1]}:{nums[2]}"
  return f"{title}, {parasha}" if parasha else title
 # Psalm comments use both the Psalm and comment numbers. Dropping the first
 # number here would collapse hundreds of comments into one row per Psalm.
 if title == "Midrash Tehillim" and len(nums) >= 2:
  return f"{title} {nums[0]}:{nums[1]}"
 # These Rabbah exports have a three-level Parasha/Chapter/Midrash path.
 # Retain all levels; omitting the parasha index causes collisions.
 if title in {"Shir HaShirim Rabbah", "Kohelet Rabbah"}:
  return f"{title} {':'.join(str(n) for n in nums)}"
 # Preserve the named node for other complex works and retain numeric levels.
 generic={"", "Chapter", "Paragraph", "Verse", "Section", "Comment", "Ot"}
 node=next((label for label in labels if label not in generic), "")
 suffix=nums[1:] if node else nums
 ref=f"{title}, {node} {':'.join(str(n) for n in suffix)}" if node else f"{title} {':'.join(str(n) for n in suffix)}"
 return ref.rstrip()

def prepare_records(title, text, meta=""):
 """Flatten an export and reject ambiguous generated references."""
 records = []
 seen_refs = {}
 for path, raw in flatten(text):
  ref=ref_for(title,path,meta)
  value=clean(raw)
  if not value:
   continue
  previous_path = seen_refs.get(ref)
  if previous_path is not None and previous_path != path:
   raise ValueError(
    f"Reference collision in {title}: {ref!r} "
    f"maps both {previous_path!r} and {path!r}"
   )
  seen_refs[ref] = path
  records.append((ref, path, value))
 return records


def refresh_primary_edition(cur, work_id):
 """Keep exactly one canonical edition per work, preferring English coverage."""
 cur.execute("""
  WITH ranked AS (
   SELECT id, row_number() OVER (
    ORDER BY
     CASE
      WHEN language='en' AND version_title ILIKE '%%Sefaria Community Translation%%' THEN 0
      WHEN language='en' THEN 1
      WHEN is_source THEN 2
      ELSE 3
     END,
     version_title, id
   ) AS rank
   FROM editions WHERE work_id=%s
  )
  UPDATE editions e SET is_primary=(ranked.rank=1)
  FROM ranked WHERE ranked.id=e.id
 """, (work_id,))


def import_edition(cur, work_id, title, lang, version, license, url):
 print("Downloading",title,lang,version)
 with urllib.request.urlopen(url, timeout=180) as response:
  payload = response.read()
 content_sha256 = hashlib.sha256(payload).hexdigest()
 data = json.loads(payload)
 text=data.get("text",{})
 if not isinstance(text,dict): raise ValueError(f"Expected cltk-flat dict text for {url}")

 # Store the source hash in edition metadata so rerunning an unchanged import is
 # safe and cheap, including against the current live schema. Existing databases
 # without a hash receive one on their next import.
 cur.execute("""SELECT id, metadata->>'content_sha256' FROM editions
  WHERE work_id=%s AND language=%s AND version_title=%s""", (work_id,lang,version))
 existing = cur.fetchone()
 if existing and existing[1] == content_sha256:
  cur.execute("SELECT count(*) FROM segments WHERE edition_id=%s", (existing[0],))
  count = cur.fetchone()[0]
  refresh_primary_edition(cur, work_id)
  cur.execute("""INSERT INTO ingestion_manifest(edition_id,work_title,language,version_title,source_url,export_generated_at,segment_count,content_sha256)
   VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(work_title,language,version_title)
   DO UPDATE SET edition_id=EXCLUDED.edition_id,segment_count=EXCLUDED.segment_count,content_sha256=EXCLUDED.content_sha256,imported_at=now()""",
   (existing[0],title,lang,version,url,EXPORT_AT,count,content_sha256))
  print("  unchanged; skipped",count,"segments")
  return count

 records = prepare_records(title, text, data.get("meta", ""))

 metadata = {
  "export_generated_at": EXPORT_AT,
  "format": "cltk-flat",
  "content_sha256": content_sha256,
  "source_bytes": len(payload),
  "source_export_url": url,
 }
 cur.execute("""INSERT INTO editions(work_id,language,version_title,version_source,license,is_source,is_primary,metadata)
  VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
  ON CONFLICT(work_id,language,version_title) DO UPDATE SET
    version_source=EXCLUDED.version_source, license=EXCLUDED.license,
    metadata=editions.metadata || EXCLUDED.metadata
  RETURNING id""",
  (work_id,lang,version,url,license,lang=="he",False,Json(metadata)))
 edition_id=cur.fetchone()[0]
 refresh_primary_edition(cur, work_id)
 cur.execute("DELETE FROM segments WHERE edition_id=%s",(edition_id,))
 for number, (ref, path, value) in enumerate(records, start=1):
  cur.execute("""INSERT INTO segments(work_id,edition_id,sefaria_ref,section_path,segment_number,text)
   VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(edition_id,sefaria_ref) DO UPDATE SET
   text=EXCLUDED.text,section_path=EXCLUDED.section_path,segment_number=EXCLUDED.segment_number""",
   (work_id,edition_id,ref,list(path),number,value))
 count = len(records)
 cur.execute("""INSERT INTO ingestion_manifest(edition_id,work_title,language,version_title,source_url,export_generated_at,segment_count,content_sha256)
  VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(work_title,language,version_title) DO UPDATE SET
  edition_id=EXCLUDED.edition_id,segment_count=EXCLUDED.segment_count,content_sha256=EXCLUDED.content_sha256,imported_at=now()""",
  (edition_id,title,lang,version,url,EXPORT_AT,count,content_sha256))
 print("  ",count,"segments; sha256",content_sha256[:12])
 return count

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--db",default=database_url()); ap.add_argument("--work",action="append",choices=list(CORE)); args=ap.parse_args()
 chosen=args.work or list(CORE)
 with psycopg2.connect(args.db) as conn:
  conn.set_client_encoding("UTF8")
  with conn.cursor() as cur:
   for title in chosen:
    meta=CORE[title]
    cur.execute("""INSERT INTO works(sefaria_title,hebrew_title,categories,corpus,source_url)
     VALUES(%s,%s,%s,%s,%s) ON CONFLICT(sefaria_title) DO UPDATE SET hebrew_title=EXCLUDED.hebrew_title,categories=EXCLUDED.categories RETURNING id""",
     (title,meta["hebrew_title"],meta["categories"],meta["corpus"],"https://www.sefaria.org/"+title.replace(" ","_")))
    work_id=cur.fetchone()[0]
    for ed in meta["editions"]: import_edition(cur,work_id,title,*ed)
  conn.commit()
 print("Import complete")
if __name__=="__main__": main()
