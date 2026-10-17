#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import collections
import datetime
import json
import logging
import os
import re
import sys
import time
import pymysql
import requests

os.environ['PYWIKIBOT_DIR'] = os.path.dirname(os.path.realpath(__file__))
os.environ['TZ'] = 'UTC'
try:
    import pywikibot
except ImportError:
    pywikibot = None

try:
    from config import config_page_name  # pylint: disable=E0611,W0614
except ImportError:
    config_page_name = ''

sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

DFT_CFG = {
    "enable": True,
    "task_number": 14,
    "summary_prefix": "[[Wikipedia:机器人/申请/Hamish-bot/14|T14]]：",
    "main_page_name": "Wikipedia:優良條目評選/提名區",
    "archive_page_name": "Wikipedia:優良條目評選/存檔/{year}年/{month}月",
    "debug_archive_page_name": "User:{username}/GA/存档/{year}年/{month}月",
    "archive_page_preload": "{{存档页|Wikipedia:優良條目評選/提名區}}\n{{Wikipedia:優良條目評選/存檔}}",
    "archive_page_summary": "存檔{0}個優良條目評選討論",
    "task_page_name": "User:{username}/Task/{task_number}",
    "debug_task_page_name": "User:{username}/GA/Task/{task_number}",
    "toolforge_db_host": "tools.db.svc.wikimedia.cloud",
    "toolforge_db_name": "s53993__ga_archive_p",
    "toolforge_replica_cnf": "~/replica.my.cnf",
}
API_URL = "https://zh.wikipedia.org/w/api.php"
USER_AGENT = "HamishWikiBot/1.0 (https://zh.wikipedia.org/wiki/User_talk:Hamish)"
TEXT_NUMS = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
HEADINGS = {
    "提名區", "提名区",
    "待存档的评选", "正在进行的评选",
    "待存檔的評選", "正在進行的評選",
    "待存檔的提名", "投票中的提名",
}

HEADING_RE = re.compile(r'^(={2,5})\s*(.+?)\s*\1[ \t]*$', flags=re.M)
TPL_RE = re.compile(
    r'\{\{\s*(?:[Aa]rticle|[Aa]l|條目|条目|[Gg]ANentry)\s*\|\s*([^|}\n]+?)\s*(?:\|[^\n}]*)?\}\}'
)
TS_RE = re.compile(
    r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*(?:\([^)]*\)|（[^）]*）)?\s*(\d{1,2}):(\d{2})\s*\(UTC\)'
)
PERIOD_RE = re.compile(
    r'投票期\s*[：:]\s*'
    r'(\d{4}年\d{1,2}月\d{1,2}日\s*(?:\([^)]*\)|（[^）]*）)?\s*\d{1,2}:\d{2}\s*\(UTC\))'
    r'\s*至\s*'
    r'(\d{4}年\d{1,2}月\d{1,2}日\s*(?:\([^)]*\)|（[^）]*）)?\s*\d{1,2}:\d{2}\s*\(UTC\))'
)


def parse_timestamp(text):
    if not text:
        return None
    m = TS_RE.search(text)
    if not m:
        return None
    try:
        return datetime.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)),
            tzinfo=datetime.timezone.utc
        )
    except ValueError:
        return None


def iso_dt(iso_str):
    if not iso_str:
        return None
    return datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))


def dt_iso(dt):
    if not dt:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def normalize(title):
    if not title:
        return ""
    title = re.sub(r'[\u200e\u200f\u200b\ufeff]', '', title)
    title = re.sub(r'<!--[\s\S]*?-->', '', title)
    # -{...}-
    title = re.sub(r'-\{([^|}]+)\}-', r'\1', title)
    title = title.replace('_', ' ').strip()
    if title.startswith(':'):
        title = title[1:].strip()
    if title:
        title = title[0].upper() + title[1:]
    return title


class StateStore:
    def __init__(self, cfg):
        self.cfg = cfg
        self.data = {"last_processed_revid": 0, "nominations": {}}

    def load(self):
        conn = self._get_db_conn()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                self._ensure_tables(cur)
                cur.execute("SELECT * FROM gan_monitor")
                rows = cur.fetchall()
                noms = {}
                max_rev = 0
                for r in rows:
                    noms[r["nomination_id"]] = {
                        "nomination_id": r["nomination_id"],
                        "article_title": r["article_title"],
                        "section_heading": r["section_heading"],
                        "vote_start": r["vote_start"],
                        "vote_end": r["vote_end"],
                        "first_seen_revid": r["first_seen_revid"],
                        "first_seen_ts": r["first_seen_ts"],
                        "last_seen_revid": r["last_seen_revid"],
                        "last_seen_ts": r["last_seen_ts"],
                        "removed_revid": r["removed_revid"],
                        "removed_ts": r["removed_ts"],
                        "removed_user": r["removed_user"],
                        "last_seen_wikitext": r["last_seen_wikitext"],
                        "status": r["status"],
                        "talk_page": r["talk_page"],
                        "talk_oldid": r["talk_oldid"],
                        "archive_target_year": r["archive_target_year"],
                        "archive_target_month": r["archive_target_month"],
                    }
                    if r["last_seen_revid"] and r["last_seen_revid"] > max_rev:
                        max_rev = r["last_seen_revid"]
                self.data = {"last_processed_revid": max_rev, "nominations": noms}
        finally:
            conn.close()
        return self.data

    def save(self):
        conn = self._get_db_conn()
        try:
            with conn.cursor() as cur:
                self._ensure_tables(cur)
                sql = """
                INSERT INTO gan_monitor (
                    nomination_id, article_title, section_heading,
                    vote_start, vote_end,
                    first_seen_revid, first_seen_ts,
                    last_seen_revid, last_seen_ts,
                    removed_revid, removed_ts, removed_user,
                    last_seen_wikitext, status,
                    talk_page, talk_oldid,
                    archive_target_year, archive_target_month
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON DUPLICATE KEY UPDATE
                    article_title=VALUES(article_title),
                    section_heading=VALUES(section_heading),
                    vote_start=VALUES(vote_start),
                    vote_end=VALUES(vote_end),
                    last_seen_revid=VALUES(last_seen_revid),
                    last_seen_ts=VALUES(last_seen_ts),
                    removed_revid=VALUES(removed_revid),
                    removed_ts=VALUES(removed_ts),
                    removed_user=VALUES(removed_user),
                    last_seen_wikitext=VALUES(last_seen_wikitext),
                    status=VALUES(status),
                    talk_page=VALUES(talk_page),
                    talk_oldid=VALUES(talk_oldid),
                    archive_target_year=VALUES(archive_target_year),
                    archive_target_month=VALUES(archive_target_month)
                """
                for rec in self.data["nominations"].values():
                    cur.execute(sql, (
                        rec.get("nomination_id"),
                        rec.get("article_title"),
                        rec.get("section_heading"),
                        rec.get("vote_start"),
                        rec.get("vote_end"),
                        rec.get("first_seen_revid"),
                        rec.get("first_seen_ts"),
                        rec.get("last_seen_revid"),
                        rec.get("last_seen_ts"),
                        rec.get("removed_revid"),
                        rec.get("removed_ts"),
                        rec.get("removed_user"),
                        rec.get("last_seen_wikitext"),
                        rec.get("status"),
                        rec.get("talk_page"),
                        rec.get("talk_oldid"),
                        rec.get("archive_target_year"),
                        rec.get("archive_target_month"),
                    ))
            conn.commit()
        finally:
            conn.close()

    def _get_db_conn(self):
        replica_cnf = os.path.expanduser(self.cfg["toolforge_replica_cnf"])
        return pymysql.connect(
            read_default_file=replica_cnf,
            host=self.cfg["toolforge_db_host"],
            database=self.cfg["toolforge_db_name"],
            charset="utf8mb4"
        )

    @staticmethod
    def _ensure_tables(cur):
        cur.execute("""
        CREATE TABLE IF NOT EXISTS gan_monitor (
            nomination_id VARCHAR(255) PRIMARY KEY,
            article_title VARCHAR(255) NOT NULL,
            section_heading VARCHAR(255),
            vote_start VARCHAR(32),
            vote_end VARCHAR(32),
            first_seen_revid BIGINT,
            first_seen_ts VARCHAR(32),
            last_seen_revid BIGINT,
            last_seen_ts VARCHAR(32),
            removed_revid BIGINT,
            removed_ts VARCHAR(32),
            removed_user VARCHAR(255),
            last_seen_wikitext MEDIUMTEXT,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            talk_page VARCHAR(255),
            talk_oldid BIGINT,
            archive_target_year INT,
            archive_target_month INT,
            INDEX idx_status (status),
            INDEX idx_article (article_title)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)


def parse_page(wikitext, fallback_ts_iso=None):
    if not wikitext:
        return []

    matches = list(HEADING_RE.finditer(wikitext))
    if not matches:
        return []

    nomination_starts = []
    for idx, m in enumerate(matches):
        h_text = m.group(2).strip()
        if h_text in HEADINGS:
            continue
        next_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(wikitext)
        chunk = wikitext[m.end():next_pos]
        non_empty_lines = [l.strip() for l in chunk.split('\n') if l.strip()]
        head_preview = '\n'.join(non_empty_lines[:4])
        tpl_m = TPL_RE.search(head_preview)
        if tpl_m:
            nomination_starts.append((m.start(), m.end(), h_text, tpl_m.group(1)))

    results = []
    for i, (start_pos, h_end_pos, raw_heading, tpl_article) in enumerate(nomination_starts):
        end_pos = nomination_starts[i + 1][0] if i + 1 < len(nomination_starts) else len(wikitext)
        full_sec_text = wikitext[start_pos:end_pos].strip()
        body_text = wikitext[h_end_pos:end_pos].strip()

        for ch in HEADINGS:
            trail_pat = re.compile(rf'\n+={2,3}\s*{re.escape(ch)}\s*={2,3}\s*$')
            body_text = trail_pat.sub('', body_text).strip()

        article_title = normalize(tpl_article) or normalize(raw_heading)
        if not article_title:
            continue

        vote_start_dt = None
        vote_end_dt = None
        vp_m = PERIOD_RE.search(body_text)
        if vp_m:
            vote_start_dt = parse_timestamp(vp_m.group(1))
            vote_end_dt = parse_timestamp(vp_m.group(2))

        if not vote_start_dt:
            # Fallback
            first_ts_m = TS_RE.search(body_text)
            if first_ts_m:
                vote_start_dt = parse_timestamp(first_ts_m.group(0))
            elif fallback_ts_iso:
                vote_start_dt = iso_dt(fallback_ts_iso)

        if vote_start_dt and not vote_end_dt:
            vote_end_dt = vote_start_dt + datetime.timedelta(days=7)

        vote_start_iso = dt_iso(vote_start_dt)
        vote_end_iso = dt_iso(vote_end_dt)

        results.append({
            "article_title": article_title,
            "section_heading": raw_heading.strip(),
            "vote_start": vote_start_iso,
            "vote_end": vote_end_iso,
            "wikitext": body_text,
            "full_section": full_sec_text,
        })

    return results


def extract_div(text):
    boxes = []
    div_open_re = re.compile(
        r'<div\b[^>]*(?:background\s*:\s*#FFFFE7|mw-archivedtalk)[^>]*>',
        flags=re.I
    )
    tag_re = re.compile(r'</?div\b[^>]*>', flags=re.I)

    prev_box_end = 0
    for m in div_open_re.finditer(text):
        div_start = m.start()
        if div_start < prev_box_end:
            continue
        inner_start = m.end()
        depth = 1
        inner_end = len(text)
        box_end = len(text)
        for tm in tag_re.finditer(text, inner_start):
            tag_str = tm.group(0).lower()
            if tag_str.startswith('</div'):
                depth -= 1
                if depth == 0:
                    inner_end = tm.start()
                    box_end = tm.end()
                    break
            else:
                depth += 1

        pre_slice_start = max(prev_box_end, div_start - 1200)
        pre_slice = text[pre_slice_start:div_start]
        last_hd_end = 0
        for hm in re.finditer(r'^={2,5}[^=\n]+={2,5}[ \t]*$', pre_slice, flags=re.M):
            last_hd_end = hm.end()
        if last_hd_end > 0:
            pre_slice_start += last_hd_end
            pre_slice = text[pre_slice_start:div_start]

        header_line = ""
        full_start = div_start
        pm = re.search(
            r'(<p\b[^>]*>[\s\S]*?(?:移动自|移動自)[\s\S]*)$',
            pre_slice,
            flags=re.I
        )
        if pm:
            header_line = pm.group(1).strip()
            full_start = pre_slice_start + pm.start()
        else:
            im = re.search(
                r'((?:(?::?\'\'|<!--\s*)[^\n]*(?:移动自|移動自|Moved from|Save to)|\{\{\s*(?:移动自|移動自|Moved from|Save to)\b|(?:以下(?:内容|內容)(?:移动自|移動自)))[\s\S]*)$',
                pre_slice,
                flags=re.I
            )
            if im:
                header_line = im.group(1).strip()
                full_start = pre_slice_start + im.start()

        prev_box_end = box_end
        inner_content = text[inner_start:inner_end].strip()
        boxes.append({
            "header": header_line,
            "inner": inner_content,
            "raw": text[full_start:box_end].strip(),
        })
    return boxes


def extract_undived(text):
    sections = []
    headings = list(re.finditer(r'^(={2,3})\s*([^=\n]+?)\s*\1[ \t]*$', text, flags=re.M))
    for i, hm in enumerate(headings):
        h_title = hm.group(2).strip()
        if not re.search(r'(優良條目|优良条目|GA)', h_title, flags=re.I):
            continue
        sec_start = hm.end()
        sec_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sec_body = text[sec_start:sec_end].strip()
        # If has a <div> box, skip
        if re.search(r'<div\b[^>]*(?:background\s*:\s*#FFFFE7|mw-archivedtalk)', sec_body, flags=re.I):
            continue
        # Stop before {{DYKEntry/archive if no heading
        dyk_m = re.search(r'^\{\{\s*DYKEntry/archive', sec_body, flags=re.M | re.I)
        if dyk_m:
            sec_body = sec_body[:dyk_m.start()].strip()
        if TPL_RE.search(sec_body):
            raw_full = sec_body
            header_line = ""
            pm = re.search(
                r'^(<p\b[^>]*>[\s\S]*?(?:移动自|移動自)[\s\S]*?(?:</p>|\n(?=[^ \t\n])))',
                sec_body,
                flags=re.I
            )
            if pm:
                header_line = pm.group(1).strip()
                sec_body = sec_body[pm.end():].strip()
            else:
                lines = sec_body.split('\n')
                if lines and ('移动自' in lines[0] or '移動自' in lines[0]):
                    header_line = lines[0].strip()
                    sec_body = '\n'.join(lines[1:]).strip()
            sections.append({
                "header": header_line,
                "inner": sec_body,
                "raw": raw_full,
            })
    return sections


def extract_closetime(header_line, inner_text, fallback_ts_iso=None):
    close_dt = None

    if header_line:
        ts_matches = list(TS_RE.finditer(header_line))
        if ts_matches:
            close_dt = parse_timestamp(ts_matches[-1].group(0))

    if not close_dt and inner_text:
        tail_lines = [l.strip() for l in inner_text.split('\n') if l.strip()][-3:]
        tail_text = '\n'.join(tail_lines)
        gan_res_m = re.search(r'\{\{\s*GANresult\b[^}]*\|\s*sign\s*=\s*([^}]+)\}\}', tail_text, flags=re.I)
        if gan_res_m:
            ts_matches = list(TS_RE.finditer(gan_res_m.group(1)))
            if ts_matches:
                close_dt = parse_timestamp(ts_matches[-1].group(0))
        else:
            for line in reversed(tail_lines):
                if re.search(r'(入選|入选|落選|落选|未能入選|未達標準|未达标准|符合標準|符合标准|通過評選|通过评选|撤回|無效|无效|yesGA|noGA|Symbol_)', line):
                    ts_m = list(TS_RE.finditer(line))
                    if ts_m:
                        close_dt = parse_timestamp(ts_m[-1].group(0))
                        break

    if not close_dt and fallback_ts_iso:
        close_dt = iso_dt(fallback_ts_iso)

    return close_dt


class TalkArchiveFetcher:
    def __init__(self, site):
        self.site = site
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.page_cache = {}

    def api_get(self, params):
        params = dict(params, format="json", formatversion=2)
        params.setdefault("maxlag", 5)
        for attempt in range(6):
            try:
                r = self.session.get(API_URL, params=params, timeout=60)
                if r.status_code == 429:
                    wait_sec = int(r.headers.get("Retry-After", 5 + attempt * 5))
                    logging.warning(f"[api_get] MediaWiki 429 Too Many Requests, waiting {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue
                if r.status_code >= 500:
                    wait_sec = int(r.headers.get("Retry-After", 3 + attempt * 3))
                    logging.warning(f"[api_get] MediaWiki HTTP {r.status_code}, waiting {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue
                r.raise_for_status()

                data = r.json()
                if "error" in data:
                    err = data["error"]
                    code = err.get("code")
                    info = err.get("info", "")
                    if code == "maxlag":
                        wait_sec = int(r.headers.get("Retry-After", 5))
                        logging.warning(f"[api_get] MediaWiki maxlag: {info}, waiting {wait_sec}s...")
                        time.sleep(wait_sec)
                        continue
                    logging.warning(f"[api_get] MediaWiki API error [{code}]: {info}, retrying ({attempt + 1}/6)...")
                    time.sleep(3 + attempt * 3)
                    continue

                return data
            except Exception as e:
                logging.warning(f"[api_get] API GET retry {attempt + 1}: {e}")
                time.sleep(2 + attempt * 2)
        raise RuntimeError(f"Failed API request after 6 retries: {params}")

    def fetch_discussion(self, titles):
        to_fetch = [t for t in set(titles) if t not in self.page_cache]
        for i in range(0, len(to_fetch), 50):
            batch = to_fetch[i:i + 50]
            data = self.api_get({
                "action": "query",
                "prop": "revisions",
                "titles": "|".join(batch),
                "rvprop": "ids|timestamp|user|comment|content",
                "rvslots": "main",
                "redirects": 1,
                "converttitles": 1,
            })
            pages = data.get("query", {}).get("pages")
            if pages is None:
                raise RuntimeError(f"API query response missing 'query.pages': {data}")

            redirect_map = {rd["from"]: rd["to"] for rd in data.get("query", {}).get("redirects", [])}
            norm_map = {nm["from"]: nm["to"] for nm in data.get("query", {}).get("normalized", [])}
            conv_map = {cv["from"]: cv["to"] for cv in data.get("query", {}).get("converted", [])}

            by_title = {}
            for pg in pages:
                pg_title = pg.get("title")
                if not pg_title:
                    continue
                if pg.get("missing") or "revisions" not in pg or not pg.get("revisions"):
                    by_title[pg_title] = None
                else:
                    rv = pg["revisions"][0]
                    by_title[pg_title] = {
                        "title": pg_title,
                        "revid": rv["revid"],
                        "timestamp": rv["timestamp"],
                        "user": rv.get("user", ""),
                        "text": rv.get("slots", {}).get("main", {}).get("content", ""),
                    }

            for orig in batch:
                curr = norm_map.get(orig, orig)
                curr = conv_map.get(curr, curr)
                visited = set()
                while curr in redirect_map and curr not in visited:
                    visited.add(curr)
                    curr = redirect_map[curr]
                    curr = conv_map.get(curr, curr)
                if curr in by_title:
                    self.page_cache[orig] = by_title[curr]
                else:
                    logging.warning(f"[fetch_discussion] Title {orig} (resolved {curr}) not found in API response pages; not caching as None")

    def get_info(self, title):
        if title not in self.page_cache:
            self.fetch_discussion([title])
        return self.page_cache.get(title)

    def find_oldid(self, talk_title, start_iso, end_iso):
        data = self.api_get({
            "action": "query",
            "prop": "revisions",
            "titles": talk_title,
            "rvprop": "ids|timestamp|user|comment|size",
            "rvstart": start_iso,
            "rvend": end_iso,
            "rvdir": "newer",
            "rvlimit": 50,
            "redirects": 1,
        })
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None, None, None
        revs = pages[0].get("revisions", [])
        if not revs:
            return None, None, None

        best_rev = None
        prev_size = None
        for rv in revs:
            cmt = rv.get("comment") or ""
            sz = rv.get("size") or 0
            if any(k in cmt for k in ("優良", "优良", "評選", "评选", "候選", "候选", "GAN", "GAC", "存檔", "存档", "移動", "移动", "入選", "入选", "落選", "落选", "結果", "结果")):
                best_rev = rv
            elif prev_size is not None and (sz - prev_size) > 400:
                best_rev = rv
            prev_size = sz

        if not best_rev:
            best_rev = revs[-1]
        return best_rev["revid"], best_rev.get("user"), best_rev.get("timestamp")

    def find_candidate(self, text, rec):
        if not text:
            return None

        candidates = extract_div(text) + extract_undived(text)
        if not candidates:
            return None

        target_vs_dt = iso_dt(rec.get("vote_start"))
        last_revid = str(rec.get("last_seen_revid") or "")

        best_cand = None
        best_score = -1

        for cand in candidates:
            inner = cand["inner"]
            hdr = cand["header"]
            score = 0

            if last_revid and last_revid in hdr:
                score += 100

            cand_vs_dt = None
            vp_m = PERIOD_RE.search(inner)
            if vp_m:
                cand_vs_dt = parse_timestamp(vp_m.group(1))
            if not cand_vs_dt:
                first_ts_m = TS_RE.search(inner)
                if first_ts_m:
                    cand_vs_dt = parse_timestamp(first_ts_m.group(0))

            if target_vs_dt and cand_vs_dt:
                diff_hours = abs((cand_vs_dt - target_vs_dt).total_seconds()) / 3600.0
                if diff_hours < 0.1:
                    score += 90
                elif diff_hours <= 48:
                    score += 60 - diff_hours
                elif diff_hours <= 24 * 10:
                    score += 10
                else:
                    continue

            if score > best_score and score >= 10:
                best_score = score
                best_cand = cand

        return best_cand

    def find_moved(self, art_title):
        targets = []
        for query_title in (f"Talk:{art_title}", art_title):
            data = self.api_get({
                "action": "query",
                "list": "logevents",
                "letype": "move",
                "letitle": query_title,
                "lelimit": 10,
            })
            for ev in data.get("query", {}).get("logevents", []):
                target = ev.get("params", {}).get("target_title")
                if target:
                    t_talk = target if target.startswith("Talk:") else f"Talk:{target}"
                    if t_talk not in targets:
                        targets.append(t_talk)
        return targets

    def fetch_nomination(self, rec, allow_defer=False):
        art_title = rec["article_title"]
        talk_title = f"Talk:{art_title}"
        pg_info = self.get_info(talk_title)

        # redirect?
        if not pg_info:
            art_info = self.get_info(art_title)
            if art_info and art_info["title"] != art_title:
                alt_talk = f"Talk:{art_info['title']}"
                pg_info = self.get_info(alt_talk)

        matched_cand = None
        actual_talk_title = talk_title
        talk_latest_revid = None

        if pg_info:
            actual_talk_title = pg_info["title"]
            talk_latest_revid = pg_info["revid"]
            matched_cand = self.find_candidate(pg_info["text"], rec)

            if not matched_cand:
                subpage_links = set(re.findall(
                    r'(Talk:[^|\n}#\]]+/(?:存檔|存档|檔案|档案|優良條目|优良条目)[^|\n}#\]]*)',
                    pg_info["text"]
                ))
                for idx in (1, 2, 3):
                    subpage_links.add(f"{actual_talk_title}/存檔{idx}")
                for sub_t in sorted(subpage_links):
                    sub_info = self.get_info(sub_t)
                    if sub_info:
                        matched_cand = self.find_candidate(sub_info["text"], rec)
                        if matched_cand:
                            actual_talk_title = sub_info["title"]
                            talk_latest_revid = sub_info["revid"]
                            break

        if not matched_cand:
            for moved_talk in self.find_moved(art_title):
                m_info = self.get_info(moved_talk)
                if m_info:
                    matched_cand = self.find_candidate(m_info["text"], rec)
                    if matched_cand:
                        actual_talk_title = m_info["title"]
                        talk_latest_revid = m_info["revid"]
                        break

        removed_ts_iso = rec.get("removed_ts") or rec.get("last_seen_ts") or rec.get("vote_end")
        last_seen_ts_iso = rec.get("last_seen_ts") or rec.get("vote_start")

        if matched_cand:
            close_dt = extract_closetime(
                matched_cand["header"],
                matched_cand["inner"],
                fallback_ts_iso=removed_ts_iso
            )

            talk_oldid = None
            if last_seen_ts_iso and removed_ts_iso:
                start_dt = iso_dt(last_seen_ts_iso) - datetime.timedelta(hours=2)
                end_dt = iso_dt(removed_ts_iso) + datetime.timedelta(days=14)
                hist_oldid, hist_user, hist_ts = self.find_oldid(
                    actual_talk_title, dt_iso(start_dt), dt_iso(end_dt)
                )
                if hist_oldid:
                    talk_oldid = hist_oldid
                    if not close_dt and hist_ts:
                        close_dt = iso_dt(hist_ts)

            if not talk_oldid:
                talk_oldid = talk_latest_revid

            archive_dt = close_dt or iso_dt(removed_ts_iso) or iso_dt(rec.get("vote_end"))
            return {
                "found_on_talk": True,
                "article_title": art_title,
                "source_page": actual_talk_title,
                "oldid": talk_oldid,
                "raw_wikitext": matched_cand["raw"].strip(),
                "archive_dt": archive_dt,
                "vote_start": rec.get("vote_start"),
            }

        if allow_defer and removed_ts_iso:
            rem_dt = iso_dt(removed_ts_iso)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            if rem_dt and (now_dt - rem_dt).total_seconds() < 24 * 3600:
                logging.info(
                    f"[fetch_nomination] Talk archive for {art_title} not found yet and closed recently ({removed_ts_iso}); deferring."
                )
                return None

        # Fallback as use last_seen_wikitext from nomination page
        logging.info(f"[fetch_nomination] Talk archive not found for {art_title} ({rec.get('vote_start')}); fallback using nomination page oldid={rec.get('last_seen_revid')}")
        raw_nom = (rec.get("last_seen_wikitext") or "").strip()
        close_dt = extract_closetime(
            "",
            raw_nom,
            fallback_ts_iso=removed_ts_iso
        )
        archive_dt = close_dt or iso_dt(removed_ts_iso) or iso_dt(rec.get("vote_end"))
        return {
            "found_on_talk": False,
            "article_title": art_title,
            "source_page": "Wikipedia:優良條目評選/提名區",
            "oldid": rec.get("last_seen_revid"),
            "raw_wikitext": raw_nom,
            "archive_dt": archive_dt,
            "vote_start": rec.get("vote_start"),
        }


def archive_format(entry, heading_title=None):
    title = heading_title or entry["article_title"]
    source_page = entry["source_page"]
    oldid = entry["oldid"]
    raw = entry["raw_wikitext"].strip()

    move_tpl = f"{{{{移动自|1=Special:PermaLink/{oldid}{{{{!}}}}{source_page}|sign=~~~~}}}}"
    return f"== {title} ==\n{move_tpl}\n{raw}"


def same_nomination(vs1_iso, vs2_iso):
    if not vs1_iso or not vs2_iso:
        return True
    dt1 = iso_dt(vs1_iso)
    dt2 = iso_dt(vs2_iso)
    if not dt1 or not dt2:
        return True
    return abs((dt1 - dt2).total_seconds()) <= 86400 * 2


def save_month_archive(site, year, m_num, entries, cfg, debug=False, replace_months=False):
    if not entries:
        return False, []

    username = site.username() if site else "Hamish-bot"
    if debug:
        tpl = cfg.get("debug_archive_page_name", "User:{username}/GA/存档/{year}年/{month}月")
    else:
        tpl = cfg.get("archive_page_name", "Wikipedia:優良條目評選/存檔/{year}年/{month}月")

    target_title = tpl.format(username=username, year=year, month=m_num)
    existing_text = ""
    target_page = None

    if site is not None:
        target_page = pywikibot.Page(site, target_title)
        existing_text = target_page.text if target_page.exists() else ""

    preload = (cfg or DFT_CFG)["archive_page_preload"]

    if not existing_text or not existing_text.strip():
        header = preload
    else:
        hm = re.search(r'^={2,4}\s*[^=\n]+?\s*={2,4}[ \t]*$', existing_text, flags=re.M)
        if hm:
            header = existing_text[:hm.start()].strip()
        else:
            header = existing_text.strip()
        # Clean up any legacy year/month headings if present
        header = re.sub(r'\n+={2,3}\s*\d{1,4}(?:年|\s*月)\s*={2,3}\s*$', '', header).strip()
        if not header:
            header = preload

    if replace_months or not existing_text.strip():
        entries_sorted = sorted(
            entries,
            key=lambda e: (e["archive_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), e.get("vote_start") or "")
        )
        title_counts = collections.Counter(e["article_title"] for e in entries_sorted)
        seen_counts = collections.Counter()

        blocks = []
        for e in entries_sorted:
            base_title = e["article_title"]
            seen_counts[base_title] += 1
            if title_counts[base_title] > 1 and seen_counts[base_title] > 1:
                idx = seen_counts[base_title]
                ord_str = TEXT_NUMS[idx] if idx < len(TEXT_NUMS) else str(idx)
                h_title = f"{base_title}（第{ord_str}次）"
            else:
                h_title = base_title
            blocks.append(archive_format(e, heading_title=h_title))
        total_added = len(entries)
        new_page_text = f"{header}\n\n" + "\n\n".join(blocks) + "\n"
        to_add = entries
        already_in = []
    else:
        already_in = []
        to_add = []
        new_blocks = []
        for e in entries:
            permaLink = f"Special:PermaLink/{e['oldid']}{{{{!}}}}{e['source_page']}"
            if permaLink in existing_text and f"== {e['article_title']}" in existing_text:
                already_in.append(e)
                continue
            to_add.append(e)
            new_blocks.append(archive_format(e))
        if not to_add:
            logging.info(f"[save_month_archive] All {len(already_in)} entries already present in {target_title}; skipping edit")
            return False, already_in
        total_added = len(to_add)
        new_page_text = existing_text.rstrip() + "\n\n" + "\n\n".join(new_blocks) + "\n"

    if target_page is None or new_page_text == target_page.text:
        return False, already_in

    pywikibot.showDiff(target_page.text, new_page_text)
    target_page.text = new_page_text
    summary = cfg["summary_prefix"] + cfg["archive_page_summary"].format(total_added)
    logging.info(f"[save_month_archive] Saving {target_title} with summary: {summary}")
    try:
        target_page.save(summary=summary, minor=False)
        return True, already_in + to_add
    except Exception as exc:
        logging.error(f"[save_month_archive] Failed to save {target_title}: {exc}")
        return False, already_in


def save_archive(site, year, month_map, cfg, debug=False, replace_months=False):
    any_saved = False
    all_confirmed = []
    for m_num, entries in sorted(month_map.items()):
        if not entries:
            continue
        saved, confirmed = save_month_archive(
            site, year, m_num, entries, cfg,
            debug=debug, replace_months=replace_months
        )
        if saved:
            any_saved = True
        all_confirmed.extend(confirmed)
    return any_saved, all_confirmed


def update_task_page(site, cfg, store, debug=False):
    if site is None:
        return False
    username = site.username() if site else "Hamish-bot"
    tpl = cfg.get("debug_task_page_name") if debug else cfg.get("task_page_name")
    if not tpl:
        tpl = "User:{username}/GA/Task/{task_number}" if debug else "User:{username}/Task/{task_number}"
    task_num = cfg.get("task_number", 14)
    target_title = tpl.format(username=username, task_number=task_num)

    noms = [
        rec for rec in store.data["nominations"].values()
        if rec.get("status") in ("active", "pending")
    ]
    noms.sort(key=lambda r: (0 if r.get("status") == "active" else 1, r.get("first_seen_ts") or ""))

    lines = [
        '最後更新：~~~~~',
        'debug=1' if debug else 'debug=0',
        '',
        '{| class="wikitable sortable"',
        "! article_title !! first_seen_revid !! first_seen_ts !! status"
    ]

    if not noms:
        lines.append('|-\n| colspan="4" style="text-align:center;" | 星之內海。物見之臺。自樂園之端讓你諦聽。願諸君的故事滿載祝福。無罪之人儘管通過吧。')
    else:
        for r in noms:
            title = r.get("article_title") or ""
            revid = r.get("first_seen_revid")
            revid_str = f"[[Special:Diff/{revid}]]" if revid else ""
            ts = r.get("first_seen_ts") or ""
            status = r.get("status") or ""
            lines.append(f"|-\n| [[{title}]] || {revid_str} || {ts} || {status}")
    lines.append("|}\n")

    new_text = "\n".join(lines)
    target_page = pywikibot.Page(site, target_title)
    if target_page.exists() and target_page.text == new_text:
        logging.info(f"[update_task_page] {target_title} is up to date, skipping edit")
        return False

    summary = cfg["summary_prefix"] + f"更新任務監控列表（{len(noms)} 個項目）"
    logging.info(f"[update_task_page] Saving {target_title} with summary: {summary}")
    try:
        pywikibot.showDiff(target_page.text if target_page.exists() else "", new_text)
        target_page.text = new_text
        target_page.save(summary=summary, minor=False)
        return True
    except Exception as exc:
        logging.error(f"[update_task_page] Failed to save {target_title}: {exc}")
        return False


def main_watcher(site, cfg, store, debug=False):
    fetcher = TalkArchiveFetcher(site)
    if site is not None:
        nom_page = pywikibot.Page(site, cfg["main_page_name"])
        current_revid = nom_page.latest_revision_id
        current_ts = dt_iso(nom_page.latest_revision.timestamp)
        current_text = nom_page.text
    else:
        pg_info = fetcher.get_info(cfg["main_page_name"])
        current_revid = pg_info["revid"]
        current_ts = pg_info["timestamp"]
        current_text = pg_info["text"]

    current_noms = parse_page(current_text, fallback_ts_iso=current_ts)
    logging.info(f"[main_watcher] Current nomination page rev={current_revid} ({current_ts}): {len(current_noms)} active nominations")

    noms_db = store.data["nominations"]
    active_by_title = {
        rec["article_title"]: rec
        for rec in noms_db.values()
        if rec.get("status") in ("active", "pending")
    }

    seen_nom_ids = set()
    for item in current_noms:
        title = item["article_title"]
        vs = item["vote_start"] or current_ts
        rec = active_by_title.get(title)
        if rec and not same_nomination(rec.get("vote_start"), item.get("vote_start")):
            rec = None
        if not rec:
            for cand_rec in active_by_title.values():
                if cand_rec.get("vote_start") and cand_rec.get("vote_start") == vs and cand_rec["nomination_id"] not in seen_nom_ids:
                    rec = cand_rec
                    break

        if rec:
            rec["article_title"] = title
            rec["section_heading"] = item["section_heading"]
            if item["vote_start"]:
                rec["vote_start"] = item["vote_start"]
            if item["vote_end"]:
                rec["vote_end"] = item["vote_end"]
            rec["last_seen_revid"] = current_revid
            rec["last_seen_ts"] = current_ts
            rec["last_seen_wikitext"] = item["wikitext"]
            rec["status"] = "active"
            rec["removed_revid"] = None
            rec["removed_ts"] = None
            rec["removed_user"] = None
            seen_nom_ids.add(rec["nomination_id"])
        else:
            nom_id = f"{title}_{(vs or '')[:16]}"
            noms_db[nom_id] = {
                "nomination_id": nom_id,
                "article_title": title,
                "section_heading": item["section_heading"],
                "vote_start": item["vote_start"],
                "vote_end": item["vote_end"],
                "first_seen_revid": current_revid,
                "first_seen_ts": current_ts,
                "last_seen_revid": current_revid,
                "last_seen_ts": current_ts,
                "removed_revid": None,
                "removed_ts": None,
                "removed_user": None,
                "last_seen_wikitext": item["wikitext"],
                "status": "active",
                "talk_page": None,
                "talk_oldid": None,
                "archive_target_year": None,
                "archive_target_month": None,
            }
            seen_nom_ids.add(nom_id)

    removed_recs = [
        rec for rec in active_by_title.values()
        if rec["nomination_id"] not in seen_nom_ids
    ]

    op = False
    if removed_recs:
        logging.info(f"[main_watcher] Detected {len(removed_recs)} nominations removed from nomination page")
        try:
            fetcher.fetch_discussion([f"Talk:{r['article_title']}" for r in removed_recs])
        except Exception:
            logging.exception("[main_watcher] prefetch failed, will fetch individually")

        by_year_month = collections.defaultdict(lambda: collections.defaultdict(list))
        for rec in removed_recs:
            if not rec.get("removed_ts"):
                rec["removed_revid"] = current_revid
                rec["removed_ts"] = current_ts
            rec["status"] = "pending"
            try:
                entry = fetcher.fetch_nomination(rec, allow_defer=True)
            except Exception:
                logging.exception(f"[main_watcher] fetch_nomination failed for {rec['article_title']}")
                continue
            if not entry:
                logging.info(f"[main_watcher] Deferring archiving for {rec['article_title']} (waiting for talk page archive)")
                continue
            entry["rec"] = rec
            arc_dt = entry["archive_dt"] or iso_dt(current_ts)
            yr, mo = arc_dt.year, arc_dt.month
            by_year_month[yr][mo].append(entry)

        for yr, month_map in sorted(by_year_month.items()):
            saved, confirmed_entries = save_archive(
                site, yr, month_map, cfg, debug=debug, replace_months=False
            )
            if saved:
                op = True
            for entry in confirmed_entries:
                r = entry.get("rec")
                if r:
                    r["status"] = "archived"
                    r["talk_page"] = entry["source_page"]
                    r["talk_oldid"] = entry["oldid"]
                    arc_dt = entry["archive_dt"] or iso_dt(current_ts)
                    r["archive_target_year"] = arc_dt.year
                    r["archive_target_month"] = arc_dt.month

    store.data["last_processed_revid"] = current_revid
    store.save()
    update_task_page(site, cfg, store, debug=debug)
    return op


def nomination_history(fetcher):
    logging.info("[nomination_history] Querying full revision metadata of Wikipedia:優良條目評選/提名區 across all history...")

    params = {
        "action": "query",
        "prop": "revisions",
        "titles": "Wikipedia:優良條目評選/提名區",
        "rvprop": "ids|timestamp|user|comment|size",
        "rvlimit": "max",
        "rvdir": "newer",
    }
    all_meta = []
    while True:
        data = fetcher.api_get(params)
        pg = data["query"]["pages"][0]
        all_meta.extend(pg.get("revisions", []))
        if "continue" in data:
            params.update(data["continue"])
        else:
            break

    logging.info(f"[nomination_history] Fetched {len(all_meta)} revision metadata entries across page history")
    by_day = {}
    for r in all_meta:
        if (r.get("size") or 0) < 500:
            continue
        day_key = r["timestamp"][:10]
        by_day[day_key] = r

    sampled_meta = [by_day[k] for k in sorted(by_day)]
    sampled_ids = [r["revid"] for r in sampled_meta]
    logging.info(f"[nomination_history] Fetching content for {len(sampled_ids)} daily snapshots...")

    snapshots = []
    batch_size = 50
    for i in range(0, len(sampled_ids), batch_size):
        batch = sampled_ids[i:i + batch_size]
        data = fetcher.api_get({
            "action": "query",
            "prop": "revisions",
            "revids": "|".join(map(str, batch)),
            "rvprop": "ids|timestamp|user|comment|content",
            "rvslots": "main",
        })
        rev_map = {}
        for pg in data.get("query", {}).get("pages", []):
            for rv in pg.get("revisions", []):
                txt = rv.get("slots", {}).get("main", {}).get("content", "")
                rev_map[rv["revid"]] = {
                    "revid": rv["revid"],
                    "timestamp": rv["timestamp"],
                    "user": rv.get("user", ""),
                    "comment": rv.get("comment", ""),
                    "text": txt,
                }
        for rid in batch:
            if rid in rev_map:
                snapshots.append(rev_map[rid])

    return snapshots, all_meta


def removal_record(all_meta, last_seen_ts, removed_day_ts, article_title):
    cands = [
        r for r in all_meta
        if last_seen_ts < r["timestamp"] <= removed_day_ts
    ]
    if not cands:
        return None

    for r in cands:
        cmt = r.get("comment") or ""
        if article_title in cmt and any(k in cmt for k in ("選", "选", "存", "移", "結", "结", "維護", "维护", "archive", "Move", "GA")):
            return r
    for r in reversed(cands):
        cmt = r.get("comment") or ""
        if article_title in cmt:
            return r

    for r in cands:
        cmt = r.get("comment") or ""
        if any(k in cmt for k in ("投票結束", "維護清理", "维护清理", "移動", "移动", "archive", "入選", "入选", "未能入選", "落選")):
            return r

    return cands[-1]


def closed_rec(rec, all_meta, curr_ts, curr_revid, curr_user):
    rem_rev = removal_record(all_meta, rec["last_seen_ts"], curr_ts, rec["article_title"])
    if rem_rev:
        rec["removed_revid"] = rem_rev["revid"]
        rec["removed_ts"] = rem_rev["timestamp"]
        rec["removed_user"] = rem_rev.get("user", "")
        rem_idx = next((i for i, r in enumerate(all_meta) if r["revid"] == rem_rev["revid"]), None)
        if rem_idx and rem_idx > 0:
            rec["last_seen_revid"] = all_meta[rem_idx - 1]["revid"]
    else:
        rec["removed_revid"] = curr_revid
        rec["removed_ts"] = curr_ts
        rec["removed_user"] = curr_user


def backfill(site, cfg, store, start_year, end_year, debug=False, months_filter=None):
    fetcher = TalkArchiveFetcher(site)
    snapshots, all_meta = nomination_history(fetcher)
    if not snapshots:
        logging.warning("[backfill] No snapshots found for backfill range.")
        return False

    parsed_days = []
    for snap in snapshots:
        noms = parse_page(snap["text"], fallback_ts_iso=snap["timestamp"])
        parsed_days.append((snap, noms))

    active = {}
    closed_records = []

    for idx, (snap, noms) in enumerate(parsed_days):
        curr_ts = snap["timestamp"]
        curr_revid = snap["revid"]
        curr_titles = set()

        for item in noms:
            title = item["article_title"]
            vs = item["vote_start"] or curr_ts
            curr_titles.add(title)

            rec = active.get(title)
            if rec and not same_nomination(rec.get("vote_start"), item.get("vote_start")):
                old_rec = active.pop(title)
                closed_rec(old_rec, all_meta, curr_ts, curr_revid, snap.get("user", ""))
                closed_records.append(old_rec)
                rec = None

            if not rec:
                for old_title, cand_rec in list(active.items()):
                    if cand_rec.get("vote_start") and cand_rec.get("vote_start") == item["vote_start"] and old_title not in curr_titles:
                        rec = active.pop(old_title)
                        active[title] = rec
                        break

            if rec:
                rec["article_title"] = title
                rec["section_heading"] = item["section_heading"]
                if item["vote_start"]:
                    rec["vote_start"] = item["vote_start"]
                if item["vote_end"]:
                    rec["vote_end"] = item["vote_end"]
                rec["last_seen_revid"] = curr_revid
                rec["last_seen_ts"] = curr_ts
                rec["last_seen_wikitext"] = item["wikitext"]
            else:
                nom_id = f"{title}_{(vs or '')[:16]}"
                active[title] = {
                    "nomination_id": nom_id,
                    "article_title": title,
                    "section_heading": item["section_heading"],
                    "vote_start": item["vote_start"],
                    "vote_end": item["vote_end"],
                    "first_seen_revid": curr_revid,
                    "first_seen_ts": curr_ts,
                    "last_seen_revid": curr_revid,
                    "last_seen_ts": curr_ts,
                    "removed_revid": None,
                    "removed_ts": None,
                    "removed_user": None,
                    "last_seen_wikitext": item["wikitext"],
                    "status": "active",
                }

        future_map = collections.defaultdict(list)
        for f_idx in range(idx + 1, min(idx + 4, len(parsed_days))):
            for f_item in parsed_days[f_idx][1]:
                future_map[f_item["article_title"]].append(f_item.get("vote_start"))

        for title in list(active.keys()):
            if title not in curr_titles:
                rec = active[title]
                if any(same_nomination(rec.get("vote_start"), f_vs) for f_vs in future_map.get(title, [])):
                    continue
                active.pop(title)
                closed_rec(rec, all_meta, curr_ts, curr_revid, snap.get("user", ""))
                closed_records.append(rec)

    filtered_closed = []
    for rec in closed_records:
        rem_dt = iso_dt(rec["removed_ts"])
        if not rem_dt:
            continue
        if start_year <= rem_dt.year <= end_year:
            if months_filter and rem_dt.month not in months_filter:
                continue
            filtered_closed.append(rec)

    logging.info(f"[backfill] Identified {len(filtered_closed)} closed nominations in target range; prefetching Talk pages...")
    fetcher.fetch_discussion([f"Talk:{r['article_title']}" for r in filtered_closed])

    by_year_month = collections.defaultdict(lambda: collections.defaultdict(list))
    for i, rec in enumerate(filtered_closed, 1):
        entry = fetcher.fetch_nomination(rec, allow_defer=False)
        if not entry:
            continue
        entry["rec"] = rec
        arc_dt = entry["archive_dt"] or iso_dt(rec["removed_ts"])
        yr, mo = arc_dt.year, arc_dt.month
        if not (start_year <= yr <= end_year):
            continue
        if months_filter and mo not in months_filter:
            continue
        by_year_month[yr][mo].append(entry)
        if i % 25 == 0 or i == len(filtered_closed):
            logging.info(f"[backfill] Processed [{i}/{len(filtered_closed)}] talk archives")

    op = False
    for yr in range(start_year, end_year + 1):
        if yr in by_year_month:
            saved, confirmed_entries = save_archive(
                site, yr, by_year_month[yr], cfg, debug=debug, replace_months=True
            )
            if saved:
                op = True
            for entry in confirmed_entries:
                r = entry.get("rec")
                if r:
                    r["status"] = "archived"
                    r["talk_page"] = entry["source_page"]
                    r["talk_oldid"] = entry["oldid"]
                    arc_dt = entry["archive_dt"] or iso_dt(r["removed_ts"])
                    r["archive_target_year"] = arc_dt.year
                    r["archive_target_month"] = arc_dt.month
                    store.data["nominations"][r["nomination_id"]] = r

    store.save()
    return op


def main():
    parser = argparse.ArgumentParser(description="GAN Monitor and Monthly Archive Generator Bot")
    parser.add_argument("--debug", action="store_true", help="Output archive pages to User:<Bot>/GA/存档/<year>年/<month>月")
    parser.add_argument("--backfill", action="store_true", help="Run online historical backfill via MediaWiki API")
    parser.add_argument("--year", type=int, default=None, help="Backfill a single specific year (e.g. 2013)")
    parser.add_argument("--start-year", type=int, default=2013, help="Start year for backfill (default: 2013)")
    parser.add_argument("--end-year", type=int, default=datetime.datetime.now(datetime.timezone.utc).year, help="End year for backfill")
    parser.add_argument("--months", type=str, default=None, help="Optional comma-separated months to backfill (e.g. '3,4')")
    args = parser.parse_args()

    print('Starting at: ' + time.asctime(time.localtime(time.time())))
    rec_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')

    site = pywikibot.Site('zh', 'wikipedia')
    site.login()

    cfg = dict(DFT_CFG)
    if config_page_name and site is not None:
        config_page = pywikibot.Page(site, config_page_name)
        if config_page.exists() and config_page.text.strip():
            online_cfg = json.loads(config_page.text)
            cfg.update(online_cfg)
            print(json.dumps(cfg, indent=4, ensure_ascii=False))

    if not cfg.get("enable", True):
        exit("disabled\n")

    store = StateStore(cfg=cfg)
    store.load()

    months_filter = None
    if args.months:
        months_filter = {int(x.strip()) for x in args.months.split(",") if x.strip()}

    if args.backfill:
        s_yr = args.year if args.year else args.start_year
        e_yr = args.year if args.year else args.end_year
        op = backfill(
            site, cfg, store, s_yr, e_yr,
            debug=args.debug, months_filter=months_filter
        )
        update_task_page(site, cfg, store, debug=args.debug)
    else:
        op = main_watcher(site, cfg, store, debug=args.debug)

    if not args.debug:
        from botutils.record import time_record
        time_record(cfg.get("task_number", 14), rec_time, op)


if __name__ == "__main__":
    main()
