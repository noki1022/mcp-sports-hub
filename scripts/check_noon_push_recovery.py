#!/usr/bin/env python3
from pathlib import Path
s=Path('.github/workflows/titan007-three-analysis.yml').read_text()
for expr in ('0 4 * * *','15 4 * * *','30 4 * * *'):
    assert ('cron: "'+expr+'"') in s
assert "'15 4 * * *':'1200'" in s and "'30 4 * * *':'1200'" in s
assert 'REPORT_ALREADY_SENT' in s
assert 'reports/pushplus-sent/' in s
assert '--require-token' in s
assert "status.get('state')!='API_ACCEPTED_NOT_DEVICE_CONFIRMED'" in s
assert s.index('Resolve canonical report slot') < s.index('Send compact iPhone PushPlus')
assert "if: ${{ success() && env.REPORT_ALREADY_SENT != 'true' }}" in s
print('NOON_PUSHPLUS_RECOVERY_GUARDS_PASS')
