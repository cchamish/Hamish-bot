# ！/usr/bin/env python
# -*-coding:Utf-8 -*-
# Time: 15 Nov 2024 Fri 16:25
# Name: record
# Author: CHAU SHING SHING HAMISH

import pywikibot
import re

site = pywikibot.Site('zh', 'wikipedia')
site.login()

def time_record(task_nbr, t, op=True, only_op=False):
    user_page = pywikibot.Page(site, "User:Hamish-bot")
    user_page_text = user_page.text

    pattern = fr'(\|\s*{task_nbr}\s*\|\|.+?\|\|\s*(.+?)\s*\|\|\s*(.+?)\s*\|\|.+)'
    task_row = re.search(pattern, user_page_text)

    if not task_row:
        return

    old_row = task_row.group(0)
    run_time = task_row.group(2)
    op_time = task_row.group(3)

    new_row = old_row

    if only_op:
        new_row = new_row.replace(op_time, t, 1)
    else:
        new_row = new_row.replace(run_time, t, 1)
        if op:
            new_row = new_row.replace(op_time, t, 1)

    user_page_text = user_page_text.replace(old_row, new_row, 1)

    pywikibot.showDiff(user_page.text, user_page_text)
    user_page.text = user_page_text
    user_page.save(summary="更新任務報告", minor=False)