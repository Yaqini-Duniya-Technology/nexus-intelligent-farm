import copy,json,tempfile,unittest
from pathlib import Path
from nexus.farm_app import development_tracker as t
ROOT=Path(__file__).resolve().parents[2]
class TrackerTests(unittest.TestCase):
 def setUp(self):
  self.path=ROOT/'docs/development/roadmap.json';self.data=t.read(self.path)
 def changed(self,mutate):
  with tempfile.TemporaryDirectory() as d:
   data=copy.deepcopy(self.data);mutate(data);p=Path(d)/'bad.json';p.write_text(json.dumps(data));return t.read(p)
 def test_exact_scope_and_workstream_counts(self):self.assertEqual(t.summary(self.data)['total'],150);self.assertEqual(sum(t.COUNTS.values()),150)
 def test_duplicate_id_rejected(self):
  with self.assertRaises(ValueError):self.changed(lambda d:d['upgrades'][1].update(id=d['upgrades'][0]['id']))
 def test_completion_without_evidence_rejected(self):
  with self.assertRaises(ValueError):self.changed(lambda d:d['upgrades'][6].update(status='Completed',verification=[],git_reference=None))
 def test_dependency_cycle_rejected(self):
  with self.assertRaises(ValueError):self.changed(lambda d:(d['upgrades'][0].update(dependencies=['NEXUS-UPG-002']),d['upgrades'][1].update(dependencies=['NEXUS-UPG-001'])))
 def test_unknown_dependency_rejected(self):
  with self.assertRaises(ValueError):self.changed(lambda d:d['upgrades'][0].update(dependencies=['NEXUS-UPG-999']))
 def test_read_is_readonly(self):before=self.path.read_bytes();t.read(self.path);self.assertEqual(before,self.path.read_bytes())
if __name__=='__main__':unittest.main()
