#!/usr/bin/env python3
"""Merge a Wofford League ESPN scrape (the bookmarklet's JSON) into data.js.

Usage:  python3 tools/merge_scrape.py incoming/wofford-scrape-2026-wk1-6.json [--data data.js] [--force]

What it rewrites in data.js (the lines marked "@auto"):
  * MATCHUPS[year]       <- scrape["schedule"][year]        (scores, played weeks)
  * FULL_SCHEDULE[year]  <- scrape["fullSchedule"][year]    (pairings, all weeks)
  * PLAYER_SCORES[year]  <- scrape["playerScores"][year]    (box scores)
Everything else in data.js (PRIMETIME_SCHEDULE, other years) is left alone.
A scrape is the whole season so far, so each run replaces that year's lines.
It refuses to shrink a year (fewer weeks than data.js already has) unless --force.
"""
import json, re, subprocess, sys, shutil

def clean(n):                      # ESPN sometimes doubles spaces in team names
    return re.sub(r'\s+', ' ', n).strip()

def js(o):
    return json.dumps(o, separators=(',', ':'), ensure_ascii=False)

def week_entry_matchup(w):
    g = [[clean(a), sa, clean(b), sb] for a, sa, b, sb in w['g']]
    parts = ['w:%d' % w['w']]
    if w.get('playoff'): parts.append('playoff:%s' % js(w['playoff']))
    if w.get('champ_game'): parts.append('champ_game:true')
    parts.append('g:' + js(g))
    return '{' + ','.join(parts) + '}'

def week_entry_schedule(w):
    g = [[clean(a), clean(b)] for a, b in w['g']]
    parts = ['w:%d' % w['w']]
    if w.get('playoff'): parts.append('playoff:%s' % js(w['playoff']))
    parts.append('g:' + js(g))
    return '{' + ','.join(parts) + '}'

def replace_year_line(text, marker, year, body, block_start_pat):
    """Replace the line after '// @auto <marker>-<year>' ; if absent, append a new
    year to the end of the block that starts with block_start_pat."""
    mark = '  // @auto %s-%s' % (marker, year)
    pat = re.compile(r'^' + re.escape(mark) + r'[^\n]*\n  (\d{4}):\[.*?\](,?)$', re.M)
    m = pat.search(text)
    new = '%s (rewritten by tools/merge_scrape.py)\n  %s:%s' % (mark, year, body)
    if m:
        return text[:m.start()] + new + m.group(2) + text[m.end():]
    # new year: add after the last year in the block
    s = text.index(block_start_pat)
    e = text.index('\n};', s)
    block = text[s:e]
    block = block.rstrip()
    if not block.endswith(','): block += ','
    return text[:s] + block + '\n' + new + text[e:]

def played_weeks(text, const, year):
    s = text.index('const %s = {' % const)
    e = text.index('\n};', s)
    m = re.search(r'^  %s:\[(.*)\],?$' % year, text[s:e], re.M)
    return len(re.findall(r'\{w:\d+', m.group(1))) if m else 0

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    force = '--force' in sys.argv
    data_path = 'data.js'
    if '--data' in sys.argv: data_path = sys.argv[sys.argv.index('--data') + 1]; args.remove(data_path)
    if not args: sys.exit(__doc__)
    scrape = json.load(open(args[0]))
    for k in ('schedule', 'fullSchedule', 'playerScores'):
        if k not in scrape: sys.exit('Scrape is missing "%s" -- is this the right file?' % k)
    text = open(data_path, encoding='utf-8').read()
    shutil.copyfile(data_path, data_path + '.bak')
    report = []
    for year in sorted(scrape['schedule']):
        weeks = sorted(scrape['schedule'][year], key=lambda w: w['w'])
        if not weeks: continue
        have = played_weeks(text, 'MATCHUPS', year)
        if len(weeks) < have and not force:
            sys.exit('Refusing: scrape has %d weeks of %s but data.js already has %d. Use --force to override.' % (len(weeks), year, have))
        bad = [w['w'] for w in weeks if len(w['g']) != 6]
        if bad: print('WARNING: weeks %s do not have 6 games' % bad)
        text = replace_year_line(text, 'matchups', year,
            '[' + ','.join(week_entry_matchup(w) for w in weeks) + ']', 'const MATCHUPS = {')
        if year in scrape['fullSchedule']:
            fs = sorted(scrape['fullSchedule'][year], key=lambda w: w['w'])
            text = replace_year_line(text, 'full-schedule', year,
                '[' + ','.join(week_entry_schedule(w) for w in fs) + ']', 'const FULL_SCHEDULE = {')
        report.append('%s: %d played weeks (was %d)' % (year, len(weeks), have))
    # player scores
    for year, wks in scrape['playerScores'].items():
        out = {}
        for wk in sorted(wks, key=int):
            out[wk] = {clean(team): [{'name': p['name'], 'pos': p['pos'], 'pts': p['pts'],
                                      'slotId': p.get('slotId'), 'bench': p['bench']} for p in pl]
                       for team, pl in wks[wk].items()}
        mark = '  // @auto player-scores-%s' % year
        pat = re.compile(r'^' + re.escape(mark) + r'[^\n]*\n  "%s":.*?(,?)$' % year, re.M)
        body = '%s (rewritten by tools/merge_scrape.py)\n  "%s":%s' % (mark, year, js(out))
        m = pat.search(text)
        if m: text = text[:m.start()] + body + m.group(1) + text[m.end():]
        else:
            s = text.index('const PLAYER_SCORES = {'); e = text.index('\n};', s)
            blk = text[s:e].rstrip()
            if not blk.endswith(','): blk += ','
            text = text[:s] + blk + '\n' + body + text[e:]
        report.append('%s box scores: %d weeks' % (year, len(out)))
    open(data_path, 'w', encoding='utf-8').write(text)
    # sanity check: data.js must still parse and define the four constants
    try:
        chk = ("const vm=require('vm'),fs=require('fs');const c={};vm.createContext(c);"
               "vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';this.o={m:MATCHUPS,f:FULL_SCHEDULE,p:PLAYER_SCORES,t:PRIMETIME_SCHEDULE}',c);"
               "console.log('data.js parses OK')")
        subprocess.run(['node', '-e', chk, data_path], check=True)
    except FileNotFoundError:
        print('(node not found; skipped syntax check)')
    except subprocess.CalledProcessError:
        shutil.copyfile(data_path + '.bak', data_path)
        sys.exit('data.js failed to parse after merge -- restored the previous version.')
    print('\n'.join(report))
    print('Reminder: PRIMETIME_SCHEDULE in data.js is hand-edited (not in the scrape).')

if __name__ == '__main__':
    main()
