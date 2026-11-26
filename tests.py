#!/usr/bin/env python3
"""Finite acceptance suite: frozen holdouts, day-one regression, mutations, CLI."""
import argparse
import copy
from fractions import Fraction as F
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import audit

D=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--save',action='store_true'); args=ap.parse_args()
    start=time.monotonic(); failures=[]; records=[]; counts={}
    def check(ok,label):
        if not ok: failures.append(label)
    fixture_bytes=(D/'confirmation.json').read_bytes()
    fixture=json.loads(fixture_bytes)
    for case in fixture['cases']:
        r=audit.audit(case['input']); e=case['expected']; label=case['id']
        check(r['axes']==e['axes'],label+': axes')
        check(r['certificates']['nominal']['boundary_average']['value']==e['nominal_boundary_average'],label+': nominal value')
        check(r['certificates']['binary']['boundary_average']['value']==e['binary_boundary_average'],label+': binary value')
        check(r['certificates']['binary']['inverted_cdf']['value']==e['binary_inverted_cdf'],label+': inverted value')
        check(r['observed']['value_hex']==e['observed_hex'],label+': observation')
        if 'observed_branch' in e:
            check(r['observed']['branch_identification']==e['observed_branch'],label+': branch ambiguity')
        if 'overlap' in label:
            check(r['implementation_diagnosis']=='ARITHMETIC_ROUNDING_PRESENT',label+': arithmetic caveat')
        records.append({'id':'confirmation:'+label,'witness':r})
    counts['confirmation']=len(fixture['cases'])
    # Known tiny-weight behavior: exact dyadic inputs and normalization pairs.
    # Kept self-contained so day2 still runs without sibling study directories.
    tiny_cases = [
        ('two_point', [0,2], [F(1,2**35)]*2, F(1,4), 0, 1),
        ('importance', [0,2,8,20], [F(a,2**39) for a in (1,2,4,1)], F(1,2), 8, 14),
        ('sixteen_point', list(range(0,32,2)), [F(1,2**34)]*16, F(17,64), 8, 9),
    ]
    tiny_count = 0
    for label,x,w,p,exact,observed in tiny_cases:
        for normalized in (False,True):
            weights = [v/sum(w) for v in w] if normalized else w
            r = audit.audit({'x':x,'w':list(map(str,weights)),'p':str(p)})
            check(r['axes']=={'definition_difference':False,'input_rounding_changes_value':False,'implementation_value_mismatch':not normalized},label+': tiny axes')
            for layer in ('nominal','binary'):
                check(r['certificates'][layer]['boundary_average']['value']==str(exact),label+': tiny exact value')
            check(r['observed']['value_hex']==float(exact if normalized else observed).hex(),label+': tiny observation')
            check(r['implementation_diagnosis']==('NO_VALUE_MISMATCH' if normalized else 'TOLERANCE_ONLY_WITNESS'),label+': tiny diagnosis')
            check(r['verification']['valid'] is True,label+': tiny separate checker')
            tiny_count += 1
    counts['tiny_weights']={'observations':tiny_count,'certificates':4*tiny_count}
    for c in fixture['unsupported']:
        proc=subprocess.run([sys.executable,'-B',str(D/'audit.py')],input=json.dumps(c['input']),text=True,capture_output=True,timeout=30)
        result=json.loads(proc.stdout)
        check(proc.returncode==2 and result['status']=='UNSUPPORTED',c['id']+': unsupported CLI')
    counts['unsupported']=len(fixture['unsupported'])
    day1=json.loads((D/'fixtures'/'day1-regression.json').read_text())['records']
    for old in day1:
        r=audit.audit(old['nominal_input']); label=old['id']
        check(r['axes']=={k:old['axes'][k] for k in r['axes']},label+': day1 axes')
        check(r['certificates']['binary']['boundary_average']==old['certificate'],label+': day1 binary certificate')
        check(r['certificates']['nominal']['boundary_average']==old['nominal_certificate'],label+': day1 nominal certificate')
        check(float.fromhex(r['observed']['value_hex'])==old['observed']['release'],label+': day1 observation')
        records.append({'id':'day1:'+label,'witness':r})
    counts['day1']=len(day1)
    # Reject independent mathematical, encoding, labels and diagnostic mutations.
    import checker
    mutants=[]
    base=records[1]['witness']
    for layer in ('nominal','binary'):
        for method in ('boundary_average','inverted_cdf'):
            for field in ('left','L','U','target','W','value'):
                r=copy.deepcopy(base); c=r['certificates'][layer][method]; c[field]=str(F(c[field])+1); mutants.append(r)
            r=copy.deepcopy(base); del r['certificates'][layer][method]['kind']; mutants.append(r)
    for field in base['axes']:
        r=copy.deepcopy(base); r['axes'][field]=not r['axes'][field]; mutants.append(r)
    for field in ('tolerance_hit','has_successor','cumulative_exact','target_exact','matches_observed'):
        r=copy.deepcopy(base); r['arithmetic'][field]=not r['arithmetic'][field]; mutants.append(r)
    for field in ('target_hex','gap_hex','predicted_hex','tolerance_hex'):
        r=copy.deepcopy(base); r['arithmetic'][field]=float(7).hex(); mutants.append(r)
    for path,value in [(('hex_input','p'),float(.25).hex()),(('binary_input','p'),'1/4'),(('observed','value_hex'),float(7).hex()),(('observed','expected_hex'),float(7).hex()),(('observed','branch_identification'),'BRANCH_UNKNOWN'),(('observed','branch_candidates'),[]),(('input_rounding','changed_fields'),['p'])]:
        r=copy.deepcopy(base); r[path[0]][path[1]]=value; mutants.append(r)
    r=copy.deepcopy(base); r['arithmetic']['cumulative_hex'][0]=float(7).hex(); mutants.append(r)
    r=copy.deepcopy(base); r['implementation_diagnosis']='NO_VALUE_MISMATCH'; mutants.append(r)
    r=copy.deepcopy(records[0]['witness']); r['certificates']['binary']['boundary_average']['right']='999'; mutants.append(r)
    r=copy.deepcopy(base); r['axes']['definition_difference']=0; mutants.append(r)
    for i,r in enumerate(mutants):
        try: result=checker.validate(r)
        except (ValueError,KeyError,TypeError,OverflowError): continue
        check(result.get('valid') is False,'mutation accepted '+str(i))
    counts['mutations_rejected']=len(mutants)-sum(x.startswith('mutation accepted') for x in failures)
    counts['mutations_total']=len(mutants)
    # Public input behavior and successful standalone checker/file replay.
    entry_cases=[('{',2,'INVALID_JSON'),('NaN',2,'INVALID_JSON'),('{"x":[0],"x":[1],"w":[1],"p":"1/2"}',2,'INVALID_JSON'),(' '*65537,2,'UNSUPPORTED'),('{"x":[0],"w":[1],"p":"1e999"}',2,'UNSUPPORTED')]
    for raw,code,status in entry_cases:
        p=subprocess.run([sys.executable,'-B',str(D/'audit.py')],input=raw,text=True,capture_output=True,timeout=30)
        check(p.returncode==code and json.loads(p.stdout)['status']==status,'entry '+status)
    p=subprocess.run([sys.executable,'-B',str(D/'audit.py'),str(D/'examples'/'tolerance.json')],capture_output=True,text=True,timeout=30)
    check(p.returncode==0 and json.loads(p.stdout)['verification']['valid'] is True,'file CLI')
    p=subprocess.run([sys.executable,'-B',str(D/'checker.py')],input=json.dumps(records[0]['witness']),capture_output=True,text=True,timeout=30)
    check(p.returncode==0 and json.loads(p.stdout)['valid'] is True,'standalone checker')
    # Enforce the pinned runtime even if the underlying method could run.
    saved=audit._ENV; audit._ENV=None
    from unittest.mock import patch
    try:
        with patch('importlib.metadata.version',return_value='0.0.invalid'):
            audit.environment()
    except audit.EnvironmentUnsupported: pass
    else: failures.append('version mismatch accepted')
    audit._ENV=saved
    import replay
    from unittest.mock import mock_open
    for malformed in ({'records':[]},{'records':{}},[],1,{'records':[1]}):
        with patch.object(Path, 'open', mock_open(read_data=json.dumps(malformed).encode())):
            try: replay.replay('malformed.json')
            except ValueError: pass
            else: failures.append('malformed replay accepted '+repr(malformed))
    import fix_regressions
    fix_counts, fix_failures = fix_regressions.run()
    counts['fix_regressions'] = fix_counts
    failures.extend(fix_failures)
    counts['entry_tests']=13
    counts['certificates']=4*len(records)
    counts['axes_total']={k:sum(r['witness']['axes'][k] for r in records) for k in records[0]['witness']['axes']}
    summary={'valid':not failures,'counts':counts,'failures':failures,'confirmation_sha256':hashlib.sha256(fixture_bytes).hexdigest(),'elapsed_seconds':time.monotonic()-start}
    if args.save:
        (D/'evidence'/'acceptance.json').write_text(json.dumps(summary,indent=2)+'\n')
        (D/'evidence'/'witnesses.json').write_text(json.dumps({'schema':'audit-suite/v1','records':records},indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    return int(bool(failures))

if __name__=='__main__': sys.exit(main())
