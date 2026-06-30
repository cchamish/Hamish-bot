# Forked from https://github.com/fossifer/WhitePhosphorus-bot/tree/master

import os
import sys
import time
import sched
import _thread
import datetime
from src import core, botsite, report, rcwatcher
from src.core import log, EditQueue, InteractiveTask

DEBUG = False

RESTART_TITLE = 'User:Hamish-bot/controls/restart'


def delta(h, m, s):
    utcnow = datetime.datetime.utcnow()
    start = datetime.datetime(utcnow.year, utcnow.month, utcnow.day, h, m, s)
    if start < utcnow:
        start += datetime.timedelta(days=1)
    return (start-utcnow).seconds


def periodic(scheduler, interval, priority, function, args=(), kwargs={}):
    scheduler.enter(interval, priority, periodic,
                    (scheduler, interval, priority, function),
                    {'args': args, 'kwargs':kwargs})
    function(*args, **kwargs)


def restart():
    log('Restart...')
    python = sys.executable
    os.execl(python, python, *sys.argv)
    exit(0)


def main(pwd):
    scheduler = sched.scheduler(timefunc=time.time, delayfunc=time.sleep)

    site = botsite.Site()
    site.client_login(pwd=pwd)

    watcher = rcwatcher.watcher()

    periodic(scheduler, 3, 1, core.main)
    periodic(scheduler, 3, 2, watcher.watch)
    _thread.start_new_thread(report.main, (rcwatcher.report_que, ))

    EditQueue().push(text='', summary='机器人重启完成', bot=True, minor=True,
                     title='User:Hamish-bot/controls/restart',
                     nocreate=True)

    def check_restart():
        if botsite.Site().get_text_by_title(RESTART_TITLE):
            restart()
    scheduler.enter(120, 999, periodic, (scheduler, 3, 999, check_restart))

    def check_bot():
        if not site.check_bot():
            log('Where is my bot flag?')
            site.client_login(pwd)
            if not site.check_bot():
                log('My bot flag has been revoked!')
                exit(0)
    scheduler.enter(900, 888, periodic, (scheduler, 900, 888, check_bot))

    try:
        scheduler.run()
    except KeyboardInterrupt:
        log('the main thread terminated because of KeyboardInterrupt')
        exit(0)


if __name__ == '__main__':
    main(sys.argv[1])