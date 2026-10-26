#!/usr/bin/env python3
"""Optional source-multiset candidate analysis; never a canonical MIHA proof."""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import re

REV = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')


def analyze(data, source_sha256):
    if not isinstance(data, dict) or data.get('schema') != 'miha.source-multisets.v1':
        raise ValueError('MIHA_SCHEMA')
    revision = data.get('dataset_revision')
    if not isinstance(revision, str) or not REV.fullmatch(revision):
        raise ValueError('MIHA_REVISION_REQUIRED')
    if not re.fullmatch(r'[0-9a-f]{64}', source_sha256):
        raise ValueError('MIHA_INPUT_SHA256')
    rows = data.get('records')
    if not isinstance(rows, list) or not 2 <= len(rows) <= 128:
        raise ValueError('MIHA_RECORD_BOUNDS')
    counts = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not ID.fullmatch(row['id']):
            raise ValueError('MIHA_RECORD_ID')
        ids = row.get('source_ids')
        if not isinstance(ids, list) or len(ids) > 256 or any(
            not isinstance(s, str) or not s or len(s) > 512 or
            any(c.isspace() or ord(c) < 32 for c in s) for s in ids
        ):
            raise ValueError('MIHA_SOURCE_IDS')
        if row['id'] in counts:
            raise ValueError('MIHA_DUPLICATE_RECORD')
        counts[row['id']] = Counter(ids)
    pairs, missing = [], 0
    for left, right in itertools.combinations(sorted(counts), 2):
        a, b = counts[left], counts[right]
        if not a or not b:
            missing += 1
            continue
        shared = {s: min(a[s], b[s]) for s in sorted(a.keys() & b.keys())}
        common = sum(shared.values())
        total = sum(a.values()) + sum(b.values())
        pairs.append({'left_id': left, 'right_id': right,
                      'dice_dissimilarity': str(Fraction(total - 2 * common, total)),
                      'shared_counts': shared})
    pairs.sort(key=lambda p: (Fraction(p['dice_dissimilarity']), p['left_id'], p['right_id']))
    return {'schema': 'miha.similarity-candidates.v1', 'status': 'CANDIDATE_ONLY_NOT_PROOF',
            'declared_revision_verified': False, 'dataset_revision': revision,
            'input_sha256': source_sha256, 'insufficient_evidence_pairs': missing,
            'pairs': pairs, 'limitations': ['no causal join', 'no payment or delivery evidence',
                                            'no dataset writes', 'source revision must be verified independently']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = a.input.read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError('MIHA_INPUT_TOO_LARGE')
    result = analyze(json.loads(raw), hashlib.sha256(raw).hexdigest())
    with a.output.open('x', encoding='utf-8') as out:
        json.dump(result, out, indent=2, sort_keys=True, allow_nan=False)
        out.write('\n')
    if json.loads(a.output.read_text(encoding='utf-8')) != result:
        raise RuntimeError('MIHA_RECEIPT_READBACK')
    print(json.dumps({'status': result['status'], 'candidates': len(result['pairs'])}))


if __name__ == '__main__':
    main()
