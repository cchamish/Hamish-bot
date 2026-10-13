# -*- coding: utf-8 -*-
import json
import hashlib
import os
import re
import sys
import time
import hashlib
import datetime
import pywikibot
from config import config_page_name  # pylint: disable=E0611,W0614

sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from botutils.record import time_record

os.environ['PYWIKIBOT_DIR'] = os.path.dirname(os.path.realpath(__file__))
os.environ['TZ'] = 'UTC'
print('Starting at: ' + time.asctime(time.localtime(time.time())))
rec_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')

site = pywikibot.Site("zh", "wikipedia")
site.login()

config_page = pywikibot.Page(site, config_page_name)
cfg = config_page.text
cfg = json.loads(cfg)
print(json.dumps(cfg, indent=4, ensure_ascii=False))
op = False

if not cfg["enable"]:
    exit("disabled\n")

summary_prefix = "[[Wikipedia:机器人/申请/Hamish-bot/3|T3]]："
rsnpage = pywikibot.Page(site, cfg["main_page_name"])
text = rsnpage.text

rndstr = hashlib.md5(str(time.time()).encode()).hexdigest()

text = re.sub(r'^(==[^=]+==)$', rndstr + r'\1', text, flags=re.M)
text = text.split(rndstr)

mainPageText = text[0].strip()
text = text[1:]

archivelist = {}
count = 0

for section in text:
    section = section.strip()
    if section == '':
        continue
    else:
        title = section.split('\n')[0]
        print(title, end="\t")

    processed = False
    publicizing = False

    notSave_pattern = r"\{\{(不存檔|不存档|Do not archive|DNA|请勿存档|請勿存檔)\}\}"
    moved_pattern = r"\{\{(moveto|Movedto|Moveto|Moved to|Switchto|移动到|已移动至|移動到|已移動至)"
    status_pattern = r"\{\{(S|s)tatus\|(.*)\}\}"
    try:
        status = "done" if re.findall(moved_pattern, section) else re.findall(status_pattern, section)[0][1]
        status = "not save" if re.findall(notSave_pattern, section) else re.findall(status_pattern, section)[0][1]
    except IndexError:
        print("status not found")
        section += "\n:{{ping|Hamish}}機械人無法識別此段落的狀態，請手動標記。--~~~~"
        mainPageText += '\n\n' + section
        print(mainPageText)
        continue
    print("status", status, end="\t")
    if status in cfg["publicizing_status"]:
        publicizing = True
        print("publicizing", end="\t")
    elif status in cfg["done_status"]:
        processed = True
        print("processed", end="\t")
    else:
        print("not processed", end="\t")

    lasttime = datetime.datetime(1, 1, 1)
    for m in re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日 \(.\) (\d{2}):(\d{2}) \(UTC\)", str(section)):
        d = datetime.datetime(int(m[0]), int(m[1]), int(m[2]), int(m[3]), int(m[4]))
        lasttime = max(lasttime, d)
    print(lasttime, end="\t")

    if (
        (
            (processed and not publicizing and time.time() - lasttime.timestamp() > cfg["time_to_live_for_processed"])
            or (not processed and not publicizing and time.time() - lasttime.timestamp() > cfg["time_to_live_for_not_processed"])
        )
            and lasttime != datetime.datetime(1, 1, 1))\
            and status != "not save":
        target = (lasttime.year, lasttime.month)
        if target not in archivelist:
            archivelist[target] = []
        archivelist[target].append(section)
        count += 1

        print("archive to " + str(target), end="\t")
    else:
        mainPageText += '\n\n' + section
        print("not archive", end="\t")
    print()

if count == 0:
    time_record(2, rec_time, op)
    print("nothing changed")
else:
    pywikibot.showDiff(rsnpage.text, mainPageText)
    rsnpage.text = mainPageText
    summary = cfg["main_page_summary"].format(count)
    print(summary)
    rsnpage.save(summary=summary_prefix + summary, minor=False)
    op = True

    for target in archivelist:
        archivepage = pywikibot.Page(site, cfg["archive_page_name"].format(target[0], target[1]))
        text = archivepage.text
        print(archivepage.title())
        if not archivepage.exists():
            text = cfg["archive_page_preload"]
        text += "\n\n" + "\n\n".join(archivelist[target])
        text = re.sub(r"{{status2\|(讨论|討論)中}}", "{{status2|-|已過時並存檔}}", text)
        pywikibot.showDiff(archivepage.text, text)
        archivepage.text = text
        summary = cfg["archive_page_summary"].format(len(archivelist[target]))
        print(summary)
        archivepage.save(summary=summary_prefix + summary, minor=False)

    time_record(2, rec_time, op)