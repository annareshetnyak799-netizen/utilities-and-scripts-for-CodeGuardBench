"""Group-preserving stratification of synthetic train pool. Test is rejected."""
import argparse
import collections
import random
from .io import read_records, dump
from .static import features

def select(rows, fraction=.2, seed=20261101):
    if not 0<fraction<1:raise ValueError('invalid_fraction')
    groups=collections.defaultdict(list)
    for row in rows:
        if row.get('source')!='synthetic' or row.get('split') not in ('train','val') or not row.get('family_id'):
            raise ValueError('only_synthetic_train_families')
        groups[row['family_id']].append(row)
    # A family may span strata. Assign whole groups; report residual imbalance.
    strata=collections.defaultdict(list)
    for family, members in groups.items():
        signature=tuple(sorted({(x['risk'],x['class']) for x in members}));strata[signature].append(family)
    rng=random.Random(seed);val=set();small=[]
    for signature, families in sorted(strata.items()):
        families=sorted(families);rng.shuffle(families)
        if len(families)<2:small.append(signature);continue
        val.update(families[:max(1,min(len(families)-1,round(len(families)*fraction)))])
    train=[x for x in rows if x['family_id'] not in val];valid=[x for x in rows if x['family_id'] in val]
    hard=[x for x in valid if any(features(x['command']).values()) or x.get('hard_negative')]
    return dict(train_ids=[x['record_id'] for x in train],val_ids=[x['record_id'] for x in valid],val_early_stop_candidate_ids=[x['record_id'] for x in hard],small_strata=small,seed=seed,policy='family-disjoint stratification; hard features are candidates, not measured difficulty')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--fraction',type=float,default=.2);a=p.parse_args();dump(a.output,select(read_records(a.input),a.fraction))
