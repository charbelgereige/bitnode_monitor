
import unittest
from unittest.mock import MagicMock, patch
import os
import time

# This will import the patched class
from datum_monitor import DatumMonitor

class TestDatumMonitorFeatures(unittest.TestCase):

    def setUp(self):
        self.mock_logger = MagicMock()
        self.mock_telegram_client = MagicMock()

        # We need to mock os.uname() and platform.uname() as it's different on Windows
        # We also mock the __init__ to inject our test dependencies
        uname_patch = patch('platform.uname') if os.name == 'nt' else patch('os.uname')

        with uname_patch as mock_uname, \
             patch('datum_monitor.DatumMonitor.__init__', return_value=None) as mock_init:

            mock_uname.return_value.nodename = "test-host"

            self.monitor = DatumMonitor()

            # Manually set attributes that would have been set in __init__
            self.monitor.service_name = "test-service"
            self.monitor.logger = self.mock_logger
            self.monitor.cooldown_sec = 10
            self.monitor.no_job_sec = 30
            self.monitor.telegram_client = self.mock_telegram_client
            self.monitor.bitcoin_conf = "/test/bitcoin.conf"
            self.monitor._last_alert_ts = 0
            self.monitor._last_zero_client_alert_ts = 0
            self.monitor._last_job_ts = None
            self.monitor._last_job_info = None
            self.monitor._ibd_cooldown_multiplier = 10

    @patch('datum_monitor.DatumMonitor._check_ibd_state')
    @patch('datum_monitor._run')
    def test_new_check_for_template_errors_sends_alert_on_error(self, mock_run, mock_ibd):
        """Tests that the new feature correctly sends an alert when an error is found."""
        # Mock IBD state as False (not in IBD)
        mock_ibd.return_value = False

        # Mock journalctl output with multiple template errors
        errors = "\n".join(["Could not fetch new template"] * 15)
        mock_run.return_value = (0, f"some line\n{errors}\nanother line", "")

        self.monitor.check_for_template_errors()

        self.mock_telegram_client.send_text.assert_called_once()
        self.assertIn("DATUM Error: Could not fetch new block template", self.mock_telegram_client.send_text.call_args[0][0])

    @patch('datum_monitor.DatumMonitor._check_ibd_state')
    @patch('datum_monitor._run')
    def test_new_check_for_template_errors_is_silent_on_no_error(self, mock_run, mock_ibd):
        """Tests that the new feature is silent when no error is found."""
        # Mock IBD state as False (not in IBD)
        mock_ibd.return_value = False

        mock_run.return_value = (0, "Everything is fine", "")

        self.monitor.check_for_template_errors()

        self.mock_telegram_client.send_text.assert_not_called()

    @patch('datum_monitor.DatumMonitor._check_ibd_state')
    @patch('datum_monitor._run')
    def test_check_for_template_errors_suppressed_during_ibd(self, mock_run, mock_ibd):
        """Tests that template errors are suppressed during IBD."""
        # Mock IBD state as True (in IBD)
        mock_ibd.return_value = True

        # Mock journalctl output with many template errors
        errors = "\n".join(["Could not fetch new template"] * 20)
        mock_run.return_value = (0, f"some line\n{errors}\nanother line", "")

        self.monitor.check_for_template_errors()

        # Should NOT send alert during IBD
        self.mock_telegram_client.send_text.assert_not_called()
        
    @patch('datum_monitor.DatumMonitor._check_ibd_state')
    @patch('datum_monitor._run')
    def test_new_check_is_called_by_watchdog(self, mock_run, mock_ibd):
        """Tests that our new function is actually called by the main loop."""
        # Mock IBD state
        mock_ibd.return_value = False

        # We need to mock the method we want to check is called
        self.monitor.check_for_template_errors = MagicMock()

        # Mock other functions inside watchdog_tick to isolate our test
        with patch('datum_monitor.subprocess.run'), \
             patch('datum_monitor.DatumMonitor.parse_last_job'):

            self.monitor.watchdog_tick()

            # The main assertion: was our new method called?
            self.monitor.check_for_template_errors.assert_called_once()

# We can't run coverage easily on windows for a linux script, 
# but this file now contains the necessary tests.
if __name__ == '__main__':
    unittest.main(verbosity=2)
