import gzip
import hashlib
import io
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError
from zipfile import ZipFile

from test_football_007_analysis_extract import CAP, GAME, html, source

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import restore_football_market_history as history
from football_007_analysis_extract import retry_timeout


class ArchivedFormTests(unittest.TestCase):
    def setUp(self):
        self.game = {**GAME, "jc_number": "周四010",
                     "home_team_id_007": 35, "away_team_id_007": 1078}
        self.day = CAP.date().isoformat()

    def archived(self, *, checksum_matches=True):
        page = html(source())
        digest = hashlib.sha256(page).hexdigest() if checksum_matches else "0" * 64
        archived_game = {**self.game, "analysis_source_status": "007_EMBEDDED_JSON_VALIDATED",
                         "analysis_source_evidence": {"captured_at_utc": CAP.isoformat(),
                                                      "sha256": digest}}
        raw = io.BytesIO()
        with ZipFile(raw, "w") as archive:
            archive.writestr(f'football-output/raw/analysis_{self.game["match_id"]}.html.gz',
                             gzip.compress(page))
        records = history.verified_form(raw.getvalue(), {
            "games": [archived_game], "captured_at_utc": CAP.isoformat(),
            "jc_sale_day_beijing": self.day})
        for record in records:
            record["archive_asset"] = "football-007-raw-archive.zip"
        return records

    def live(self, *, age=timedelta(hours=1), **overrides):
        return {"captured_at_utc": (CAP + age).isoformat(), "jc_sale_day_beijing": self.day,
                "games": [{**self.game, "analysis_source_status": "UNAVAILABLE_URLError",
                           "home_last5": [], "away_last5": [], "h2h": [],
                           "data_gaps": ["RECENT_FIVE_NOT_YET_PARSED", "H2H_NOT_YET_PARSED",
                                         "INJURIES_NOT_YET_VERIFIED"],
                           "injuries": [], "jc_markets": {"had": [1.5, 3.5, 4.0]},
                           **overrides}]}

    def test_verified_form_only_preserves_fresh_quotes_and_unverified_injuries(self):
        snapshot = self.live()
        self.assertEqual(history.reuse_form(snapshot, self.archived()), 1)
        game = snapshot["games"][0]
        self.assertEqual((len(game["home_last5"]), len(game["away_last5"]), len(game["h2h"])),
                         (5, 5, 1))
        self.assertEqual(game["jc_markets"]["had"], [1.5, 3.5, 4.0])
        self.assertEqual(game["injuries"], [])
        self.assertEqual(game["data_gaps"], ["INJURIES_NOT_YET_VERIFIED"])
        self.assertEqual(game["archived_form_007"]["observed_at_utc"], CAP.isoformat())
        self.assertEqual(history.reuse_form(snapshot, self.archived()), 0)

    def test_bad_hash_stale_future_or_different_fixture_is_ignored(self):
        self.assertEqual(self.archived(checksum_matches=False), [])
        records = self.archived()
        for snapshot in (self.live(age=timedelta(hours=4)), self.live(age=-timedelta(minutes=1)),
                         self.live(away_team_id_007=35), self.live(analysis_source_evidence={"fresh": True})):
            with self.subTest(snapshot=snapshot):
                self.assertEqual(history.reuse_form(snapshot, records), 0)

    def test_retry_timeout_once_without_retrying_invalid_responses(self):
        request = Mock(side_effect=[URLError(TimeoutError("handshake")), b"007"])
        self.assertEqual(retry_timeout(request, "007"), b"007")
        self.assertEqual(request.call_count, 2)
        request = Mock(side_effect=ValueError("invalid bytes"))
        with self.assertRaises(ValueError):
            retry_timeout(request, "007")
        self.assertEqual(request.call_count, 1)
        request = Mock(side_effect=TimeoutError("still unavailable"))
        with self.assertRaises(TimeoutError):
            retry_timeout(request, "007")
        self.assertEqual(request.call_count, 2)
