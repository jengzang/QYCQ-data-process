import csv
from pathlib import Path

EXT_SUFFIXES = ['新村', '里', '社', '坊', '岗', '围', '屋', '村']


def has_suffix(name, suffix):
    return name.endswith(suffix)


def split_candidates(text):
    return [x.strip() for x in text.split('|') if x.strip()]


def choose_by_rule_d(xlsx_name, candidates):
    # Rule D: prefer the simplest/base form; do not pick expanded suffix variants
    # unless the xlsx source itself carries that same suffix explicitly.
    if len(candidates) < 2:
        return None
    x = xlsx_name.strip()
    # If source itself carries one explicit extension suffix, prefer same-suffix candidate.
    for suffix in EXT_SUFFIXES:
        if has_suffix(x, suffix):
            same = [c for c in candidates if has_suffix(c, suffix)]
            if len(same) == 1:
                return same[0]
    # Otherwise prefer candidate with no extension suffix among the known suffix list.
    base = [c for c in candidates if not any(has_suffix(c, suf) for suf in EXT_SUFFIXES)]
    if len(base) == 1:
        return base[0]
    # If all are extended variants, prefer shortest candidate deterministically.
    shortest = sorted(candidates, key=lambda c: (len(c), c))
    if shortest:
        # only accept deterministic shortest if strictly shorter than next
        if len(shortest) == 1 or len(shortest[0]) < len(shortest[1]):
            return shortest[0]
    return None


def main():
    rows = list(csv.DictReader(open('outputs/natural_village_unresolved.csv', encoding='utf-8-sig')))
    amb = [r for r in rows if r['match_status'] == 'ambiguous_normalized']
    confirmations = list(csv.DictReader(open('outputs/manual_confirmed_mappings.csv', encoding='utf-8-sig')))
    idx = {(r['level'], r['parent_scope'], r['source_value']): r for r in confirmations}
    accepted = []
    skipped = []
    for r in amb:
        candidates = split_candidates(r['candidates'])
        chosen = choose_by_rule_d(r['xlsx_natural_village'], candidates)
        if not chosen:
            skipped.append({
                'xlsx_city': r['xlsx_city'],
                'xlsx_town': r['xlsx_town'],
                'xlsx_admin_village': r['xlsx_admin_village'],
                'xlsx_natural_village': r['xlsx_natural_village'],
                'candidates': r['candidates'],
            })
            continue
        parent = f"{r['xlsx_city']} / {r['xlsx_town']} / {r['xlsx_admin_village']}"
        idx[('natural', parent, r['xlsx_natural_village'])] = {
            'level': 'natural',
            'parent_scope': parent,
            'source_value': r['xlsx_natural_village'],
            'confirmed_value': chosen,
            'action': 'confirm',
            'source_suggestions': 'rule_d_prefer_base_over_li_she_fang_gang:' + r['candidates'],
        }
        accepted.append({
            'xlsx_city': r['xlsx_city'],
            'xlsx_town': r['xlsx_town'],
            'xlsx_admin_village': r['xlsx_admin_village'],
            'xlsx_natural_village': r['xlsx_natural_village'],
            'chosen': chosen,
            'candidates': r['candidates'],
        })

    fieldnames = ['level','parent_scope','source_value','confirmed_value','action','source_suggestions']
    final = sorted(idx.values(), key=lambda r:(r['level'], r['parent_scope'], r['source_value'], r['confirmed_value']))
    with open('outputs/manual_confirmed_mappings.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(final)
    with open('outputs/natural_rule_d_applied.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['xlsx_city','xlsx_town','xlsx_admin_village','xlsx_natural_village','chosen','candidates'])
        w.writeheader(); w.writerows(accepted)
    with open('outputs/natural_rule_d_skipped.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['xlsx_city','xlsx_town','xlsx_admin_village','xlsx_natural_village','candidates'])
        w.writeheader(); w.writerows(skipped)
    print('accepted', len(accepted), 'skipped', len(skipped), 'confirmations_total', len(final))


if __name__ == '__main__':
    main()
