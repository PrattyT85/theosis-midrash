#!/usr/bin/env python3
import psycopg2
from midrash_config import database_url
from midrash_import import ref_for

with psycopg2.connect(database_url(), options='-c client_encoding=UTF8') as conn:
    conn.set_client_encoding('UTF8')
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id,w.sefaria_title,s.section_path
            FROM segments s JOIN works w ON w.id=s.work_id
            WHERE w.sefaria_title IN ('Shir HaShirim Rabbah','Kohelet Rabbah')
        """)
        rows=cur.fetchall()
        for sid,title,path in rows:
            cur.execute('UPDATE segments SET sefaria_ref=%s WHERE id=%s',(ref_for(title,path,''),sid))
    conn.commit()
print('fixed',len(rows),'references')
