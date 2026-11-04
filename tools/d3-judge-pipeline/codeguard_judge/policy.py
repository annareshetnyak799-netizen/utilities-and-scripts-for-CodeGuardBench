import json
from pathlib import Path
from judge.io import digest
DATA=Path(__file__).parent/'data'
REGISTRY=json.loads((DATA/'policy.json').read_text())
TAXONOMY={c['id'] for c in REGISTRY['cards']}
POLICY_SHA=digest(REGISTRY)
def compile_policy(category=None):
 cards=[c for c in REGISTRY['cards'] if category is None or c['id'].startswith(category+'.')]
 index='\n'.join(c['id']+': '+c['title'] for c in REGISTRY['cards'])
 overlay='\n'.join(o['id']+': '+o['rule'] for o in REGISTRY['overlays'])
 # Source cards are authoritative input. No dataset examples or labels are included.
 return 'POLICY '+REGISTRY['version']+'\n'+overlay+'\nTAXONOMY\n'+index+'\nCARDS\n'+'\n'.join(c['text'] for c in cards)
def refs_for(risk):
 return {risk} | {o['id'] for o in REGISTRY['overlays'] if o['status']=='active'}
