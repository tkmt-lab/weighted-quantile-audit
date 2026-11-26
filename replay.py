#!/usr/bin/env python3
"""Recheck saved witnesses and rerun pinned library observations; offline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import audit

D = Path(__file__).resolve().parent

def replay(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(16*1024*1024+1)
    if len(raw) > 16*1024*1024:
        raise ValueError('replay bundle exceeds 16 MiB')
    doc = json.loads(raw, object_pairs_hook=audit.unique_object, parse_constant=audit.reject_constant)
    if not isinstance(doc, dict):
        raise ValueError('replay document must be an object')
    records = doc['records'] if 'records' in doc else [doc]
    if not isinstance(records, list) or not 1 <= len(records) <= 256:
        raise ValueError('replay records must be a nonempty array of at most 256 records')
    count = 0
    for saved in records:
        if not isinstance(saved, dict):
            raise ValueError('replay record must be an object')
        record = saved.get('witness', saved)
        if not isinstance(record, dict):
            raise ValueError('witness must be an object')
        audit.independent_check(record)
        fresh = audit.audit(record['nominal_input'])
        for field in ('nominal_input','binary_input','hex_input','certificates','axes','input_rounding','observed','arithmetic','implementation_diagnosis'):
            if fresh[field] != record[field]:
                raise ValueError('replay differs at '+field)
        if fresh['source'] != record['source']:
            raise ValueError('producer/checker source hashes differ from saved version')
        if fresh['environment']['weightstats_sha256'] != record['environment']['weightstats_sha256']:
            raise ValueError('observed module differs')
        if fresh['environment']['distributions'] != record['environment']['distributions']:
            raise ValueError('recorded distribution versions differ')
        if fresh['environment']['python'] != record['environment'].get('python'):
            raise ValueError('recorded Python version differs (exact version required)')
        count += 1
    return {'valid':True, 'observations_replayed':count,'certificates_rechecked':4*count,
            'file_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path',nargs='?',default=str(D/'evidence'/'witnesses.json'))
    args=ap.parse_args()
    try:
        print(json.dumps(replay(args.path),sort_keys=True)); return 0
    except (ValueError,KeyError,TypeError,AttributeError,RecursionError,OSError,RuntimeError,audit.EnvironmentUnsupported) as exc:
        print(json.dumps({'valid':False,'reason':str(exc)})); return 1

if __name__=='__main__':
    sys.exit(main())
