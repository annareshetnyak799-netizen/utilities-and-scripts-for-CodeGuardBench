import importlib.util,json
from pathlib import Path
SPEC=importlib.util.spec_from_file_location('adapt',Path(__file__).resolve().parents[1]/'scripts/adapt_candidates.py');module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)
def test_d1_keeps_labels_out_of_blind_and_preserves_text(tmp_path):
 row={'record_id':'one','command':'printf "a  b"','class':'deny','risk':'CAT-9.9','split':'test','family_id':'family','warnings':['label_conflict']}
 r=module.adapt([row],'d1',tmp_path/'out');assert r['accepted']==1
 b=json.loads((tmp_path/'out/blind_inputs.jsonl').read_text());assert b=={'record_id':'one','command':row['command']}
 assert 'label_conflict' in (tmp_path/'out/provenance.jsonl').read_text()
def test_d2_requires_privacy_owner_review(tmp_path):
 r=module.adapt([{'record_id':'x','command':'pwd','source':'local'}],'d2',tmp_path/'out')
 assert r['accepted']==0 and r['quarantine']==1
