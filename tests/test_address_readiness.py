import errno
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from wait_for_address import wait_for_address

class AddressReadinessTests(unittest.TestCase):
    def test_ready_address_returns_immediately(self):
        probe=Mock();probe.__enter__=Mock(return_value=probe);probe.__exit__=Mock(return_value=False)
        factory=Mock(return_value=probe);sleep=Mock()
        wait_for_address('192.168.4.1',factory=factory,sleep=sleep)
        probe.bind.assert_called_once_with(('192.168.4.1',0));sleep.assert_not_called()
    def test_unavailable_address_is_retried_then_ready(self):
        probe=Mock();probe.__enter__=Mock(return_value=probe);probe.__exit__=Mock(return_value=False)
        probe.bind.side_effect=[OSError(errno.EADDRNOTAVAIL,'not ready'),None]
        sleep=Mock();wait_for_address('192.168.4.1',factory=lambda *a:probe,sleep=sleep)
        self.assertEqual(probe.bind.call_count,2);sleep.assert_called_once()
    def test_unavailable_address_times_out(self):
        probe=Mock();probe.__enter__=Mock(return_value=probe);probe.__exit__=Mock(return_value=False)
        probe.bind.side_effect=OSError(errno.EADDRNOTAVAIL,'not ready')
        with self.assertRaises(TimeoutError):wait_for_address('192.168.4.1',timeout=0,clock=lambda:0,factory=lambda *a:probe)
    def test_permissions_are_not_bypassed(self):
        probe=Mock();probe.__enter__=Mock(return_value=probe);probe.__exit__=Mock(return_value=False)
        probe.bind.side_effect=OSError(errno.EACCES,'denied')
        with self.assertRaises(OSError):wait_for_address('192.168.4.1',factory=lambda *a:probe)
    def test_public_or_ipv6_address_rejected(self):
        for address in ['8.8.8.8','::1']:
            with self.assertRaises(ValueError):wait_for_address(address)

if __name__=='__main__':unittest.main()
