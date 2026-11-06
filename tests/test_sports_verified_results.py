import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'analysis'))
import sports_verified_result_sources as S
import sports_verified_review as V
import sport_match_final_registry as R
from test_sport_match_final_grade import football, nba, TIP, iso
from datetime import timedelta


def html():
    return '''<div>巴西甲 第34轮</div><div id="scoreState"><div id="homeScore">2</div>
    <span id="mState">完场</span><div id="guestScore">1</div></div><script>
    var scheduleId=3075305;var matchState=-1;var _isCup="1";
    var headHomeTeamId=1;var headGuestTeamId=2;var headMatchTime="2026-11-06T07:30:00";
    </script>'''.encode()


class Results(unittest.TestCase):
    def test_real_header_shape_replays_three_markets(self):
        final = football()
        report = V.make(final, html(), 'https://m.titan007.com/analy/Analysis/3075305.htm', iso(TIP+timedelta(hours=2)))
        self.assertTrue(V.verify(report, final))
        self.assertEqual(report['matches'][0]['actual_score'], {'home': 2, 'away': 1})
        self.assertEqual(report['summary']['hhad']['misses'], 1)

    def test_fail_closed_status_identity_extra_time_and_duplicate(self):
        for raw in (html().replace('完场'.encode(), '中场'.encode()),
                    html().replace(b'matchState=-1', b'matchState=1'),
                    html().replace(b'3075305', b'3075306'),
                    html().replace(b'<div id="homeScore">2', b'<div id="homeScore">2</div><div id="homeScore">2'),
                    html().replace('完场</span>'.encode(), '完场</span>加时'.encode()),
                    html().replace('第34轮'.encode(), '决赛'.encode())):
            with self.assertRaises(ValueError):
                S.football(raw, '3075305')

    def test_same_hash_cannot_legitimize_fabricated_score(self):
        final = football()
        report = V.make(final, html(), 'https://m.titan007.com/analy/Analysis/3075305.htm', iso(TIP+timedelta(hours=2)))
        report['matches'][0]['actual_score']['home'] = 9
        report['review_sha256'] = R.digest({k:v for k,v in report.items() if k!='review_sha256'})
        with self.assertRaisesRegex(ValueError, 'DOES_NOT_REPLAY'):
            V.verify(report, final)

    def test_nba_completed_boolean_and_full_replay(self):
        event = {'id':'1001', 'date':iso(TIP), 'status':{'type':{'completed':True,'name':'STATUS_FINAL'}},
            'competitions':[{'competitors':[
                {'homeAway':'home','score':'112','team':{'abbreviation':'ATL'}},
                {'homeAway':'away','score':'100','team':{'abbreviation':'MIA'}}]}]}
        raw = json.dumps({'events':[event]}).encode()
        url = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261105&limit=100'
        self.assertTrue(V.verify(V.make(nba(),raw,url,iso(TIP+timedelta(hours=3))),nba()))
        event['status']['type']['completed'] = 'true'
        with self.assertRaisesRegex(ValueError,'NBA_NOT_FINAL'):
            S.basketball(json.dumps({'events':[event]}).encode(),'1001')

    def test_nba_cli_cohort_does_not_raise_nameerror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'scores.json').write_text('{}')
            (root/'cohort.json').write_text(json.dumps({'schema_version':'nba-beijing-noon-cohort-v1',
                'target_beijing_date':'2026-11-06','official_count':0,'official_games':{}}))
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'analysis/nba_per_match_score_review.py'),
                '--final-root',tmp,'--day','20261106','--scores',str(root/'scores.json'),
                '--official-cohort',str(root/'cohort.json'),'--out-dir',str(root/'out')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((root/'out/review.json').exists())


if __name__=='__main__':
    unittest.main()
