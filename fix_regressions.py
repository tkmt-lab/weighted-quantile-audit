"""Regression checks for valid oversized JSON integers and Python replay history."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

D = Path(__file__).resolve().parent

def run():
    failures = []
    counts = {'integer_cli': 0, 'python_replay': 0}
    def check(ok, label):
        if not ok:
            failures.append(label)

    def document(token, field='x'):
        values = {'x': '[0,1]', 'w': '[1,1]', 'p': '"1/2"'}
        values[field] = '[' + token + ',1]' if field in ('x', 'w') else token
        return '{' + ','.join(json.dumps(k) + ':' + v for k, v in values.items()) + '}'

    cases = []
    for digits in (4300, 4301, 60000):
        for sign in ('', '-'):
            for field in ('x', 'w', 'p'):
                cases.append((f'{field}:{sign}{digits}digits', document(sign+'9'*digits, field), 'UNSUPPORTED'))
    huge = '9'*4301
    for label, raw in [('root', huge), ('unknown', '{"extra":'+huge+'}'),
                       ('nested', document('['+huge+']'))]:
        cases.append((label, raw, 'UNSUPPORTED'))
    raw = document(huge)
    for label, broken in [('truncated', raw[:-1]), ('trailing', raw+'x'),
                          ('duplicate', raw[:-1]+',"x":[0,1]}'),
                          ('leading_zero', document('0'+huge)),
                          ('bad_exponent', document(huge+'e+'))]:
        cases.append((label, broken, 'INVALID_JSON'))
    for value in (2**128-1, -(2**128-1), 2**128, -2**128, 10**39, -10**39, 0):
        cases.append((f'bit-boundary:{value}', document(str(value)),
                      'OK' if abs(value).bit_length() <= 128 else 'UNSUPPORTED'))
    cases.append(('exact-byte-limit', raw+' '*(65536-len(raw)), 'UNSUPPORTED'))
    cases.append(('over-byte-limit', raw+' '*(65537-len(raw)), 'UNSUPPORTED'))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'input.json'
        for label, raw, status in cases:
            for mode in ('stdin', 'file'):
                path.write_text(raw)
                command = [sys.executable, '-B', str(D/'audit.py')]
                if mode == 'file': command.append(str(path))
                p = subprocess.run(command, input=raw if mode == 'stdin' else None,
                                   capture_output=True, text=True, timeout=30)
                result = json.loads(p.stdout)
                check(p.returncode == (0 if status == 'OK' else 2) and result['status'] == status,
                      label+':'+mode)
                counts['integer_cli'] += 1
        # Changing the interpreter's decimal conversion setting must not change
        # the public classification; never change it in the application itself.
        for limit in ('640', '0'):
            p = subprocess.run([sys.executable, '-B', str(D/'audit.py')], input=document(huge),
                               capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, PYTHONINTMAXSTRDIGITS=limit))
            check(p.returncode == 2 and json.loads(p.stdout)['status'] == 'UNSUPPORTED',
                  'integer-runtime-limit:'+limit)
            counts['integer_cli'] += 1

        import audit
        original = audit.audit({'x': [0, 1], 'w': [1, 1], 'p': '1/2'})
        current = original['environment']['python']
        # Exercise the public replay entry point with fresh source hashes, so
        # source mismatch cannot accidentally make a metadata regression pass.
        variants = [('unchanged', current), ('false_version', '0.0.0'),
                    ('patch_only', current.rsplit('.', 1)[0]+'.999'),
                    ('null', None), ('missing', None)]
        for label, version in variants:
            record = copy.deepcopy(original)
            if label == 'missing': del record['environment']['python']
            else: record['environment']['python'] = version
            path.write_text(json.dumps(record))
            p = subprocess.run([sys.executable, '-B', str(D/'replay.py'), str(path)],
                               capture_output=True, text=True, timeout=30)
            result = json.loads(p.stdout)
            if label == 'unchanged':
                check(p.returncode == 0 and result['valid'] is True, 'replay:'+label)
            else:
                check(p.returncode == 1 and result['valid'] is False and
                      result['reason'] == 'recorded Python version differs (exact version required)',
                      'replay:'+label)
            counts['python_replay'] += 1
    return counts, failures

if __name__ == '__main__':
    counts, failures = run()
    print(json.dumps({'valid': not failures, 'counts': counts, 'failures': failures}, indent=2))
    sys.exit(bool(failures))
