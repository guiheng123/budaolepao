"""Offline lifecycle/template regression tests: python -m unittest discover -s mobile."""
import threading
import unittest
from unittest.mock import patch

import hook


class FakeScript:
    def on(self, *args):
        pass

    def load(self):
        pass


class FakeSession:
    def __init__(self):
        self.detaches = 0

    def on(self, *args):
        pass

    def create_script(self, source):
        return FakeScript()

    def detach(self):
        self.detaches += 1


class ClientTests(unittest.TestCase):
    def test_certificate_template(self):
        path, cert = hook.read_cert_hex()
        source = hook.build_script(cert)
        self.assertNotIn('__CERT_HEX__', source)
        self.assertIn(cert, source)
        for invalid in ('', 'abc', 'zz'):
            with self.assertRaises(ValueError):
                hook.build_script(invalid)

    def test_cleanup_detaches(self):
        session = FakeSession()
        sessions = {1: (session, FakeScript(), threading.Event())}
        hook.cleanup(sessions)
        self.assertEqual(session.detaches, 1)
        self.assertFalse(sessions)

    def test_failed_connection_removed(self):
        from unittest.mock import Mock
        api = Mock()
        manager = api.get_device_manager.return_value
        manager.add_remote_device.return_value.enumerate_processes.side_effect = RuntimeError('offline')
        with patch.object(hook, 'frida', api):
            with self.assertRaises(RuntimeError):
                hook.connect('test:123')
        manager.remove_remote_device.assert_called_once_with('test:123')

    def test_positive_interval(self):
        import argparse
        for value in ('0', '-1', 'nan', 'inf'):
            with self.assertRaises(argparse.ArgumentTypeError):
                hook.positive(value)
        self.assertEqual(hook.positive('0.5'), 0.5)

    def test_load_failure_detaches(self):
        from unittest.mock import Mock
        api = Mock()
        device = api.get_device_manager.return_value.add_remote_device.return_value
        process = Mock(pid=42)
        process.name = 'test.proc'
        device.enumerate_processes.return_value = [process]
        session = device.attach.return_value
        session.create_script.return_value.load.side_effect = RuntimeError('bad script')
        with patch.object(hook, 'frida', api):
            self.assertEqual(hook.main(['--proc', 'test.proc', '--duration', '0.01']), 0)
        session.detach.assert_called_once()


if __name__ == '__main__':
    unittest.main()
