# -*- coding: utf-8 -*-
import json, os, re, time, requests, datetime
import sys
import pywikibot
from config import config_page_name  # pylint: disable=E0611,W0614
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from botutils.record import time_record
os.environ['PYWIKIBOT_DIR'] = os.path.dirname(os.path.realpath(__file__))
os.environ['TZ'] = 'UTC'
print('Starting at: ' + time.asctime(time.localtime(time.time())))
rec_time = datetime.datetime.now().__format__('%d/%m/%y %H:%M')

site = pywikibot.Site()
site.login()

config_page = pywikibot.Page(site, config_page_name)
cfg = config_page.text
cfg = json.loads(cfg)
print(json.dumps(cfg, indent=4, ensure_ascii=False))
op = False

if not cfg["enable"]:
    exit("disabled\n")

catpage = pywikibot.Category(site, "Category:可能违反方针的用户名")
for page in catpage.articles():
    if not re.search("User talk:", page.title()):
        continue
    if '/' in page.title():
        title = page.title()[:page.title().find('/')]
    else:
        title = page.title()
    session = requests.Session()
    print(title[10:], end='\t')
    params = {
        "action": "query",
        "list": "blocks",
        "bkusers": title[10:],
        "format": "json"
    }
    blockinfo = session.get(url="https://zh.wikipedia.org/w/api.php", params=params).json()
    if not blockinfo['query']['blocks'] or blockinfo['query']['blocks'][0]['expiry'] != "infinity" or "partial" in blockinfo['query']['blocks'][0]:
        print('not blocked')
        continue
    print('blocked')
    utpage = pywikibot.Page(site, page.title())
    template_text = "{{subst:uw-username|category=}}"
    text = utpage.text
    text = re.sub(r'\[\[Category:可能(违|違)反方(针|針)的用(户|戶)名(\|{{PAGENAME}}|)\]\]', '', text, flags=re.M)
    text = re.sub(r'\{\{Uw-username\}\}', template_text, text, flags=re.M)
    pywikibot.showDiff(utpage.text, text)
    utpage.text = text
    utpage.save(summary="[[Wikipedia:机器人/申请/Hamish-bot/4|T4]]：自動維護[[:Category:可能违反方针的用户名]]", minor=False)
    op = True
    print()

time_record(3, rec_time, op)

