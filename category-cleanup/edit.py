# ！/usr/bin/env python
# -*-coding:Utf-8 -*-
# Time: 18 Nov 2024 Mon 17:09
# Name: edit
# Author: CHAU SHING SHING HAMISH
import datetime

import pywikibot
import re
import os
import time
import toolforge

os.environ['TZ'] = 'UTC'
print('Starting at: ' + time.asctime(time.localtime(time.time())))
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

def time_record(t, op):
    user_page = pywikibot.Page(site, "User:Hamish-bot")
    user_page_text = user_page.text
    user_page_text = re.sub(r'<!-- T9rs -->(.*)<!-- T9re -->', '<!-- T9rs -->' + t + '<!-- T9re -->', user_page_text, flags=re.M)
    if op:
        user_page_text = re.sub(r'<!-- T9os -->(.*)<!-- T9oe -->', '<!-- T9os -->' + t + '<!-- T9oe -->', user_page_text, flags=re.M)
    pywikibot.showDiff(user_page.text, user_page_text)
    user_page.text = user_page_text
    user_page.save(summary = "Updating task report", minor = False)

def fetch_pages():
    try:
        conn = toolforge.connect('zhwiki_p')
        cursor = conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        # Display results
        for row in results:
            print(f"Page ID: {row[0]}, Title: {row[1].decode('utf-8')}")
        conn.close()
        return results
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    pages_to_remove = [page[1] for page in fetch_pages()]
    if not pages_to_remove:
        print('No pages to remove')
        time_record(str((datetime.datetime.now() + datetime.timedelta(hours=8)).__format__('%d/%m/%y %H:%M')), False)
        exit(0)
    for page in pages_to_remove:
        page = page.decode('utf-8')
        print(page)
        page = pywikibot.Page(site, page)
        text = page.text
        # Category is added by software so use full prefix, but need check
        text = re.sub(r'\[\[Category:用[条條]目[向嚮][导導][创創]建的草稿\]\]', '', text)
        pywikibot.showDiff(page.text, text)
        page.text = text
        page.save(summary='[[Wikipedia:机器人/申请/Hamish-bot/9|T9]]：從條目空間頁面中移除[[:Category:用条目向导创建的草稿]]', minor=False)
    time_record(str((datetime.datetime.now() + datetime.timedelta(hours=8)).__format__('%d/%m/%y %H:%M')), True)


