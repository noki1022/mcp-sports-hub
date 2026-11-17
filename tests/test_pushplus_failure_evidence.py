import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pushplus_mobile as push
from pushplus_five_compact import render_compact

class Reply:
    status=200
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,limit):return self.body

class FailureEvidence(unittest.TestCase):
    def test_rejection_preserves_reason_without_secret_and_sends_once(self):
        token='SECRET_TOKEN_DO_NOT_LOG_123456789'
        body=json.dumps({'code':999,'msg':'频率限制 token='+token}).encode()
        with patch.object(push.urllib.request,'urlopen',return_value=Reply(body)) as request:
            with self.assertRaises(push.PushPlusSendError) as error:
                push.send({'title':'test','html':'<p>内容</p>'},token)
        request.assert_called_once()
        details=error.exception.details
        self.assertEqual(details['state'],'SEND_FAILED')
        self.assertEqual(details['api_code'],999)
        self.assertIn('频率限制',details['provider_message'])
        self.assertNotIn(token,json.dumps(details)+str(error.exception))
        self.assertEqual(details['content_sha256'],hashlib.sha256('<p>内容</p>'.encode()).hexdigest())
        self.assertIn('requested_at_utc',details)
        self.assertNotIn('accepted_at_utc',details)

    def test_network_unknown_does_not_retry(self):
        with patch.object(push.urllib.request,'urlopen',side_effect=URLError('secret URL')) as request:
            with self.assertRaises(push.PushPlusSendError) as error:
                push.send({'title':'test','html':'body'},'secret')
        request.assert_called_once()
        self.assertEqual(error.exception.details['state'],'SEND_OUTCOME_UNKNOWN')
        self.assertNotIn('secret URL',str(error.exception))

    def test_acceptance_is_distinct_from_device_delivery(self):
        with patch.object(push.urllib.request,'urlopen',return_value=Reply(b'{"code":200,"data":"short-code"}')):
            result=push.send({'title':'test','html':'body'},'secret')
        self.assertEqual(result['state'],'API_ACCEPTED_NOT_DEVICE_CONFIRMED')
        self.assertIn('accepted_at_utc',result)

    def test_status_can_be_written_before_output_directory_exists(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'nested'/'failure.json'
            push.save_status(path,{'state':'SEND_FAILED','api_code':999})
            self.assertEqual(json.loads(path.read_text())['api_code'],999)

    def test_real_snapshot_time_distinguishes_hourly_reports(self):
        game={'game_id':'1','home_team':'A','away_team':'B','start_time_beijing':'2026-11-18T09:00:00+08:00'}
        a=render_compact([game],{},'NBA','2026-11-18','three',snapshot_utc='2026-11-17T08:00:00Z')
        b=render_compact([game],{},'NBA','2026-11-18','three',snapshot_utc='2026-11-17T09:00:00Z')
        self.assertIn('11-17 16:00',a)
        self.assertIn('11-17 17:00',b)
        self.assertNotEqual(a,b)

if __name__=='__main__':unittest.main()
