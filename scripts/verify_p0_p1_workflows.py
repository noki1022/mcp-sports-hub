#!/usr/bin/env python3
"""Static safety checks for P0/P1 basketball automation maintenance."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
daily=(ROOT/".github/workflows/titan007-daily-free.yml").read_text()
three=(ROOT/".github/workflows/titan007-three-analysis.yml").read_text()
final=(ROOT/".github/workflows/titan007-final-hourly.yml").read_text()
join=(ROOT/"scripts/titan007_join_daily.py").read_text()
for s in (daily,three,final):
    assert 'numpy==2.2.6' in s, "model numerical dependency missing"
    assert 'Generate odds-blind NBA prediction artifact' in s
assert 'cron: "30 13-22 * * *"' in final
assert '*/10 * * * *' not in final
assert "contents: write" in final
assert "git add reports/hourly/" in final
assert "git add reports/final-window/" not in final
assert final.index("titan007_hourly_history.py capture") < final.index("Select 3–30 minute final window")
assert "if: success()" in final
assert "if: ${{ success() && env.PUSHPLUS_TOKEN != '' }}" in final
assert "except ET.ParseError:" in join
assert "for attempt in range(3):" in join
assert 'raise RuntimeError("Scoreboard XML malformed/truncated in all three downloads")' in join
assert 'cron: "0 22 * * *"' in three and 'cron: "0 4 * * *"' in three and 'cron: "0 13 * * *"' in three
print("P0_P1_WORKFLOW_GUARDRAILS_PASS")
