import time
import unittest
from unittest.mock import MagicMock, patch

import requests

from bitaxe_checker import BitaxeChecker


class MockResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def healthy_response():
    return MockResponse(
        {
            "hashRate": 1200,
            "sharesAccepted": 8,
            "sharesRejected": 0,
            "isUsingFallbackStratum": 0,
            "stratumURL": "primary.example",
            "stratumPort": 3333,
            "fallbackStratumURL": "fallback.example",
            "fallbackStratumPort": 3333,
            "temp": 53,
            "voltage": 5100,
            "power": 16,
        }
    )


class TestBitaxeCheckerReachability(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.telegram = MagicMock()
        self.checker = BitaxeChecker(
            "http://192.168.68.102",
            self.logger,
            telegram_client=self.telegram,
            alert_cooldown_sec=0,
            consecutive_failure_threshold=3,
        )
        self.checker._last_daily_summary_ts = time.time()

    @patch("bitaxe_checker.requests.get")
    def test_reachability_alert_requires_consecutive_failures(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectTimeout("timed out")

        for _ in range(2):
            snap, alert = self.checker.tick()
            self.assertFalse(snap.ok)
            self.assertIsNone(alert)

        self.telegram.send_text.assert_not_called()

        snap, alert = self.checker.tick()

        self.assertFalse(snap.ok)
        self.assertIn("after 3 consecutive failed polls", alert)
        self.telegram.send_text.assert_called_once()

    @patch("bitaxe_checker.requests.get")
    def test_success_resets_non_alerted_failures_without_recovery_alert(self, mock_get):
        mock_get.side_effect = [
            requests.exceptions.ReadTimeout("timed out"),
            healthy_response(),
        ]

        first_snap, first_alert = self.checker.tick()
        second_snap, second_alert = self.checker.tick()

        self.assertFalse(first_snap.ok)
        self.assertIsNone(first_alert)
        self.assertTrue(second_snap.ok)
        self.assertIsNone(second_alert)
        self.telegram.send_text.assert_not_called()
        self.assertEqual(self.checker._consecutive_fetch_failures, 0)

    @patch("bitaxe_checker.requests.get")
    def test_recovery_alert_after_sustained_reachability_alert(self, mock_get):
        mock_get.side_effect = [
            requests.exceptions.ReadTimeout("timed out"),
            requests.exceptions.ReadTimeout("timed out"),
            requests.exceptions.ReadTimeout("timed out"),
            healthy_response(),
        ]

        for _ in range(3):
            self.checker.tick()

        snap, alert = self.checker.tick()

        self.assertTrue(snap.ok)
        self.assertEqual(alert, "[BITAXE] ✅ AxeOS reachable again at http://192.168.68.102.")
        self.assertEqual(self.telegram.send_text.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
