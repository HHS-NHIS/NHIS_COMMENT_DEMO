#!/usr/bin/env python3
"""Score a human-coded validation sample against a keyword screen OR a blinded AI-label sample.

1. In the dashboard: Import & exports -> "Validation sample for human coding" (CSV).
2. Coders fill human_label with 1 (theme present in the comment) or 0 (absent). Optional second
   independent coder: add a column human_label_2 for inter-coder agreement (Cohen's kappa).
3. python scripts\\score_validation.py path\\to\\coded.csv [--out scores.csv]

Per theme:
* precision = share of screen-positive sampled records coded 1 (Wilson 95% CI)
* false-negative rate among screen-negatives (Wilson 95% CI)
* recall is estimated with stratum weights: TP_hat = precision x N_pos; FN_hat = fn_rate x N_neg;
  recall = TP_hat / (TP_hat + FN_hat). The interval is a conservative bound built from the two
  Wilson intervals (not exact).
* estimated prevalence (records) = (TP_hat + FN_hat) / N
Small samples (default 8 per stratum) give wide intervals: they show whether a rule is usable,
not a precise rate. Increase per-stratum size for publication-grade estimates.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict


def wilson(k, n, z=1.96):
    if n == 0:
        return (float('nan'), float('nan'), float('nan'))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def kappa(pairs):
    n = len(pairs)
    if not n:
        return float('nan')
    po = sum(a == b for a, b in pairs) / n
    p1 = sum(a for a, _ in pairs) / n
    p2 = sum(b for _, b in pairs) / n
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def label(v):
    v = str(v or '').strip().lower()
    return {'1': 1, 'yes': 1, 'y': 1, 'true': 1, '0': 0, 'no': 0, 'n': 0, 'false': 0}.get(v)


def score(rows):
    by = defaultdict(lambda: {'pos': [], 'neg': [], 'Npos': 0, 'Nneg': 0, 'name': '', 'pairs': []})
    for r in rows:
        t = by[r['theme_id']]
        t['name'] = r.get('theme', r['theme_id'])
        lab = label(r.get('human_label'))
        stratum_pos = r['stratum'] == 'screen_positive'
        pop = int(float(r.get('stratum_population') or 0))
        if stratum_pos:
            t['Npos'] = pop
        else:
            t['Nneg'] = pop
        if lab is None:
            continue
        (t['pos'] if stratum_pos else t['neg']).append(lab)
        l2 = label(r.get('human_label_2'))
        if l2 is not None:
            t['pairs'].append((lab, l2))
    out = []
    for tid, t in sorted(by.items()):
        prec = wilson(sum(t['pos']), len(t['pos']))
        fnr = wilson(sum(t['neg']), len(t['neg']))
        def rec(pr, fr):
            tp, fn = pr * t['Npos'], fr * t['Nneg']
            return tp / (tp + fn) if (tp + fn) > 0 else float('nan')
        recall = rec(prec[0], fnr[0]) if t['pos'] and t['neg'] else float('nan')
        r_lo = rec(prec[1], fnr[2]) if t['pos'] and t['neg'] else float('nan')
        r_hi = rec(prec[2], fnr[1]) if t['pos'] and t['neg'] else float('nan')
        f1 = 2 * prec[0] * recall / (prec[0] + recall) if prec[0] == prec[0] and recall == recall and (prec[0] + recall) else float('nan')
        N = t['Npos'] + t['Nneg']
        prev = ((prec[0] * t['Npos'] if t['pos'] else 0) + (fnr[0] * t['Nneg'] if t['neg'] else 0)) / N if N else float('nan')
        out.append({'theme_id': tid, 'theme': t['name'], 'coded_positive': len(t['pos']), 'coded_negative': len(t['neg']),
                    'screen_positive_records': t['Npos'], 'screen_negative_records': t['Nneg'],
                    'precision': prec[0], 'precision_lo': prec[1], 'precision_hi': prec[2],
                    'false_negative_rate': fnr[0], 'fnr_lo': fnr[1], 'fnr_hi': fnr[2],
                    'recall_est': recall, 'recall_lo': r_lo, 'recall_hi': r_hi, 'f1_est': f1,
                    'estimated_true_records': prev * N if prev == prev else float('nan'),
                    'cohen_kappa': kappa(t['pairs']), 'double_coded': len(t['pairs'])})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('coded_csv')
    ap.add_argument('--out', default='validation_scores.csv')
    ap.add_argument('--key', help='Private answer key for BLINDED AI-label validation; NEVER give this file to coders')
    a = ap.parse_args(argv)
    with open(a.coded_csv, encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    if a.key:
        with open(a.key, encoding='utf-8-sig', newline='') as f:
            answers = list(csv.DictReader(f))
        keys = {r['review_id']:r for r in answers}
        if len(keys) != len(answers): sys.exit('Answer key has duplicate review IDs')
        if len({r.get('review_id') for r in rows}) != len(rows): sys.exit('Coder file has duplicate review IDs')
        if len(rows) != len(keys): sys.exit('Coded review rows and answer-key rows differ: use the same sample version')
        for row in rows:
            k = keys.get(row.get('review_id'))
            if not k or row.get('comment_id') != k.get('comment_id') or row.get('theme_id') != k.get('theme_id'):
                sys.exit('Blinded row IDs do not match the answer key. Stop; never guess matching labels.')
            row['stratum'] = k['stratum']
            row['stratum_population'] = k['stratum_population']
    need = {'theme_id', 'stratum', 'stratum_population', 'human_label'}
    if not rows or need - set(rows[0]):
        sys.exit('Expected the validation_sample export with columns: ' + ', '.join(sorted(need)))
    results = score(rows)
    fmt = lambda v: '' if v != v else (f'{v:.3f}' if isinstance(v, float) else v)
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0]))
        w.writeheader()
        for r in results:
            w.writerow({k: fmt(v) for k, v in r.items()})
    print(f"{'theme':34} {'n+':>3} {'n-':>3} {'precision (95% CI)':>22} {'recall est (bounds)':>22} {'kappa':>6}")
    for r in results:
        p = 'n/a' if r['precision'] != r['precision'] else f"{r['precision']:.2f} ({r['precision_lo']:.2f}-{r['precision_hi']:.2f})"
        rc = 'n/a' if r['recall_est'] != r['recall_est'] else f"{r['recall_est']:.2f} ({r['recall_lo']:.2f}-{r['recall_hi']:.2f})"
        k = '' if r['cohen_kappa'] != r['cohen_kappa'] else f"{r['cohen_kappa']:.2f}"
        print(f"{r['theme'][:34]:34} {r['coded_positive']:>3} {r['coded_negative']:>3} {p:>22} {rc:>22} {k:>6}")
    print('Wrote', a.out)


if __name__ == '__main__':
    main()
