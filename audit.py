#!/usr/bin/env python3
"""Audit small positive-weight quantiles. JSON in, checked JSON witness out."""
import argparse
from fractions import Fraction as F
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

D = Path(__file__).resolve().parent
SCHEMA = 'weighted-quantile-audit/v1'
LIMIT = 65536
_OVERSIZED_INTEGER = object()
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

class Unsupported(ValueError):
    pass

class EnvironmentUnsupported(ValueError):
    pass

def bounded_json_integer(token):
    # JSON has already recognized an integer token. Avoid Python's decimal
    # conversion limit without disabling it or allocating an unbounded int.
    # Keep parsing: a later syntax error or duplicate key is still INVALID_JSON.
    if len(token.lstrip('-')) > 39:  # 2**128 - 1 has 39 decimal digits
        return _OVERSIZED_INTEGER
    return int(token)

def parse_number(v):
    if v is _OVERSIZED_INTEGER:
        raise Unsupported('integer exceeds 128 bits')
    if type(v) is int:
        if v.bit_length() > 128:
            raise Unsupported('integer exceeds 128 bits')
        return F(v)
    if not isinstance(v, str) or len(v) > 96 or not re.fullmatch(r'[+-]?(?:\d+(?:/\d+)?|\d*\.\d+)(?:[eE][+-]?\d{1,3})?', v):
        raise Unsupported('numbers must be integers or finite rational/decimal strings (max 96 characters)')
    # Bound decimal exponents before Fraction allocates powers of ten.
    if 'e' in v.lower() and abs(int(v.lower().split('e')[1])) > 128:
        raise Unsupported('decimal exponent outside -128..128')
    try:
        f = F(v)
    except (ValueError, ZeroDivisionError) as exc:
        raise Unsupported('invalid rational') from exc
    if max(f.numerator.bit_length(), f.denominator.bit_length()) > 128:
        raise Unsupported('normalized rational exceeds 128 bits')
    return f

def parse_input(doc):
    if not isinstance(doc, dict) or set(doc) != {'x', 'w', 'p'}:
        raise Unsupported('expected exactly x, w, p')
    if not isinstance(doc['x'], list) or not isinstance(doc['w'], list) or not 1 <= len(doc['x']) <= 16 or len(doc['x']) != len(doc['w']):
        raise Unsupported('x and w must be equal-length 1D arrays of length 1..16')
    x, w, p = list(map(parse_number, doc['x'])), list(map(parse_number, doc['w'])), parse_number(doc['p'])
    if not all(v > 0 for v in w) or not 0 < p < 1:
        raise Unsupported('positive weights and 0 < p < 1 required')
    if not all(math.isfinite(float(v)) for v in x+w+[p]) or not all(float(v) > 0 for v in w) or not 0 < float(p) < 1:
        raise Unsupported('binary64 conversion must stay finite, weights positive, probability interior')
    return {'x': list(map(str, x)), 'w': list(map(str, w)), 'p': str(p)}

def binary_input(inp):
    return {k: [str(F(float(F(z)))) for z in inp[k]] for k in ('x', 'w')} | {'p': str(F(float(F(inp['p']))))}

def hex_input(inp):
    return {k: [float(F(z)).hex() for z in inp[k]] for k in ('x', 'w')} | {'p': float(F(inp['p'])).hex()}

def certificates(inp):
    masses = {}
    for x, w in zip(map(F, inp['x']), map(F, inp['w'])):
        masses[x] = masses.get(x, F(0)) + w
    values = sorted(masses)
    W = sum(masses.values(), F(0)); target = F(inp['p']) * W; L = F(0)
    for j, left in enumerate(values):
        U = L + masses[left]
        if target <= U:
            tie = target == U
            right = values[j+1] if tie else None
            base = {'kind': 'tie' if tie else 'point', 'left': str(left), 'right': str(right) if tie else None,
                    'L': str(L), 'U': str(U), 'W': str(W), 'target': str(target)}
            return {'boundary_average': base | {'value': str((left+right)/2 if tie else left)},
                    'inverted_cdf': base | {'value': str(left)}}
        L = U
    raise RuntimeError('unreachable exact target')

_ENV = None

def environment():
    global _ENV
    if _ENV is not None:
        return _ENV
    if sys.version_info[:2] != (3, 12):
        raise EnvironmentUnsupported('requires Python 3.12')
    lock = json.loads((D/'runtime-lock.json').read_text())
    versions = {}
    for name, expected in lock['distributions'].items():
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise EnvironmentUnsupported('missing dependency: '+name) from exc
        if versions[name] != expected:
            raise EnvironmentUnsupported('dependency version mismatch: '+name)
    import statsmodels.stats.weightstats as ws
    digest = hashlib.sha256(Path(ws.__file__).read_bytes()).hexdigest()
    if digest != lock['weightstats_sha256']:
        raise EnvironmentUnsupported('statsmodels weightstats module hash mismatch')
    _ENV = {'python': sys.version.split()[0], 'distributions': versions, 'weightstats_sha256': digest}
    return _ENV

def produce(doc):
    nominal = parse_input(doc)
    env = environment()
    import numpy as np
    import pandas as pd
    from statsmodels.stats.weightstats import DescrStatsW
    binary = binary_input(nominal)
    cert = {'nominal': certificates(nominal), 'binary': certificates(binary)}
    x = np.array([float(F(v)) for v in binary['x']], dtype=np.float64)
    w = np.array([float(F(v)) for v in binary['w']], dtype=np.float64)
    p = float(F(binary['p']))
    actual = float(DescrStatsW(x, w).quantile([p], return_pandas=False)[0])
    expected = float(F(cert['binary']['boundary_average']['value']))
    support = sorted(set(map(F, binary['x'])))
    candidates = [('point:'+str(v), float(v)) for v in support]
    candidates += [('tie:'+str(a)+','+str(b), (float(a)+float(b))/2) for a,b in zip(support,support[1:])]
    matching = [label for label,value in candidates if value == actual]
    branch = matching[0] if len(matching) == 1 else 'BRANCH_UNKNOWN'
    # Reproduce the pinned method's arithmetic; this is not instrumentation.
    df = pd.DataFrame({'weights': w, 'vec': x}).groupby('vec').agg('sum')
    cumulative = np.cumsum(df.values[:,0]); target = p*cumulative[-1]
    j = int(np.searchsorted(cumulative, target)); gap = abs(float(target)-float(cumulative[j]))
    hit = gap < 1e-10; successor = j < len(support)-1
    predicted = (float(support[j])+float(support[j+1]))/2 if hit and successor else float(support[j])
    exact_cw = [sum((F(b) for a,b in zip(binary['x'],binary['w']) if F(a)<=v), F(0)) for v in support]
    arithmetic = {'support': list(map(str,support)), 'cumulative_hex': [float(v).hex() for v in cumulative],
                  'target_hex': float(target).hex(), 'selected_index': j, 'gap_hex': gap.hex(),
                  'tolerance_hex': float(1e-10).hex(), 'tolerance_hit': hit, 'has_successor': successor,
                  'cumulative_exact': all(F(float(a))==b for a,b in zip(cumulative,exact_cw)),
                  'target_exact': F(float(target))==F(cert['binary']['boundary_average']['target']),
                  'predicted_hex': predicted.hex(), 'matches_observed': predicted==actual}
    axes = {'definition_difference': F(cert['binary']['boundary_average']['value']) != F(cert['binary']['inverted_cdf']['value']),
            'input_rounding_changes_value': F(cert['nominal']['boundary_average']['value']) != F(cert['binary']['boundary_average']['value']),
            'implementation_value_mismatch': actual != expected}
    diagnosis = 'NO_VALUE_MISMATCH'
    if axes['implementation_value_mismatch']:
        if arithmetic['cumulative_exact'] and arithmetic['target_exact'] and gap != 0 and hit and successor and predicted==actual and branch!='BRANCH_UNKNOWN':
            diagnosis = 'TOLERANCE_ONLY_WITNESS'
        elif not (arithmetic['cumulative_exact'] and arithmetic['target_exact']):
            diagnosis = 'ARITHMETIC_ROUNDING_PRESENT'
        else:
            diagnosis = 'UNRESOLVED'
    changes = [f'{key}[{i}]' for key in ('x','w') for i,(a,b) in enumerate(zip(nominal[key],binary[key])) if F(a)!=F(b)]
    if nominal['p'] != binary['p']:
        changes.append('p')
    return {'schema': SCHEMA, 'status':'OK', 'nominal_input':nominal, 'binary_input':binary, 'hex_input':hex_input(binary),
            'certificates':cert, 'axes':axes, 'input_rounding':{'changed_fields':changes},
            'observed':{'value_hex':actual.hex(), 'expected_hex':expected.hex(), 'branch_candidates':matching, 'branch_identification':branch},
            'arithmetic':arithmetic, 'implementation_diagnosis':diagnosis, 'environment':env,
            'source':{name+'_sha256':hashlib.sha256((D/(name+'.py')).read_bytes()).hexdigest() for name in ('audit','checker')}}

def independent_check(record):
    proc = subprocess.run([sys.executable, '-B', str(D/'checker.py')], input=json.dumps(record), text=True,
                          capture_output=True, timeout=30, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    try:
        result = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError('checker did not return JSON') from exc
    if proc.returncode or result.get('valid') is not True:
        raise RuntimeError('independent checker rejected: '+str(result))
    return result

def audit(doc):
    record = produce(doc)
    record['verification'] = independent_check(record)
    return record

def unique_object(pairs):
    out = {}
    for key,value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key: '+key)
        out[key] = value
    return out

def reject_constant(value):
    raise ValueError('nonfinite JSON constant: '+value)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path', nargs='?', default='-', help='input JSON file or - for stdin')
    args = ap.parse_args()
    try:
        if args.path == '-':
            raw = sys.stdin.buffer.read(LIMIT+1)
        else:
            with open(args.path, 'rb') as h:
                raw = h.read(LIMIT+1)
        if len(raw)>LIMIT:
            raise Unsupported('input exceeds 64 KiB')
        try:
            doc = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant,
                             parse_int=bounded_json_integer)
        except (ValueError, UnicodeError, RecursionError) as exc:
            print(json.dumps({'schema':SCHEMA,'status':'INVALID_JSON','reason':str(exc)})); return 2
        result = audit(doc); code = 0
    except Unsupported as exc:
        result = {'schema':SCHEMA,'status':'UNSUPPORTED','reason':str(exc)}; code = 2
    except (EnvironmentUnsupported, ImportError) as exc:
        result = {'schema':SCHEMA,'status':'ENVIRONMENT_UNSUPPORTED','reason':str(exc)}; code = 3
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        result = {'schema':SCHEMA,'status':'ERROR','reason':str(exc)}; code = 4
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return code

if __name__ == '__main__':
    sys.exit(main())
