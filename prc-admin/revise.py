#!/usr/bin/env python
# -*-coding:Utf-8 -*-
# Time: 18 Jul 2025 23:01
# Name: revise
# Author: CHAU SHING SHING HAMISH

import argparse
import logging
import os
import pymysql
import pywikibot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_db_connection():
    replica_config_path = os.path.expanduser('~/replica.my.cnf')
    connection = pymysql.connect(
        read_default_file=replica_config_path,
        host='tools.db.svc.wikimedia.cloud',
        database='s53993__prc_admin_p',
        charset='utf8mb4'
    )
    logging.info("Toolforge database connection successful")
    return connection

def process_village_templates(start_code=None, start_index=1):
    connection = get_db_connection()
    try:
        cursor = connection.cursor()
        
        query = "SELECT full_code FROM admin_data_online WHERE RIGHT(full_code, 3) != '000'"
        params = []
        if start_code:
            query += " AND full_code >= %s"
            params.append(start_code)
        query += " ORDER BY full_code ASC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        site = pywikibot.Site('zh', 'wikipedia')
        site.login()
        
        deprecated_template = "<noinclude>{{Deprecated template|historical=yes|note=如需修改上級區劃，請參閱[[Wikipedia:机器人建立条目小组/中华人民共和国行政区划/wikidata|維護手冊]]修改維基數據相關實體，或前往[[WikiProject_talk:中国行政区划|專案頁面]]求助。|date=18 Jul 2025}}</noinclude>"
        
        offset = max(start_index - 1, 0)
        items_to_process = results[offset:] if not start_code else results
        total_count = len(items_to_process)
        
        logging.info(f"{total_count} villages to process")
        
        for i, (full_code,) in enumerate(items_to_process, start=start_index if not start_code else 1):
            page_title = f"Template:PRC admin/data/{full_code[:2]}/{full_code[2:4]}/{full_code[4:6]}/{full_code[6:9]}/{full_code[9:]}"
            page = pywikibot.Page(site, page_title)
            
            try:
                if page.exists():
                    current_text = page.text
                    if not current_text.startswith(deprecated_template):
                        new_text = deprecated_template + "\n" + current_text
                        page.text = new_text
                        page.save(summary="[[Wikipedia:机器人/申请/Hamish-bot/12|T12]]：PRC admin村級模板添加已棄用模板標記，基於[[Special:Permalink/88341043#村级模板data页和乡级模板list页清理|共識]]", minor=False)
                        logging.info(f"[{i}/{total_count}] Updated {page_title} (code: {full_code})")
                    else:
                        logging.info(f"[{i}/{total_count}] Skipped {page_title} (already has deprecated template)")
                else:
                    logging.warning(f"[{i}/{total_count}] Page does not exist: {page_title}")
            except Exception as e:
                logging.error(f"[{i}/{total_count}] Error processing {page_title}: {str(e)}")

    finally:
        connection.close()

def process_town_templates(start_code=None, start_index=1):
    connection = get_db_connection()
    try:
        cursor = connection.cursor()
        
        query = "SELECT full_code FROM admin_data_online WHERE RIGHT(full_code, 3) = '000' AND SUBSTRING(full_code, -6, 3) != '000'"
        params = []
        if start_code:
            query += " AND full_code >= %s"
            params.append(start_code)
        query += " ORDER BY full_code ASC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        site = pywikibot.Site('zh', 'wikipedia')
        site.login()
        
        replacement_content = "{{PRC admin/showlist/town}}"
        
        offset = max(start_index - 1, 0)
        items_to_process = results[offset:] if not start_code else results
        total_count = len(items_to_process)
        
        logging.info(f"Found {total_count} towns to process")
        
        for i, (full_code,) in enumerate(items_to_process, start=start_index if not start_code else 1):
            page_title = f"Template:PRC admin/list/{full_code[:2]}/{full_code[2:4]}/{full_code[4:6]}/{full_code[6:9]}/000"
            page = pywikibot.Page(site, page_title)
            
            try:
                if page.exists():
                    page.text = replacement_content
                    page.save(summary="[[Wikipedia:机器人/申请/Hamish-bot/12|T12]]：PRC admin鄉級模板更換顯示下級區劃模板，基於[[Special:Permalink/88341043#村级模板data页和乡级模板list页清理|共識]]", minor=False)
                    logging.info(f"[{i}/{total_count}] Replaced content for {page_title} (code: {full_code})")
            except Exception as e:
                logging.error(f"[{i}/{total_count}] Error processing {page_title}: {str(e)}")

    finally:
        connection.close()

def main():
    parser = argparse.ArgumentParser(description='Process PRC admin templates')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--village', action='store_true', help='Process village-level templates')
    group.add_argument('--town', action='store_true', help='Process town-level templates')
    
    parser.add_argument('--start-code', type=str, default=None, help='Start processing from this PRC admin code (inclusive)')
    
    args = parser.parse_args()
    
    if args.village:
        logging.info("Starting village template processing")
        process_village_templates(start_code=args.start_code, start_index=args.start_index)
        logging.info("Village template processing completed")
    elif args.town:
        logging.info("Starting town template processing")
        process_town_templates(start_code=args.start_code, start_index=args.start_index)
        logging.info("Town template processing completed")

if __name__ == "__main__":
    main()