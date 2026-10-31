#!/usr/bin/env python3
"""Regression for noon recovery and the shared fixed-slot delivery gate."""
from pathlib import Path
from datetime import datetime
import sys
sys.path.insert(0, str(Path("scripts").resolve()))
from nba_fixed_slot_gate import SCHEDULE_SLOTS, resolve_slot, marker_is_accepted

s=Path(".github/workflows/titan007-three-analysis.yml").read_text()
now=datetime.fromisoformat("2026-10-31T12:00:00+08:00")
for expr in ("0 4 * * *","15 4 * * *","30 4 * * *"):
    assert ('cron: "'+expr+'"') in s
    assert SCHEDULE_SLOTS[expr]=="1200"
    assert resolve_slot(expr,"",now)=="1200"
assert s.index("Preflight canonical slot and verified acceptance") < s.index("Join independent UTC fixture")
assert s.index("Recheck verified acceptance before PushPlus") < s.index("Send compact iPhone PushPlus")
assert "python3 scripts/nba_fixed_slot_gate.py --phase preflight" in s
assert "python3 scripts/nba_fixed_slot_gate.py --phase recheck" in s
assert "if: steps.preflight.outputs.skip != 'true'" in s
assert "if: ${{ success() && env.REPORT_ALREADY_SENT != 'true' }}" in s
assert "--send --require-token --require-delivery" in s
assert "status.get('state')!='API_ACCEPTED_NOT_DEVICE_CONFIRMED'" in s
assert "FALLBACK_SLOT=\"${REPORT_SLOT:-}\"" in s
assert "nba_schedule_fallback_push.py" in s
assert "reports/pushplus-sent" in s
print("NOON_PUSHPLUS_RECOVERY_GUARDS_PASS")

# Live incidents (2026-10-31): delayed cron, empty 007 next-day ID3, and
# 13:05 first-available market data must not abort fixture-only baseline.
assert '--allow-schedule-only' in s
assert 'SCHEDULE_ONLY_CAPTURE_NO_VERIFIED_007_QUOTES' in Path('scripts/titan007_join_beijing_verified.py').read_text()
assert 'FALLBACK_SLOT="${REPORT_SLOT:-}"' in s
assert "python3 scripts/nba_fixed_slot_gate.py --phase recheck" in s
assert s.index('Lock the noon official NBA slate') < s.index('Enforce Beijing date identity')
# Exercise the actual CLI serializer: the old late-freeze wrote a literal
# backslash+n after JSON, which made the next capture fail to read the lock.
import json, subprocess, sys, tempfile
with tempfile.TemporaryDirectory() as directory:
    base=Path(directory)
    date='2026-11-01'
    capture={
        'requested_display_date':date,'captured_at_utc':'2026-10-31T05:05:00Z',
        'official_schedule_count':1,
        'upcoming_nba_games':[{'nba_game_id':'fixture001','home':'UTA',
           'away':'POR','utc_tip':'2026-10-31T19:00:00+00:00',
           'beijing_date':date}],
        'nba_cba_games':[]}
    source=base/'joined.json';lock=base/'lock.json'
    source.write_text(json.dumps(capture),encoding='utf-8')
    subprocess.run([sys.executable,'scripts/nba_noon_slate.py','late-freeze',
        '--joined',str(source),'--out',str(lock)],check=True,capture_output=True,text=True)
    loaded=json.loads(lock.read_text(encoding='utf-8'))
    assert loaded['noon_on_time'] is False
    assert loaded['baseline_quote_count']==0
    assert loaded['official_count']==1
print('NOON_LATE_CAPTURE_AND_FALLBACK_GUARDS_PASS')
