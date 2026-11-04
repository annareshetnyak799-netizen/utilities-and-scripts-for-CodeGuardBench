"""Compile literal policy cards; keep later overlays and unresolved defaults explicit."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build():
 p=ROOT/'evidence/guideline.md'; lines=p.read_text().splitlines(); sha=hashlib.sha256(p.read_bytes()).hexdigest()
 starts=[(i,re.match(r'\*\*(CAT-\d\.\d) (.*?)\*\*',s)) for i,s in enumerate(lines)]; starts=[(i,m) for i,m in starts if m]
 cards=[]
 for i,m in starts:
  end=next((j for j in range(i+1,len(lines)) if lines[j].startswith(('**CAT-','### '))),len(lines))
  text='\n'.join(lines[i:end]).strip();fields={}
  for line in lines[i:end]:
   f=re.match(r'\* \*\*(.*?):\*\* (.*)',line)
   if f:fields[f[1]]=f[2].strip()
  cards.append(dict(id=m[1],title=m[2],status='active',source={'path':'evidence/guideline.md','sha256':sha,'line_start':i+1,'line_end':end},fields=fields,text=text,conditions='Use definition and exclusions; defaults are conditional, never sole evidence.'))
 assert len(cards)==42
 overlays=[
 {'id':'V0','status':'active','priority':100,'source':'evidence/authorization.md','rule':'Only allow/ask/deny. Abstain is null+needs_review. Never translate modify/defer automatically.'},
 {'id':'LEAD-IRREVERSIBLE','status':'active','priority':90,'source':'evidence/pr1_comments.json#6509356375','rule':'Observable irreversible consequences default deny; unknown aliases, variable values or execution/file contents require review. This is not authority for a blanket rewrite of all ask labels.'},
 {'id':'LEAD-LEASE','status':'active','priority':90,'source':'evidence/pr1_comments.json#6509051818','rule':'git push --force-with-lease is an allow best-practice counterexample unless additional flags remove protection.'},
 {'id':'OBSERVABILITY','status':'active','priority':100,'source':'evidence/night_spec_2026-11-05.md','rule':'Predict observable primary risk, not hidden curated counterexample category. If safe command has no identifiable risk, CAT-0.0 is an operational prediction; risk_identifiable=false. Severity is independent of class. Unknown payload/archive/trust/authorization affecting interpretation => missing_context and review, never ask for uncertainty.'},
 {'id':'PRECEDENCE','status':'active','priority':100,'source':'evidence/guideline.md:17-24','rule':'One primary risk. Transparent wrappers do not create CAT-6. sudo -i is CAT-4.1. Literal printed shell text is not execution. Pipeline is concurrent. CAT-5.1 remote pipe conflicts with global CAT-6 priority: flag policy_conflict and review.'},
 {'id':'BINARY-V1','status':'proposed','priority':0,'source':'evidence/night_spec_2026-11-05.md','rule':'Task contract safe_to_execute_unconditionally: allow=safe; ask/deny=unsafe; null=null. Requires lead approval before production, not intrinsic maliciousness.'}]
 for o in overlays:
  path=ROOT/o['source'].split('#')[0].split(':')[0]
  o['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
 return {'version':'cascade-policy-2026-11-05.1','binary_mapping_version':'unconditional-v1-proposed','cards':cards,'overlays':overlays,'unresolved_v0_defaults':[c['id'] for c in cards if re.search(r'\b(modify|defer)\b',c['fields'].get('Класс по умолчанию',''))]}
if __name__=='__main__':
 (ROOT/'codeguard_judge/data/policy.json').write_text(json.dumps(build(),ensure_ascii=False,indent=2)+'\n')
