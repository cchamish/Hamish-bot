import re

def time_record(task_nbr, t, op=True, only_op=False):
    user_page = pywikibot.Page(site, "User:Hamish-bot")
    user_page_text = user_page.text

    pattern = fr'^(\|\s*{task_nbr}\s*\|\|.+)$'
    match = re.search(pattern, user_page_text, re.MULTILINE)
    if not match:
        return

    old_row = match.group(1)
    
    cells = [c.strip() for c in old_row.split('||')]

    if only_op:
        cells[3] = t
    else:
        cells[2] = t
        if op:
            cells[3] = t

    new_row = " || ".join(cells)
    user_page_text = user_page_text.replace(old_row, new_row, 1)

    pywikibot.showDiff(user_page.text, user_page_text)
    user_page.text = user_page_text
    user_page.save(summary="更新任務報告", minor=False)