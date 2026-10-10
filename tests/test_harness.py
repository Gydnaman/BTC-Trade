import unittest
import tempfile
from pathlib import Path


class HarnessTests(unittest.TestCase):
    def test_validation_detects_failure(self):
        from harness.validate import run_suite
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test_deliberate_failure.py'
            path.write_text('import unittest\nclass T(unittest.TestCase):\n def test_failure(self): self.fail("sentinel")\n')
            report = run_suite(Path(tmp))
            self.assertFalse(report['passed'])
            self.assertEqual(report['failures'], 1)

    def test_standard_library_signal_available(self):
        import signal
        self.assertTrue(hasattr(signal, 'SIGINT'))


if __name__ == '__main__':
    unittest.main()
