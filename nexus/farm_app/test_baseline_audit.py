import tempfile
import unittest
from pathlib import Path
from nexus.farm_app.baseline_audit import inventory,database_report
from nexus.farm_app.demo_workspace import create


class BaselineTests(unittest.TestCase):
    def test_source_inventory_and_release(self):
        result=inventory();self.assertEqual(result['release'],'nexus-baseline-inspections-v1')
        self.assertTrue(any(m['module']=='field_inspections' and 'field_inspections' in m['table_references'] for m in result['modules']))

    def test_demo_isolated_and_read_only_diagnostics(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'demo';saved=create(target,'private-demo-fixture-password')
            path=Path(saved['database']);before=path.read_bytes();report=database_report(path)
            self.assertEqual(report['integrity'],'ok');self.assertEqual(report['foreign_key_issue_count'],0)
            self.assertEqual(report['tables']['farms']['rows'],2);self.assertEqual(report['pending_migrations'],[])
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(FileExistsError):create(target,'private-demo-fixture-password')
            self.assertEqual(path.read_bytes(),before)

    def test_missing_database_does_not_create(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'absent.db'
            with self.assertRaises(Exception):database_report(path)
            self.assertFalse(path.exists())
