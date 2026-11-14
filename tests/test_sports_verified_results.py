import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

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


def knockout_html():
    return html().replace("巴西甲 第34轮".encode(), "日联杯 半准决赛".encode())


def desktop_events():
    return """<script>
    var scheduleID = 3075305;
    var strTime = '2026-11-06 07:30';
    var homeTeamFlg = '//zq.titan007.com/Image/team/images/1/home.png';
    var guestTeamFlg = '//zq.titan007.com/Image/team/images/2/away.png';
    </script><ul id="teamEventDiv">
    <li class='teamtit'><div class='data'><span>主队</span><span></span><span>客队</span></div></li>
    <li class='lists'><div class='data'><span><a><span>球员</span></a><img title='点球'></span><span>20'</span><span></span></div></li>
    <li class='lists'><div class='data'><span></span><span>45+6'</span><span><img title='入球'></span></div></li>
    <li class='lists'><div class='data'><span><img title='入球'></span><span>90+4'</span><span></span></div></li>
    </ul><div><img title='入球'></div>""".encode()


class Results(unittest.TestCase):
    def test_efl_trophy_regional_group_and_unverified_knockout(self):
        cup = html().replace(b'_isCup="1"', b'_isCup="2"')
        for region in ("北", "南"):
            group = cup.replace("巴西甲 第34轮".encode(), ("英锦赛 分组赛" + region).encode())
            self.assertEqual(S.football(group, 3075305)["home_goals"], 2)
        knockout = cup.replace("巴西甲 第34轮".encode(), "日联杯 半准决赛".encode())
        with self.assertRaisesRegex(ValueError, "REGULATION_STAGE_NOT_VERIFIED"):
            S.football(knockout, 3075305)

    def test_knockout_requires_matching_007_regulation_goal_events(self):
        raw, events = knockout_html(), desktop_events()
        row = S.football(raw, 3075305, desktop=events)
        self.assertEqual((row["home_goals"], row["away_goals"]), (2, 1))
        self.assertEqual(row["regulation_evidence"]["source_url"], S.football_event_url(3075305))
        cases = (
            (events.replace(b"90+4'", b"105+1'"), "NON_REGULATION"),
            (events.replace(b"90+4'", b"91'"), "NON_REGULATION"),
            (events + "<div>点球大战</div>".encode(), "EXTRA_TIME_OR_SHOOTOUT"),
            (events.replace("title='点球'".encode(), b""), "GOALS_DO_NOT_CONFIRM_SCORE"),
            (events.replace(b"teamEventDiv", b"other"), "LIST_MISSING_OR_DUPLICATE"),
            (events.replace(b"3075305", b"3075306"), "MATCH_ID_MISMATCH"),
            (events.replace(b"07:30", b"07:45"), "KICKOFF_MISMATCH"),
            (events.replace(b"images/1/", b"images/2/"), "TEAM_ID_MISMATCH"),
        )
        for altered, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                S.football(raw, 3075305, desktop=altered)
        tied = raw.replace(b'id="homeScore">2', b'id="homeScore">0').replace(
            b'id="guestScore">1', b'id="guestScore">0')
        empty = events.replace("title='入球'".encode(), b"").replace("title='点球'".encode(), b"")
        with self.assertRaisesRegex(ValueError, "GOALS_DO_NOT_CONFIRM_SCORE"):
            S.football(tied, 3075305, desktop=empty)
        with self.assertRaisesRegex(ValueError, "REGULATION_SCORE_AMBIGUOUS"):
            S.football(raw.replace("完场</span>".encode(), "完场</span>点球".encode()), 3075305, desktop=events)

    def test_nations_league_header_accepts_group_phase_only(self):
        cup = html().replace(b'_isCup="1"', b'_isCup="2"')
        for division in ("A", "C"):
            stage = f'<div id="head"><div class="league">欧国联&nbsp{division}联赛&nbsp11-13 03:45&nbsp微雨</div></div>'
            raw = cup.replace("<div>巴西甲 第34轮</div>".encode(), stage.encode())
            self.assertEqual(S.football(raw, 3075305)["away_goals"], 1)
            with self.assertRaisesRegex(ValueError, "FOOTBALL_NOT_FINAL"):
                S.football(raw.replace(b"matchState=-1", b"matchState=0"), 3075305)
            knockout = raw.replace(f"{division}联赛".encode(), "半准决赛".encode())
            with self.assertRaisesRegex(ValueError, "REGULATION_STAGE_NOT_VERIFIED"):
                S.football(knockout, 3075305)

    def test_desktop_match_header_identifies_teams_when_flags_lack_ids(self):
        header = b'''<div class="analyhead new">
          <div class="home"><a href="//zq.titan007.com/cn/team/Summary/1.html">Home</a></div>
          <div class="guest"><a href="//zq.titan007.com/cn/team/Summary/2.html">Away</a></div>
        </div>'''
        events = desktop_events().replace(b'images/1/home.png', b'images/165018987224.png').replace(
            b'images/2/away.png', b'images/1kd9x06mhg1c.png')
        self.assertEqual(S.football(knockout_html(), 3075305, desktop=header + events)['away_goals'], 1)
        for invalid in (header.replace(b'Summary/1.html', b'Summary/2.html'),
                        header.replace(b'class="guest"', b'class="other"'), header + header):
            with self.subTest(header=invalid), self.assertRaisesRegex(ValueError, 'TEAM_ID_MISMATCH'):
                S.football(knockout_html(), 3075305, desktop=invalid + events)

    def test_football_source_timeout_keeps_the_result_pending(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"ops"))
        import sports_result_to_review as job
        final = football()
        tag = f"sport-pregame-final-football-{final['kickoff_beijing_day']}"
        release = {"assets": [{"name": "football-3075305.final.json", "id": 1}]}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(job, "release", side_effect=lambda repo, name: release if name == tag else None),
            patch.object(job, "asset_bytes", return_value=json.dumps(final).encode()),
            patch.object(job, "fetch", side_effect=URLError(TimeoutError("TLS handshake timed out"))),
            patch.object(job, "datetime", wraps=job.datetime) as clock,
            patch.object(job, "gh") as publish,
        ):
            clock.now.return_value = TIP.astimezone(job.ZoneInfo("Asia/Shanghai"))
            health = job.run("fixture/repo", tmp, publish=True, days=1)
        self.assertEqual(health["pending"][0]["reason"], "FOOTBALL_RESULT_SOURCE_TIMEOUT")
        self.assertFalse(health["errors"])
        self.assertFalse(health["verified"])
        publish.assert_not_called()

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

    def test_kickoff_mismatch_preserves_raw_evidence_without_scoring(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"ops"))
        import sports_result_to_review as job
        final = football()
        source_tag = f"sport-pregame-final-football-{final['kickoff_beijing_day']}"
        raw = html().replace(b"07:30:00", b"07:40:00")
        with self.assertRaisesRegex(ValueError, "007_KICKOFF_MISMATCH"):
            V.score(final, raw, iso(TIP + timedelta(hours=3)))
        source = {"assets": [{"name": "football-3075305.final.json", "id": 1}]}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(job, "release", side_effect=lambda repo, tag: source if tag == source_tag else None),
            patch.object(job, "asset_bytes", return_value=json.dumps(final).encode()),
            patch.object(job, "fetch", return_value=(raw, iso(TIP + timedelta(hours=3)))),
            patch.object(job, "datetime", wraps=job.datetime) as clock,
            patch.object(job, "gh") as publish,
        ):
            clock.now.return_value = TIP.astimezone(job.ZoneInfo("Asia/Shanghai"))
            result = job.run("fixture/repo", tmp, publish=True, days=1)
            self.assertFalse(result["errors"])
            self.assertFalse(result["verified"])
            item, = result["quarantined"]
            self.assertEqual(item["frozen_kickoff_utc"], final["kickoff_utc"])
            self.assertTrue(item["source_kickoff_beijing"].endswith("07:40:00+08:00"))
            self.assertEqual((Path(tmp)/item["raw_path"]).read_bytes(), raw)
            publish.assert_not_called()

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

    def test_verified_espn_gs_alias_preserves_home_away_check(self):
        import sport_match_final_grade as G
        final=nba()
        final['home_team']='金州勇士'
        source={'completed':True,'home_points':120,'away_points':100,
                'tip_beijing':iso(TIP),'home_abbr':'GS','away_abbr':'MIA'}
        G.verify_nba_final_score_identity(final,source)
        source['home_abbr'],source['away_abbr']='MIA','GS'
        with self.assertRaisesRegex(ValueError,'SWAPPED'):
            G.verify_nba_final_score_identity(final,source)

    def test_verified_espn_wsh_alias_preserves_home_away_check(self):
        import sport_match_final_grade as G
        final = nba()
        final.update(home_team="亚特兰大老鹰", away_team="华盛顿奇才")
        source = {"completed": True, "home_points": 139, "away_points": 132,
                  "tip_beijing": iso(TIP), "home_abbr": "ATL", "away_abbr": "WSH"}
        G.verify_nba_final_score_identity(final, source)
        source.update(home_abbr="WSH", away_abbr="ATL")
        with self.assertRaisesRegex(ValueError, "SWAPPED"):
            G.verify_nba_final_score_identity(final, source)

    def test_live_espn_aliases_still_reject_reversed_sides(self):
        import sport_match_final_grade as G
        for name, abbreviation in (("纽约尼克斯", "NY"), ("圣安东尼奥马刺", "SA"),
                                   ("新奥尔良鹈鹕", "NO"), ("犹他爵士", "UTAH")):
            with self.subTest(abbreviation=abbreviation):
                final = nba()
                final.update(home_team="亚特兰大老鹰", away_team=name)
                source = {"completed": True, "home_points": 112, "away_points": 100,
                          "tip_beijing": iso(TIP), "home_abbr": "ATL", "away_abbr": abbreviation}
                G.verify_nba_final_score_identity(final, source)
                source.update(home_abbr=abbreviation, away_abbr="ATL")
                with self.assertRaisesRegex(ValueError, "SWAPPED"):
                    G.verify_nba_final_score_identity(final, source)


if __name__=='__main__':
    unittest.main()
