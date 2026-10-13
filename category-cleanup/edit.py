# ！/usr/bin/env python
# -*-coding:Utf-8 -*-
# Time: 18 Nov 2024 Mon 17:09
# Name: edit
# Author: CHAU SHING SHING HAMISH
import datetime
import sys
import pywikibot
import re
import os
import time
import toolforge
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from botutils.record import time_record

os.environ['TZ'] = 'UTC'
print('Starting at: ' + time.asctime(time.localtime(time.time())))
rec_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
site = pywikibot.Site('zh', 'wikipedia')
site.login()

conn = toolforge.connect('zhwiki_p')
query = """
SELECT page_id, page_title 
    FROM page 
    JOIN categorylinks ON page_id = cl_from 
    JOIN linktarget ON cl_target_id = lt_id 
    WHERE lt_title = '用条目向导创建的草稿' 
      AND lt_namespace = 14 
      AND page_namespace = 0;
"""


def fetch_pages():
    try:
        conn = toolforge.connect('zhwiki_p')
        cursor = conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        # Display results
        for row in results:
            print(f"Fetched ID: {row[0]}, Title: {row[1].decode('utf-8')}")
        conn.close()
        return results
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    pages_to_remove = [page[1] for page in fetch_pages()]
    if not pages_to_remove:
        print('No pages to remove')
        time_record(5, rec_time, False)
        exit(0)
    for page in pages_to_remove:
        page = page.decode('utf-8')
        print(f'Removing page: {page}')
        page = pywikibot.Page(site, page)
        text = page.text
        # Category is added by software so use full prefix, but need check
        text = re.sub(r'\[\[Category:用[条條]目[向嚮][导導][创創]建的草稿\]\]', '', text)
        pywikibot.showDiff(page.text, text)
        page.text = text
        page.save(summary='[[Wikipedia:机器人/申请/Hamish-bot/9|T9]]：從條目空間頁面中移除[[:Category:用条目向导创建的草稿]]', minor=False)
    time_record(5, rec_time, True)


