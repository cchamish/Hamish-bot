# -*- coding: utf-8 -*-
import os
import re
import json
import time
import datetime


os.environ['PYWIKIBOT_DIR'] = os.path.dirname(os.path.realpath(__file__))
import pywikibot
from config import config_page_name  # pylint: disable=E0611,W0614


def time_record(oprt, t):
    user_page = pywikibot.Page(site, "User:Hamish-bot")
    user_page_text = user_page.text
    user_page_text = re.sub(r'<!-- T5rs -->(.*)<!-- T5re -->', '<!-- T2rs -->' + t + '<!-- T2re -->', user_page_text, flags=re.M)
    if oprt:
        user_page_text = re.sub(r'<!-- T5os -->(.*)<!-- T5oe -->', '<!-- T2os -->' + t + '<!-- T2oe -->', user_page_text, flags=re.M)
    pywikibot.showDiff(user_page.text, user_page_text)
    user_page.text = user_page_text
    user_page.save(summary="Updating task report", minor=False)


os.environ['TZ'] = 'UTC'
print('Starting at: ' + time.asctime(time.localtime(time.time())))
rec_time = datetime.datetime.now().__format__('%d/%m/%y %H:%M')

site = pywikibot.Site('zh', 'wikipedia')
site.login()

config_page = pywikibot.Page(site, config_page_name)
cfg = config_page.text
cfg = json.loads(cfg)
print(json.dumps(cfg, indent=4, ensure_ascii=False))

if not cfg["enable"]:
    exit("disabled\n")

today = datetime.datetime.now().__format__('%Y/%m/%d')
afdPagePrefix = 'Wikipedia:頁面存廢討論/記錄/'
count = 0
summary = "[[Wikipedia:机器人/申请/Hamish-bot/5|T5]]：自動清除存廢討論已完結頁面之冗餘內容"
pattern = re.compile(r'((== ?|=== ?)\[\[(:|))')

modifyDate = 0
op = False
while modifyDate < 61:
    op = False
    afdPage = pywikibot.Page(site, afdPagePrefix + (datetime.datetime.now() - datetime.timedelta(days=modifyDate)).__format__('%Y/%m/%d'))
    text = afdPage.text
    pageToProcess = len(pattern.findall(text))
    pageProcessed = text.count('{{delf}}')
    if pageToProcess == pageProcessed:
        op = True
        count += 1
        text = text.replace('\n__NOINDEX__', '__NOINDEX__')
        text = text.replace('\n<section begin=backlog />', '')
        text = text.replace('\n<section end=backlog />', '')
        text = text.replace('\n<!-- (讨论结束后删除本行|討論結束後刪除本行) --> ', '')
        pywikibot.showDiff(afdPage.text, text)
        afdPage.text = text
        afdPage.save(summary=summary, minor=True)
    print(afdPagePrefix + (datetime.datetime.now() - datetime.timedelta(days=modifyDate)).__format__('%Y/%m/%d'), end='\t')
    print(pageToProcess, end='\t')
    print(pageProcessed, end='\t')
    print('EDITED' if op else 'NOT EDITED')
    print()
    modifyDate += 1

if count == 0:
    time_record(op, rec_time)
    exit("nothing changed")

time_record(op, rec_time)
