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
        if tag == 'div' and 'league' in attrs.get('class', '').split() and any(
                parent == 'head' for _, parent in self.stack):
            key = 'match_league_header'
        if key in ('homeScore', 'guestScore', 'mState', 'scoreState', 'match_league_header'):
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


class RegulationStageUnverified(ValueError):
    pass


def football_event_url(match_id):
    return f'https://live.titan007.com/detail/{match_id}cn.htm'


class FootballEvents(Header):
    """Read only 007's important-events list, whose columns are home/minute/away."""

    def __init__(self):
        super().__init__()
        self.feed_count = 0
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get('id') == 'teamEventDiv':
            self.feed_count += 1
        if ('ul', 'teamEventDiv') in self.stack:
            index = self.stack.index(('ul', 'teamEventDiv'))
            parents = [name for name, _ in self.stack[index + 1:]]
            if parents == [] and tag == 'li':
                self.row = []
            if parents == ['li', 'div'] and tag == 'span':
                self.row.append({'text': '', 'goals': []})
            if tag == 'img' and attributes.get('title') in ('入球', '点球', '乌龙', '乌龙球'):
                if parents != ['li', 'div', 'span'] or not self.row:
                    raise ValueError('007_EVENT_GOAL_LAYOUT')
                self.row[-1]['goals'].append(attributes['title'])
        super().handle_starttag(tag, attrs)

    def handle_data(self, data):
        super().handle_data(data)
        if ('ul', 'teamEventDiv') in self.stack and len(self.row) == 2:
            index = self.stack.index(('ul', 'teamEventDiv'))
            if [name for name, _ in self.stack[index + 1:]] == ['li', 'div', 'span']:
                self.row[-1]['text'] += data

    def handle_endtag(self, tag):
        if tag == 'li' and len(self.stack) >= 2 and self.stack[-2] == ('ul', 'teamEventDiv'):
            self.rows.append(self.row)
        super().handle_endtag(tag)


def verify_football_events(raw, result):
    if not isinstance(raw, bytes) or len(raw) > 850000:
        raise ValueError('007_EVENT_SOURCE_SIZE')
    html = raw.decode('utf-8-sig')

    def field(name, pattern):
        values = re.findall(r'\bvar\s+' + name + r'\s*=\s*' + pattern + r'\s*;', html)
        if len(values) != 1:
            raise ValueError('007_EVENT_FIELD_MISSING_OR_DUPLICATE:' + name)
        return values[0]

    if field('scheduleID', r'(\d+)') != result['match_id']:
        raise ValueError('007_EVENT_MATCH_ID_MISMATCH')
    for name, side in (('homeTeamFlg', 'home'), ('guestTeamFlg', 'away')):
        team = field(name, r"'//zq\.titan007\.com/Image/team/images/(\d+)/[^'\s]+'")
        if int(team) != result[f'{side}_team_id_007']:
            raise ValueError('007_EVENT_TEAM_ID_MISMATCH')
    tip = datetime.fromisoformat(result['kickoff_beijing'])
    if tip.strftime('%Y-%m-%d %H:%M') != field('strTime', r"'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})'"):
        raise ValueError('007_EVENT_KICKOFF_MISMATCH')

    feed = FootballEvents()
    feed.feed(html)
    feed.close()
    if feed.feed_count != 1:
        raise ValueError('007_EVENT_LIST_MISSING_OR_DUPLICATE')
    if re.search(r'加时赛|点球大战|点球决胜|互射点球|十二碼決勝|penalty shootout',
                 ' '.join(feed.visible), re.I):
        raise ValueError('007_EVENT_EXTRA_TIME_OR_SHOOTOUT')
    counts = [0, 0]
    for row in feed.rows:
        goals = sum(len(cell['goals']) for cell in row)
        if not goals:
            continue
        if (goals != 1 or len(row) != 3 or row[1]['goals']
                or not re.fullmatch(r"(?:[1-9]|[1-8]\d|90)(?:\+\d{1,2})?['’]",
                                    row[1]['text'].strip())):
            raise ValueError('007_EVENT_NON_REGULATION_OR_UNREADABLE_GOAL')
        counts[0 if row[0]['goals'] else 1] += 1
    # Missing events and a true 0:0 are indistinguishable in this list.
    if counts == [0, 0] or counts != [result['home_goals'], result['away_goals']]:
        raise ValueError('007_EVENT_GOALS_DO_NOT_CONFIRM_SCORE')
    return {'source_url': football_event_url(result['match_id']),
            'source_sha256': hashlib.sha256(raw).hexdigest()}


def football(raw, match_id, *, desktop=None):
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
    score = f.get('scoreState', '')
    if not score or re.search(r'加时|点球|腰斩|中断|取消|待定', score):
        raise ValueError('REGULATION_SCORE_AMBIGUOUS')
    visible = ' '.join(header.visible)
    stage = visible.split('完场', 1)[0]
    regular = (scalar('_isCup') == '1' and re.search(r'第\s*\d+\s*轮', stage))
    group = re.search(r'联赛阶段|小组赛|小组阶段|英锦赛\s+分组赛[南北](?=\s|$)', stage)
    # 007 displays the UEFA Nations League group phase as A联赛 through D联赛.
    # Match the league header, so a reference elsewhere cannot authorize a knockout score.
    nations_group = re.match(r'^欧国联\s+[A-D]联赛\s+\d{2}-\d{2}\s+\d{2}:\d{2}(?=\s|$)',
                             f.get('match_league_header', ''))
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
    result = {'match_id': str(match_id), 'home_goals': goals('homeScore'),
            'away_goals': goals('guestScore'), 'final_status': 'FT',
            'home_team_id_007': home, 'away_team_id_007': away,
            'kickoff_beijing': tip.replace(tzinfo=BJ).isoformat(),
            'source_url': f'https://m.titan007.com/analy/Analysis/{match_id}.htm',
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'parser_version': '007-header-regulation-v1'}
    if not (regular or group or nations_group):
        if desktop is None:
            raise RegulationStageUnverified('REGULATION_STAGE_NOT_VERIFIED')
        result['regulation_evidence'] = verify_football_events(desktop, result)
        result['parser_version'] = '007-header-and-regulation-events-v1'
    return result


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
