"""Create review-only ZIP; preserve frozen originals and report every sanitization."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/cascade_2026-11-05';ZIP=ROOT.parents[2]/'exports/CodeGuardBench_Cascade_Review_2026-11-05.zip'
FILES=[]
for d in ['codeguard_judge','judge','tests','scripts','evidence','data','policy']:
 for p in (ROOT/d).rglob('*'):
  if p.is_file() and p.suffix in ('.py','.json','.jsonl','.md','.txt') and '__pycache__' not in p.parts and 'model_cards' not in p.parts and 'configs' not in p.parts:FILES.append(p)
FILES += [ROOT/'pyproject.toml',ROOT/'requirements.txt',ROOT/'DEMO.md']
for p in OUT.rglob('*'):
 if p.name in ('bundle_receipt.json','zip_verification.json'):continue
 if not p.is_file() or p.suffix not in ('.json','.jsonl','.md','.txt','.csv'):continue
 rel=p.relative_to(OUT)
 if rel.parts[0] in ('discovery','full_mock','full_rules','release_full_mock','release_full_rules','clean_install_demo','release_install_demo'):
  if p.name not in ('metrics.json','pipeline_health.json','actual.json','expected.json','run_manifest.json','doctor.json'):continue
 if 'snapshots' in rel.parts:continue
 if p.name in ('references.jsonl','eligible_references.jsonl','blind_inputs.jsonl') and 'discovery_v2' in rel.parts:continue
 FILES.append(p)
manifest=[];ZIP.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(ZIP,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(set(FILES)):
  raw=p.read_bytes();text=raw.decode();safe=text.replace(str(ROOT),'.').replace('/Users/dekovaleva/GigaChat/CodeBench','CODEBENCH_WORKSPACE').replace('/Users/dekovaleva/GigaChat/.proxyapi/access_token.py','LOCAL_CREDENTIAL_FILE_REQUIRED').replace('/Users/dekovaleva','LOCAL_USER_HOME');packed=safe.encode()
  rel=str(p.relative_to(ROOT));z.writestr(rel,packed);manifest.append({'path':rel,'source_sha256':hashlib.sha256(raw).hexdigest(),'packaged_sha256':hashlib.sha256(packed).hexdigest(),'paths_sanitized':packed!=raw})
 z.writestr('BUNDLE_MANIFEST.json',json.dumps(manifest,indent=2))
 z.writestr('READ_ME_FIRST.md','# Review bundle, 2026-11-05\n\nStart with DEMO.md and reports/cascade_2026-11-05/HANDOFF_2026-11-05.md. Human gold=0; annotation agreement is not accuracy. No auto-export.\n\nThis is a review copy. Personal absolute paths were sanitized; BUNDLE_MANIFEST records original and packaged SHA256 separately. Frozen run manifests refer to the original workspace: do not resume those runs from this sanitized ZIP. Use a NEW output directory for offline demo. No credentials, private logs, weights, remote execution, or paid calls are required for demo. API configurations need your own explicit setup and budget.\n\nPeer source CSV blobs omitted for size; commit/path/SHA references remain in inventory. Pilot public commands and raw structured decisions are included for independent audit. Do not show human reviewers the reference key before their own annotation.\n')
print(json.dumps({'zip':str(ZIP),'files':len(manifest),'bytes':ZIP.stat().st_size,'sha256':hashlib.sha256(ZIP.read_bytes()).hexdigest()}))
