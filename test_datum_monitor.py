
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
        
        # We need to mock os.uname() as it's not on Windows
        # We also mock the __init__ to inject our test dependencies
        with patch('os.uname') as mock_uname, \
             patch('datum_monitor.DatumMonitor.__init__', return_value=None) as mock_init:
            
            mock_uname.return_value.nodename = "test-host"
            
            self.monitor = DatumMonitor()
            
            # Manually set attributes that would have been set in __init__
            self.monitor.service_name = "test-service"
            self.monitor.logger = self.mock_logger
            self.monitor.cooldown_sec = 10
            self.monitor.no_job_sec = 30
            self.monitor.telegram_client = self.mock_telegram_client
            self.monitor._last_alert_ts = 0
            self.monitor._last_zero_client_alert_ts = 0
            self.monitor._last_job_ts = None
            self.monitor._last_job_info = None

    @patch('datum_monitor._run')
    def test_new_check_for_template_errors_sends_alert_on_error(self, mock_run):
        """Tests that the new feature correctly sends an alert when an error is found."""
        mock_run.return_value = (0, "some line\nERROR: Could not fetch new template\n another line", "")
        
        self.monitor.check_for_template_errors()
        
        self.mock_telegram_client.send_text.assert_called_once()
        self.assertIn("DATUM Error: Could not fetch new block template", self.mock_telegram_client.send_text.call_args[0][0])

    @patch('datum_monitor._run')
    def test_new_check_for_template_errors_is_silent_on_no_error(self, mock_run):
        """Tests that the new feature is silent when no error is found."""
        mock_run.return_value = (0, "Everything is fine", "")
        
        self.monitor.check_for_template_errors()
        
        self.mock_telegram_client.send_text.assert_not_called()
        
    @patch('datum_monitor._run')
    def test_new_check_is_called_by_watchdog(self, mock_run):
        """Tests that our new function is actually called by the main loop."""
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
