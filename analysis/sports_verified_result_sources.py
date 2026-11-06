"""Pure, fail-closed parsers for original postgame source bytes; no model inference."""
import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

BJ = ZoneInfo('Asia/Shanghai')


class Header(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.fields = {}
        self.visible = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = attrs.get('id')
        if key in ('homeScore', 'guestScore', 'mState', 'scoreState'):
            if key in self.fields:
                raise ValueError('DUPLICATE_SCORE_HEADER')
            self.fields[key] = ''
        if tag not in ('br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr'):
            self.stack.append((tag, key))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if any(tag in ('script', 'style') for tag, _ in self.stack):
            return
        self.visible.append(data)
        for _, key in self.stack:
            if key in self.fields:
                self.fields[key] += data


def football(raw, match_id):
    if not isinstance(raw, bytes) or len(raw) > 850000:
        raise ValueError('FOOTBALL_SOURCE_SIZE')
    html = raw.decode('utf-8-sig')
    def scalar(name):
        found = re.findall(r'\bvar\s+' + re.escape(name) + r'\s*=\s*("[^"\r\n]*"|-?\d+)\s*;', html)
        if len(found) != 1:
            raise ValueError('SOURCE_SCALAR_MISSING_OR_DUPLICATE:' + name)
        return json.loads(found[0])
    if str(scalar('scheduleId')) != str(match_id):
        raise ValueError('SOURCE_MATCH_ID_MISMATCH')
    header = Header()
    header.feed(html)
    f = {k: v.strip() for k, v in header.fields.items()}
    if scalar('matchState') != -1 or f.get('mState') != '完场':
        raise ValueError('FOOTBALL_NOT_FINAL')
    # Restrict initial admission to verified league rounds / cup league-group
    # stages. Knockout, ET, penalties and ambiguous 90-minute totals stay pending.
    score = f.get('scoreState', '')
    if not score or re.search(r'加时|点球|腰斩|中断|取消|待定', score):
        raise ValueError('REGULATION_SCORE_AMBIGUOUS')
    visible = ' '.join(header.visible)
    stage = visible.split('完场', 1)[0]
    regular = (scalar('_isCup') == '1' and re.search(r'第\s*\d+\s*轮', stage))
    group = re.search(r'联赛阶段|小组赛|小组阶段', stage)
    if not (regular or group):
        raise ValueError('REGULATION_STAGE_NOT_VERIFIED')
    def goals(key):
        text = f.get(key, '')
        if not re.fullmatch(r'\d{1,2}', text) or not 0 <= int(text) <= 25:
            raise ValueError('INVALID_SOURCE_GOALS')
        return int(text)
    tip = datetime.fromisoformat(scalar('headMatchTime'))
    if tip.tzinfo is not None:
        raise ValueError('UNEXPECTED_SOURCE_TIMEZONE')
    home, away = scalar('headHomeTeamId'), scalar('headGuestTeamId')
    if type(home) is not int or type(away) is not int or min(home, away) <= 0 or home == away:
        raise ValueError('INVALID_SOURCE_TEAM_IDS')
    return {'match_id': str(match_id), 'home_goals': goals('homeScore'),
            'away_goals': goals('guestScore'), 'final_status': 'FT',
            'home_team_id_007': home, 'away_team_id_007': away,
            'kickoff_beijing': tip.replace(tzinfo=BJ).isoformat(),
            'source_url': f'https://m.titan007.com/analy/Analysis/{match_id}.htm',
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'parser_version': '007-header-regulation-v1'}


def basketball(raw, event_id):
    if len(raw) > 2000000:
        raise ValueError('NBA_SOURCE_SIZE')
    events = [e for e in json.loads(raw).get('events', []) if str(e.get('id')) == str(event_id)]
    if len(events) != 1:
        raise ValueError('NBA_EVENT_MISSING_OR_DUPLICATE')
    e = events[0]
    status = (e.get('status') or {}).get('type', {})
    if status.get('completed') is not True or status.get('name') != 'STATUS_FINAL':
        raise ValueError('NBA_NOT_FINAL')
    competitions = e.get('competitions', [])
    if len(competitions) != 1 or len(competitions[0].get('competitors', [])) != 2:
        raise ValueError('NBA_COMPETITORS_INVALID')
    sides = {s['homeAway']: s for s in competitions[0]['competitors']}
    if set(sides) != {'home', 'away'}:
        raise ValueError('NBA_SIDES_INVALID')
    out = {'completed': True, 'tip_beijing': e['date']}
    for side in ('home', 'away'):
        value = sides[side].get('score')
        if not isinstance(value, str) or not re.fullmatch(r'\d{1,3}', value):
            raise ValueError('NBA_INVALID_SOURCE_SCORE')
        out[side + '_points'] = int(value)
        out[side + '_abbr'] = sides[side]['team']['abbreviation']
    return out
