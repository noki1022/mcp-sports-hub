"""Exercise the real review shell preflight with local, non-network GH stubs."""
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ReviewDeliveryPreflight(unittest.TestCase):
    def invoke(self, mode):
        workflow=(ROOT/'.github/workflows/football-review-push-1300.yml').read_text()
        body=workflow.split('      - name: Send one verified previous-day review and archive API acceptance\n',1)[1]
        script=textwrap.dedent(body.split('        run: |\n',1)[1].split('      - uses:',1)[0])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bin=root/'bin';bin.mkdir()
            (bin/'date').write_text('#!/bin/sh\nprintf "2026-11-17\\n"\n')
            (bin/'date').chmod(0o700)
            (bin/'gh').write_text('''#!/bin/sh
printf '%s\n' "$*" >> "$STUB_CALLS"
if [ "$1" != api ]; then echo 'Unexpected write or download' >&2; exit 90; fi
case "$STUB_MODE" in
  missing) echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;
  forbidden) echo 'gh: Resource not accessible (HTTP 403)' >&2; exit 1 ;;
  accepted) echo 'football-jc-review-latest-20261117-push-1300.accepted.json'; exit 0 ;;
  claimed) echo 'football-jc-review-latest-20261117-push-1300.claim.json'; exit 0 ;;
esac
exit 91
''')
            (bin/'gh').chmod(0o700)
            env={'PATH':str(bin)+':/usr/bin:/bin','GITHUB_REPOSITORY':'noki1022/mcp-sports-hub',
                 'STUB_MODE':mode,'STUB_CALLS':str(root/'calls')}
            result=subprocess.run(['/bin/bash','-eo','pipefail','-c',script],cwd=root,
                env=env,text=True,capture_output=True,timeout=5)
            return result,(root/'calls').read_text().splitlines(),list(root.glob('*.accepted.json'))

    def test_missing_or_unreadable_archive_is_blocked_not_successful_delivery(self):
        for mode in ('missing','forbidden'):
            result,calls,receipts=self.invoke(mode)
            self.assertNotEqual(result.returncode,0,(mode,result.stdout,result.stderr))
            self.assertEqual(len(calls),1)
            self.assertTrue(calls[0].startswith('api '))
            self.assertEqual(receipts,[])
        self.assertIn('FOOTBALL_REVIEW_BLOCKED_NO_VERIFIED_ARCHIVE',self.invoke('missing')[0].stdout)

    def test_existing_acceptance_or_uncertain_claim_still_prevents_another_send(self):
        for mode in ('accepted','claimed'):
            result,calls,receipts=self.invoke(mode)
            self.assertEqual(result.returncode,0,(mode,result.stdout,result.stderr))
            self.assertEqual(len(calls),1)
            self.assertEqual(receipts,[])
            self.assertNotIn('BLOCKED_NO_VERIFIED_ARCHIVE',result.stdout)


if __name__=='__main__':unittest.main()
