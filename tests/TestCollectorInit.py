import sys
import os
import unittest
import importlib
import types

sys.path.append('.')
from unittest import TestCase
from unittest.mock import call, patch, MagicMock
import collectors.VMStatsCollector
from exporter import initialize_collector_by_name

class TestCollectorInitialization(TestCase):

    @patch('BaseCollector.BaseCollector.wait_for_inventory_data')
    def test_valid_collector(self, mocked_wait):
        mocked_wait.return_value = None
        collector = initialize_collector_by_name('VMStatsCollector')
        self.assertIsInstance(collector, collectors.VMStatsCollector.VMStatsCollector)

    # the collector crashes during initialization
    @patch('BaseCollector.BaseCollector.wait_for_inventory_data')
    @patch('builtins.print')
    def test_crashing_collector(self, mocked_print, mocked_wait):
        mocked_wait.side_effect = RuntimeError("__init__ crashed")
        collector = initialize_collector_by_name('VMStatsCollector')
        self.assertIsNone(collector)
        self.assertEqual(mocked_print.mock_calls, [call('Unable to initialize "VMStatsCollector". Ignoring...')])

    # do not crash if the user provides a non existing collector
    @patch('builtins.print')
    def test_with_bogus_collector(self, mocked_print):
        collector = initialize_collector_by_name('BogusCollector')
        self.assertIsNone(collector)
        self.assertEqual(mocked_print.mock_calls, [call('No Collector "BogusCollector" defined. Ignoring...')])

    @patch('builtins.print')
    def test_with_invalid_collector(self, mocked_print):
        importlib.import_module = MagicMock(return_value=collectors.VMStatsCollector)
        collector = initialize_collector_by_name('ClassNotDefinedCollector')
        self.assertIsNone(collector)
        self.assertEqual(mocked_print.mock_calls, [call('Unable to initialize "ClassNotDefinedCollector". Ignoring...')])

if __name__ == '__main__':
    unittest.main()
