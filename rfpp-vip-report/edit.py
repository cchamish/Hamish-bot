# Time: 11 Oct 2026 15:22
# Name: edit.py
# Author: CHAU SHING SHING HAMISH
# Adopted from: https://github.com/fossifer/WhitePhosphorus-bot/tree/master/src
# exception.py botsite.py core.py rcwatcher.py report.py main.py
# SET ~/.pywikibot/user-password.py to store bot password

import re
import os
import sys
import time
import json
import queue
import requests
import datetime
import ipaddress
import threading
from heapq import heappush, heappop
from collections import namedtuple
from dateutil.relativedelta import relativedelta
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from botutils.record import time_record

SITE_DEBUG = False
DEBUG = False

BotPassword = namedtuple('BotPassword', 'login_name password')

RELEVANT_ACTIONS = {'block': ('block', 'reblock'),
                    'protect': ('protect', 'modify')}

class Error(Exception):
    def __init__(self, arg):
        self.message = arg

    def __str__(self):
        return repr(self.message)

# TODO: Warning: {'result': {'*': 'This result was truncated because it would
# otherwise be larger than the limit of 12,582,912 bytes.'}}

lang = 'zh'

if not SITE_DEBUG:
    lang_api = 'https://%s.wikipedia.org/w/api.php' % lang
    headers = {'User-Agent': "HamishWikiBot/1.0 (https://zh.wikipedia.org/w/"
               "User_talk:Hamish) BasedOnPython/3.13"}
    bot_name = 'Hamish-bot'
else:
    lang_api = 'https://%s.wikipedia.beta.wmflabs.org/w/api.php' % lang
    headers = {'User-Agent': 'Hamish-bot via Python 3.13'}
    bot_name = 'Hamish-bot'

comment_re = re.compile(r'<!--[\s\S]*?-->')

maxlag = 5


def get_summary(task, body):
    return '[[Wikipedia:机器人/申请/{name}/{task}|T{task}]]：'.format(
        name=bot_name, task=task) + body


def log(*args, time=True, sp='\n'):
    if time:
        print('[%s] ' % datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), end='', flush=True)
    for item in args:
        print(item, end=sp, flush=True)


def cur_timestamp():
    utcnow = str(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    return utcnow.replace(' ', 'T')[:19] + 'Z'


def singleton(cls, *args, **kwargs):
    instances = {}

    def _singleton(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    return _singleton


def check_csrf(f):
    def wrapper(*args, **kwargs):
        site = args[0]
        if not site.check_user():
            site.client_login()
            tmp = site.get_tokens('csrf')
            if not tmp:
                site.set_tokens('csrf', site.query_tokens('csrf').get('csrftoken'))
        return f(*args, **kwargs)
    return wrapper

def load_bot_password(username, family='wikipedia',
                      path='~/.pywikibot/user-password.py'):
    with open(os.path.expanduser(path), encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('('):
                continue
            try:
                entry = eval(line, {'__builtins__': {}, 'BotPassword': BotPassword})
            except Exception:
                continue
            scope, user, pwd = entry[:-2], entry[-2], entry[-1]
            if user != username or scope not in [(), (family,), (lang, family)]:
                continue
            if isinstance(pwd, BotPassword):
                return '%s@%s' % (user, pwd.login_name), pwd.password
            return user, pwd
    raise Error('No password entry for %s in %s' % (username, path))

@singleton
class Site:
    def __init__(self):
        self.s = requests.Session()
        self.tokens, self.status, self.ts = {}, '', ''
        self._tokens_l, self._status_l, self._ts_l = \
            (threading.Lock(),) * 3
        self.pwd = ''

    def get_tokens(self, key, default=None):
        with self._tokens_l:
            return self.tokens.get('key', default)

    def set_tokens(self, key, value):
        with self._tokens_l:
            self.tokens['key'] = value

    def get_status(self):
        with self._status_l:
            return self.status

    def set_status(self, value):
        with self._status_l:
            self.status = value

    def get_ts(self):
        with self._ts_l:
            return self.ts

    def set_ts(self, value):
        with self._ts_l:
            self.ts = value

    def api_get(self, req, target, interval=1):
        req['format'] = 'json'
        self.set_status('')
        try:
            result = self.s.get(lang_api, params=req, headers=headers).json()
        except:  # json.decoder.JSONDecodeError:
            log('api_get: Try again after %d sec...' % interval)
            time.sleep(interval)
            return self.api_get(req, target, interval * 2)
        if 'error' in result:
            code = result['error'].get('code', 'error')
            if code == 'maxlag':
                lag_str = result['error'].get('info', 'Maxlag Error')
                log(lag_str)
                lag_m = re.search(r'(\d+(\.\d+)?) seconds lagged.', lag_str)
                lag_sec = maxlag if lag_m is None else float(lag_m.group(1))
                log('api_get: Try again after %f sec...' % lag_sec)
                time.sleep(lag_sec)
                return self.api_get(req, target)
            log('api_get error!', req, target)
            raise Error(result['error'])
        if 'warnings' in result:
            log('api_get: Warning: %s' % result['warnings'], req, target)
        return result.get(target)

    def api_get_long(self, req, target, last_c='', interval=1):
        req['format'] = 'json'
        self.set_status('')
        last_cont = {'continue': last_c}
        while True:
            c_req = req.copy()
            c_req.update(last_cont)
            try:
                result = self.s.get(lang_api,
                                    params=c_req, headers=headers).json()
            except requests.exceptions.ConnectionError as error:
                log(error)
                log('api_get_long: Try again after %d sec...' % interval)
                time.sleep(interval)
                for t in self.api_get_long(req, target, last_cont['continue'],
                                           interval * 2):
                    yield t
                break
            if 'error' in result:
                code = result['error'].get('code', 'error')
                if code == 'maxlag':
                    lag_str = result['error'].get('info', 'Maxlag Error')
                    log(lag_str)
                    lag_m = re.search(r'(\d+(\.\d+)?) seconds lagged.', lag_str)
                    lag_sec = maxlag if lag_m is None else float(lag_m.group(1))
                    log('api_get_long: Try again after %f sec...' % lag_sec)
                    time.sleep(lag_sec)
                    for t in self.api_get_long(req, target, last_c=last_c):
                        yield t
                    break
                log(result)
                raise Error(result['error'])
            if 'warnings' in result:
                log('api_get_long: Warning:', result['warnings'])
            if target in result:
                yield result[target]
            if 'continue' not in result:
                break
            last_cont = result['continue']

    def api_post(self, data, interval=1, retry=False):
        data['format'], data['utf8'], data['maxlag'] = 'json', '1', maxlag
        self.set_status('')
        rst = None
        try:
            rst = self.s.post(lang_api, data=data, headers=headers).json()
        except:
            log('api_post: Try again after %d sec...' % interval)
            time.sleep(interval)
            return self.api_post(data, interval * 2)
        if 'error' in rst:
            code = rst['error'].get('code', 'error')
            if code == 'maxlag':
                lag_str = rst['error'].get('info', 'Maxlag Error')
                log(lag_str)
                lag_m = re.search(r'(\d+(\.\d+)?) seconds lagged.', lag_str)
                lag_sec = maxlag if lag_m is None else float(lag_m.group(1))
                log('api_post: Try again after %f sec...' % lag_sec)
                time.sleep(lag_sec)
                return self.api_post(data)
            elif code == 'badtoken':
                self.set_tokens('csrf', self.query_tokens('csrf'))
                if not retry:
                    self.api_post(data, interval=interval, retry=True)
                else:
                    log('Invalid token.')
            self.set_status(code)
        elif 'warnings' in rst:
            log('api_post: Warning:', rst['warnings'])
        return rst

    def query_tokens(self, type):
        req = {'type': type}
        req['meta'], req['action'] = 'tokens', 'query'
        return self.api_get(req, 'query').get('tokens')

    def check_user(self, interval=1):
        r = None
        try:
            r = self.s.get(lang_api + '?'
                           'action=query&format=json&assert=user').json()
        except requests.exceptions.ConnectionError as e:
            log('check_user: ConnectionError, try again after %d sec...' % interval)
            time.sleep(interval)
            return self.check_user(interval * 2)
        return 'error' not in r

    def client_login(self):
        lgname, lgpassword = load_bot_password(bot_name)
        data = {'action': 'login',
                'lgname': lgname,
                'lgpassword': lgpassword,
                'lgtoken': self.query_tokens('login')['logintoken']}

        result = self.api_post(data).get('login', {})

        if result.get('result') == 'Success':
            self.set_tokens('csrf', self.query_tokens('csrf').get('csrftoken'))
            return None
        raise Error(result.get('reason', 'Login Failed'))

    def get_text_by_title(self, title, detect_flow=False, ts=False):
        req = {'action': 'query', 'titles': title,
               'rvprop': 'content|timestamp'}
        req['prop'] = 'revisions|info' if detect_flow else 'revisions'
        r = self.api_get(req, 'query')['pages']
        for k, v in r.items():
            try:
                if ts:
                    self.set_ts(v['revisions'][0]['timestamp'])
                if detect_flow:
                    return [v['revisions'][0]['*'],
                            v['contentmodel'] == 'flow-board']
                return v['revisions'][0]['*']
            except:
                self.set_ts('')
                if detect_flow:
                    return ['', False]
                return ''

    def get_text_by_id(self, pageid):
        req = {'action': 'query', 'pageids': pageid,
               'prop': 'revisions', 'rvprop': 'content|timestamp'}
        r = self.api_get(req, 'query')['pages']
        temp = r.get(pageid, '')
        # TODO: missing
        self.set_ts(temp['revisions'][0]['timestamp'] if temp else '')
        return temp['revisions'][0]['*'] if temp else ''

    @check_csrf
    def ex_edit(self, **kwargs):
        op_type = kwargs.pop('op_type', None)
        operator = kwargs.pop('operator', None)
        target = kwargs.pop('target', None)
        op_ts = kwargs.pop('op_timestamp', None)

        title, pageid = kwargs.get('title'), kwargs.get('pageid')
        content = kwargs.get('text')
        if (title is None) == (pageid is None):
            # invalid parameters
            return None
        if callable(content):
            # A function which can generate new content.
            if title:
                text = self.get_text_by_title(title, ts=True)
            else:
                text = self.get_text_by_id(pageid)
            kwargs['basetimestamp'] = kwargs.get('basetimestamp') or self.ts
            result = content(text)
            if isinstance(result, dict):
                content = result.get('text', '')
                kwargs['summary'] = kwargs.get('summary') or result.get('summary', '')
            elif isinstance(result, str):
                content = result
            else:
                return None
        kwargs['starttimestamp'] = kwargs.get('starttimestamp') or kwargs.get('basetimestamp') or cur_timestamp()
        kwargs['text'] = content
        kwargs['action'] = 'edit'
        kwargs['token'] = self.get_tokens('csrf')

        rst = self.api_post(kwargs)

        if rst.get('edit', {}).get('result') == 'Success':
            if 'nochange' in rst['edit']:
                self.set_status('nochange')
            else:
                self.set_status('')
                
                reported_at = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                if operator and op_type:
                    log(f"[{title or pageid}] Reported {target} by {operator} at {op_ts} (posted at {reported_at})")
                else:
                    log(f"Successfully edited: {title or pageid} | summary: {kwargs.get('summary', '')}")

                if kwargs.get('title') != f'User:{bot_name}':
                    if time_record:
                        try:
                            now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
                            time_record(7, now_str, only_op=True)
                        except Exception as e:
                            log(f"time_record error: {e}")
        else:
            log(f"Error: Page not saved for title: {title} / pageid: {pageid}")
            log(json.dumps(rst, indent=4, sort_keys=True))
            if rst.get('edit', {}).get('captcha'):
                word = input('Input the captcha listed above: ')
                kwargs['captchaid'] = rst['edit']['captcha'].get('id')
                kwargs['captchaword'] = word
                self.ex_edit(**kwargs)
            elif rst.get('edit', {}).get('abusefilter', {}).get('id'):
                afid = rst['edit']['abusefilter']['id']
                self.set_status('abusefilter #%d' % afid)
                log('Hit abusefilter #%d!' % afid)
                if 'info' in rst['edit']:
                    log(rst['edit']['info'])
            elif 'error' not in rst:
                self.set_status(json.dumps(rst))

class Timestamp:
    def __init__(self, **kwargs):
        if kwargs.get('ts_str'):
            self.str = kwargs['ts_str']
            self.ts = datetime.datetime.strptime(self.str, '%Y-%m-%dT%H:%M:%SZ')
        elif kwargs.get('ts_obj'):
            self.str = kwargs['ts_obj'].strftime('%Y-%m-%dT%H:%M:%SZ')
            self.ts = kwargs['ts_obj']
        else:
            raise TypeError('neither ts_str nor ts_obj is specified')

    def __str__(self):
        return self.str

    def strftime(self, fmt):
        return self.ts.strftime(fmt)

    # TODO: __repr__

    def __int__(self):
        return time.mktime(self.ts.timetuple())

    def __ne__(self, other):
        if isinstance(other, Timestamp):
            return self.ts != other.ts

    def __eq__(self, other):
        if isinstance(other, Timestamp):
            return self.ts == other.ts

    def __lt__(self, other):
        if isinstance(other, Timestamp):
            return self.ts < other.ts

    def __gt__(self, other):
        if isinstance(other, Timestamp):
            return self.ts > other.ts

    def __le__(self, other):
        if isinstance(other, Timestamp):
            return self.ts <= other.ts

    def __ge__(self, other):
        if isinstance(other, Timestamp):
            return self.ts >= other.ts

    def __add__(self, other):
        if isinstance(other, datetime.timedelta):
            return Timestamp(ts_obj=self.ts + other)

    def __sub__(self, other):
        if isinstance(other, datetime.timedelta):
            return Timestamp(ts_obj=self.ts - other)
        elif isinstance(other, Timestamp):
            return self.ts - other.ts


def now():
    return Timestamp(ts_obj=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))

_disabled_logged = {}
def check_core(task_name):
    if task_name is None:
        return True
    jsontitle = 'User:%s/T%s.json' % (bot_name, task_name)
    text = (Site().get_text_by_title(jsontitle) or '').strip()
    if not text:
        enabled = True
    else:
        try:
            conf = json.loads(text)
            enabled = isinstance(conf, dict) and bool(conf.get('enabled', False))
        except ValueError:
            enabled = False
    if enabled:
        _disabled_logged.pop(task_name, None)
    elif not _disabled_logged.get(task_name):
        _disabled_logged[task_name] = True
        log('[check] task %s is disabled by %s' % (task_name, jsontitle))
    return enabled


def check(task_name):
    def _wrapper(func, *args, **kwargs):
        def _check(*args, **kwargs):
            if check_core(task_name):
                return func(*args, **kwargs)
            else:
                log(f"[check] Execution of '{func.__name__}' skipped due to disabled task '{task_name}'.")
                return None
        return _check
    return _wrapper


class Revision:
    def __init__(self, **kwargs):
        self.task = kwargs.pop('task', None)
        self.ts = kwargs.pop('ts', now())
        self.loop = kwargs.pop('loop', None)
        self.options = kwargs
        self.title = kwargs.get('title', '')
        self.text = kwargs.get('text', '')
        self.summary = kwargs.get('summary', '')
        self.basetimestamp = kwargs.get('basetimestamp')

    def __str__(self):
        return vars(self).__str__()

    def __repr__(self):
        return 'Revision(%s)' % ', '.join(['%s=%s' % (k, v) for k, v in vars(self).items()])

    def __lt__(self, other):
        if isinstance(other, Revision):
            return self.ts < other.ts

    def __gt__(self, other):
        if isinstance(other, Revision):
            return self.ts > other.ts

    def __le__(self, other):
        if isinstance(other, Revision):
            return self.ts <= other.ts

    def __ge__(self, other):
        if isinstance(other, Revision):
            return self.ts >= other.ts


@singleton
class EditQueue:
    def __init__(self):
        self.lock = threading.Lock()
        self.heap = []

    def __len__(self):
        return len(self.heap)

    def push(self, **kwargs):
        with self.lock:
            rev = Revision(**kwargs)
            heappush(self.heap, rev)

    def peek(self):
        with self.lock:
            if len(self.heap):
                return self.heap[0]

    def pop(self):
        with self.lock:
            if len(self.heap):
                ret = heappop(self.heap)
                if ret.loop:
                    para = vars(ret)
                    para['ts'] = now() + ret.loop
                    heappush(self.heap, Revision(**para))
                return ret


def process_edit_queue():
    site = Site()
    que = EditQueue()
    if len(que) and que.peek().ts < now():
        rev = que.pop()
        if check_core(rev.task):
            site.ex_edit(**rev.options)


rcprop = 'user|userid|timestamp|title|ids|comment|loginfo'
rctype = 'edit|new|log'
rcnamespace = '*'

report_que = queue.Queue()


def rc_generator(rcstart):
    site = Site()
    for rc in site.api_get_long({'action': 'query', 'list': 'recentchanges',
                                 'rcstart': rcstart, 'rcdir': 'newer',
                                 'rcnamespace': rcnamespace, 'rctype': rctype,
                                 'rcprop': rcprop, 'rclimit': 'max'}, 'query'):
        if not rc['recentchanges']:
            return
        for change in rc['recentchanges']:
            yield change


from collections import deque

class watcher:
    def __init__(self, seconds=14400):
        self.last_ts = now() - datetime.timedelta(seconds=seconds)
        self.seen_rcids = set()
        self.seen_queue = deque(maxlen=5000)

    def watch(self):
        new_items_count = 0
        captured_actions = []

        for change in rc_generator(self.last_ts):
            rcid = change.get('rcid', 0)
            
            if rcid in self.seen_rcids:
                continue

            self.seen_rcids.add(rcid)
            self.seen_queue.append(rcid)
            if len(self.seen_rcids) > 5000:
                self.seen_rcids = set(self.seen_queue)

            self.last_ts = change.get('timestamp', self.last_ts)
            new_items_count += 1

            if (change.get('type') == 'log'
                    and change.get('logaction') in RELEVANT_ACTIONS.get(change.get('logtype'), ())):
                action_desc = f"{change['logtype']} on {change.get('title')} by {change.get('user')}"
                captured_actions.append(action_desc)
                log(f"[Watcher] Captured event: {action_desc} at {change.get('timestamp')}")
                report_que.put(change)

        if captured_actions:
            log(f"[Watcher] Polled {new_items_count} RC entries, queued {len(captured_actions)} action(s).")
        elif DEBUG:
            log(f"[Watcher] Polled {new_items_count} RC entries, 0 relevant actions.")

DELAY = 180
LONG_SLEEP = 120
SHORT_SLEEP = 5

VIP = 'Wikipedia:当前的破坏'
RFP = 'Wikipedia:请求保护页面'

# TODO: Do not use '?:', use group name instead
vandal_re = re.compile(r'(?<!=)==\s*(.*?)\s*==(?!=)')
result_re = re.compile(r'^[*:;#]+\s*[处處]理\s*[:：]\s*(.*?)\s*$')
protect_re = re.compile(r'===\s*\[\[:?(.*?)(?:\|.*?)?\]\]\s*===')
unprotect_re = re.compile(r'==\s*[请請]求解除保[护護]\s*==')
ts_re = re.compile(r'\d{4}年\d{1,2}月\d{1,2}日 \([日一二三四五六]\)'
                   r' \d{2}:\d{2} \(UTC\)')

pt_dict = {'sysop': 'f', 'autoconfirmed': 's', 'move': 'm', 'create': 't',
           'extendedconfirmed': 'e', 'templateeditor': 'tp'}


# approx works only when tostr is True,
# set it to True when an approx result is needed
def ts_delta(ts, ots, tostr=True, approx=True):
    # "expiry": "infinite" for protection
    # "duration": "indefinite" for block
    if ts in ['infinite', 'indefinite', 'infinity']:
        return 'indef'
    dt = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ')
    odt = datetime.datetime.strptime(ots, '%Y-%m-%dT%H:%M:%SZ')
    total_seconds = (dt - odt).total_seconds()
    if not tostr:
        return total_seconds

    delta = None
    if approx:
        seconds = 0
        if total_seconds < 86400:
            # accurate to a minute
            seconds = (total_seconds // 30 + (total_seconds // 30 % 2)) * 30
        elif total_seconds < 5184000:
            # accurate to an hour
            seconds = (total_seconds // 1800 + (total_seconds // 1800 % 2)) * 1800
        else:
            # accurate to a day
            seconds = (total_seconds // 43200 + (total_seconds // 43200 % 2)) * 43200
        delta = relativedelta(odt + datetime.timedelta(seconds=seconds), odt)
    else:
        delta = relativedelta(dt, odt)

    ret = ''
    if delta.years:
        ret += '%d年' % delta.years
    if delta.months:
        ret += '%d个月' % delta.months
    if delta.days:
        ret += '%d天' % delta.days
    if delta.hours:
        ret += '%d小时' % delta.hours
    if delta.minutes:
        ret += '%d分' % delta.minutes
    if delta.seconds:
        ret += '%d秒' % delta.seconds
    return ret


def insert_result(text, title_re, tar, result, stop_re=None):
    lines = text.splitlines(True)
    lines.append('\n')  # For the case that the last line is our target.
    found, ts = False, 0
    for i, line in enumerate(lines):
        if stop_re and stop_re.search(line):
            break
        target = (title_re.findall(line) or [''])[0]
        if found:
            if target or i == len(lines) - 1:
                t = i
                while t and not lines[t - 1].strip('\n'):
                    t -= 1  # Find the last blank line and insert before it.
                lines.insert(t, result)
                break
            ts += len(ts_re.findall(line))
            if ts > 1:
                return '', False
        # FIXME: The title needs normalization, e.g. [[WP:xxx]]
        elif target.replace('_', ' ') == tar:
            found = True

    return ''.join(lines), found


def ip_in_range(ip, range):
    try:
        target = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return target in range


def isip(user):
    try:
        ipaddress.ip_network(user)
    except ValueError:
        return False
    return True


def handleVIP(change):
    site = Site()
    text = site.get_text_by_title(VIP, ts=True)
    basets = site.get_ts()
    user = change.get('title', '')
    params = change.get('logparams', {}) or change.get('params', {})
    duration = params.get('duration')
    timestamp = change.get('timestamp')
    expiry = params.get('expiry')
    sysop = change.get('user')
    logaction = change.get('logaction')

    if expiry == timestamp:
        return None

    if not expiry:
        if duration in ['infinite', 'indefinite', 'infinity']:
            expiry = duration
        else:
            log(f"[handleVIP] Skipped: Cannot parse expiry for user '{user}' (params: {params})")
            return None

    if not any([sysop, user, timestamp]):
        log(f"[handleVIP] Skipped: Incomplete log entry for user '{user}'")
        return None

    block_log = site.api_get({'action': 'query', 'list': 'logevents', 'letype': 'block',
                              'letitle': user, 'lelimit': 1}, 'query').get('logevents')
    if not block_log or type(block_log) != list:
        log(f"[handleVIP] Skipped: No block log verification found for '{user}'")
        return None
        
    new_params = block_log[0].get('params', {}) or block_log[0].get('logparams', {})
    latest_expiry = new_params.get('expiry') or new_params.get('duration')
    if latest_expiry != expiry:
        log(f"[handleVIP] Skipped: Block parameter changed/mismatched for '{user}' (current: {expiry}, latest: {latest_expiry})")
        return None

    raw_user = user
    if user.startswith('User:'):
        user = user[5:]
    elif user.startswith('用户:'):
        user = user[3:]
    elif ':' in user:
        user = user.split(':', 1)[1]

    ip_range = None
    ip = isip(user)
    if '/' in user:
        try:
            ip_range = ipaddress.ip_network(user)
        except ValueError:
            log(f"[handleVIP] Skipped: Invalid IP range format '{user}'")
            return None

    result = '{{Blocked|%s|ad=%s}}' % (ts_delta(expiry, timestamp), sysop)
    if ip_range:
        result += '<small>（[[special:contribs/{0}|{0}]]的段封）</small>'.format(user)
    result += '。 --~~~~'

    lines = text.splitlines(True)
    found, replaced = False, False
    skip_reason = None

    for i, line in enumerate(lines):
        target = (vandal_re.findall(line) or [''])[0]
        if found:
            if target:
                insert_pos = i
                while insert_pos > 0 and lines[insert_pos - 1].strip() == '':
                    insert_pos -= 1
                lines.insert(insert_pos, '* 處理：%s\n' % result)
                replaced = True
                break

            m = result_re.match(line)
            if m:
                content = comment_re.sub('', m.group(1)).strip()
                if content:
                    skip_reason = f"Already processed by others ('{content}')"
                    break
                else:
                    lines[i] = '* 處理：%s\n' % result
                    replaced = True
                    break

        elif target:
            if ip:
                if target.upper() == user.upper() or (ip_range and ip_in_range(target, ip_range)):
                    found = True
            else:
                if target == user:
                    found = True

    if found and not replaced and not skip_reason:
        m = result_re.match(lines[-1]) if lines else None
        if not (m and comment_re.sub('', m.group(1)).strip()):
            lines.append('* 處理：%s\n' % result)
            replaced = True

    if replaced:
        log(f"[handleVIP] Matched reported target '{user}', pushing edit to queue.")
        EditQueue().push(
            text=''.join(lines),
            summary=get_summary('13', '回報[[Special:Contribs/{0}|{0}]]的處理結果'.format(user)),
            title=VIP,
            bot=True,
            basetimestamp=basets,
            op_type='block',
            operator=sysop,
            target=user,
            op_timestamp=timestamp
        )
    else:
        if not found:
            log(f"[handleVIP] User '{user}' is not reported on {VIP}.")
        elif skip_reason:
            log(f"[handleVIP] Skipped updating '{user}': {skip_reason}")


def handleRFP(change):
    site = Site()
    text = site.get_text_by_title(RFP, ts=True)
    basets = site.get_ts()
    page = change.get('title')
    sysop = change.get('user')
    details = change.get('logparams', {}).get('details', [])
    ots = change.get('timestamp')

    protect_log = site.api_get({'action': 'query', 'list': 'logevents', 'letype': 'protect',
                                'letitle': page, 'lelimit': 1}, 'query').get('logevents')
    if not protect_log or type(protect_log) != list:
        log(f"[handleRFP] Skipped: No protect log verification found for '{page}'")
        return None

    if protect_log[0].get('logid') != change.get('logid'):
        log(f"[handleRFP] Skipped: Protect action modified by newer operation for '{page}'")
        return None

    if not any([page, sysop, details, ots]):
        log(f"[handleRFP] Skipped: Incomplete log entry for '{page}'")
        return None

    if details and type(details) == list:
        pt = details[0]
        delta = ts_delta(pt['expiry'], ots)
        if not delta:
            return None
        result = '* {{{{RFPP|{level}|{time}|by={by}}}}}'.format(
            level=pt_dict[pt['level']] if pt['type'] == 'edit' else pt_dict[pt['type']],
            time=delta, by=sysop)
    else:
        log(f"[handleRFP] Skipped: Invalid 'details' in logparams for '{page}' (logid: {change.get('logid', -1)})")
        return None

    result += '。 --~~~~'

    newtext, found = insert_result(text, protect_re, page, '%s\n' % result, stop_re=unprotect_re)
    if found:
        log(f"[handleRFP] Matched requested page '{page}', pushing edit to queue.")
        EditQueue().push(
            text=newtext,
            summary=get_summary('13', '回報[[:%s]]的處理結果' % page),
            title=RFP,
            bot=True,
            basetimestamp=basets,
            operator=sysop,
            target=page,
            op_timestamp=ots
        )
    else:
        log(f"[handleRFP] Page '{page}' is not requested on {RFP}.")


@check('13')
def work(report_que):
    if not report_que.queue:
        return LONG_SLEEP
    change = report_que.queue[0]
    ct = cur_timestamp()
    delta = ts_delta(ct, change.get('timestamp', ct), tostr=False)
    if delta < DELAY:
        ret = DELAY - delta + SHORT_SLEEP
        log(f"[Work] Waiting {int(ret)}s buffer delay for: {change.get('title')} ({change.get('timestamp')})")
        return ret

    change = report_que.get()
    if DEBUG:
        log('handling {type}: {fr} -> {to} on {ts}'.format(type=change['logtype'], fr=change['user'],
                                                       to=change['title'], ts=change['timestamp']))
    if change['logtype'] == 'block':
        handleVIP(change)
    else:
        handleRFP(change)
    return SHORT_SLEEP

RC_INTERVAL = 60       # Interval for query recent changes
QUEUE_INTERVAL = 3     # Interval for querying the edit queue

def rc_loop(w):
    while True:
        try:
            w.watch()
        except Exception as e:
            log('rc_loop error: %r' % e)
        time.sleep(RC_INTERVAL)


def report_loop():
    while True:
        try:
            sleep_time = work(report_que) or SHORT_SLEEP
        except Exception as e:
            log('report_loop error: %r' % e)
            sleep_time = SHORT_SLEEP
        if DEBUG:
            log('Nothing to do, sleep %d seconds...' % sleep_time)
        time.sleep(sleep_time)


def edit_loop():
    while True:
        try:
            process_edit_queue()
        except Exception as e:
            log('edit_loop error: %r' % e)
        time.sleep(QUEUE_INTERVAL)


def main():
    site = Site()
    site.client_login()

    threads = [
        threading.Thread(target=rc_loop, args=(watcher(),), daemon=True, name='rcwatcher'),
        threading.Thread(target=report_loop, daemon=True, name='report'),
        threading.Thread(target=edit_loop, daemon=True, name='editqueue'),
    ]
    for t in threads:
        t.start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        if DEBUG:
            log('program terminated because of KeyboardInterrupt')
        sys.exit(0)


if __name__ == '__main__':
    # python report.py <password>, or python report.py and input password in prompt
    main()
