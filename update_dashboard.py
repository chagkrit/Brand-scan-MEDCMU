import csv, json, re
from collections import defaultdict

MONTH_ORDER = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
PLAT_TEXT_MAP = {'facebook':'Facebook','Facebook':'Facebook','X':'x','x':'x','Twitter':'x',
                 'TikTok':'TikTok','tiktok':'TikTok','instagram':'Instagram','Instagram':'Instagram',
                 'YouTube':'YouTube','youtube':'YouTube'}
TAB_TO_PLAT = {'Facebook':'Facebook','TikTok':'TikTok','Instagram':'Instagram',
               'YouTube':'YouTube','x':'x','X':'x'}

def js(v):
    """Safe JS string using json.dumps (handles newlines, backslashes, quotes, Thai etc.)"""
    return json.dumps(str(v), ensure_ascii=False)

def parse_data_file(filepath):
    result = defaultdict(lambda: defaultdict(list))
    with open(filepath, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            result[row['month']][row['tab']].append(row)
    for m in result:
        for t in result[m]:
            result[m][t].sort(key=lambda r: int(r['line_order']))
    return result

def get_section_rows(rows, section_name):
    explicit = [r for r in rows if r['section'] == section_name]
    if len(explicit) > 1: return explicit
    result, inside = [], False
    for r in rows:
        if r['item_type'] == 'section_heading':
            if r['item'] == section_name: inside = True; result.append(r)
            elif inside: break
        elif inside: result.append(r)
    return result

def first_value_after(rows, section_name, label):
    srows = get_section_rows(rows, section_name)
    hit = False
    for r in srows:
        if r['item_type'] == 'metric_or_label' and label.lower() in r['item'].lower(): hit = True
        elif hit and r['item_type'] == 'value': return r['item']
    return None

def first_two_values(rows, section_name):
    srows = get_section_rows(rows, section_name)
    vals = [r['item'] for r in srows if r['item_type'] == 'value']
    return (vals[0] if vals else ''), (vals[1] if len(vals) > 1 else '0.0%')

def extract_overview(month_tabs):
    result = {}
    for month in MONTH_ORDER:
        if month not in month_tabs: continue
        rows = month_tabs[month].get('Overview', [])
        if not rows: continue
        d = {}
        for sec, k1, k2 in [('Brand Score','brand_score','brand_score_change'),
                              ('Owned Score','owned_score','owned_score_change'),
                              ('Earned Score','earned_score','earned_score_change'),
                              ('Sentiment Score','sentiment','sentiment_change')]:
            v, c = first_two_values(rows, sec)
            if v: d[k1] = v; d[k2] = c
        for sec in ['Total Posts','Total Post','Total post']:
            srows = get_section_rows(rows, sec)
            vals = [r['item'] for r in srows if r['item_type'] == 'value']
            if vals: d['total_posts'] = vals[0]; break
        v = first_value_after(rows,'Daily Unique Messages','total')
        if not v:
            srows = get_section_rows(rows,'Daily Unique Messages')
            vals = [r['item'] for r in srows if r['item_type'] == 'value']
            v = vals[0] if vals else ''
        if v: d['daily_messages'] = v
        v = first_value_after(rows,'Engagement Timeline','total engagement')
        if not v:
            for sec in ['Total post','Total Posts','Total Post']:
                v = first_value_after(rows, sec, 'total engagement')
                if v: break
        if v: d['total_engagement'] = v
        if d: result[month] = d
    return result

def extract_channel_engagement(month_tabs):
    result = {}
    for month in MONTH_ORDER:
        if month not in month_tabs: continue
        rows = month_tabs[month].get('Overview', [])
        srows = get_section_rows(rows, 'Engagement By Channel')
        text_items = [r['item'] for r in srows if r['item_type'] == 'text'
                      and r['item'] not in ('Owned','Earned')]
        vals = [r['item'] for r in srows if r['item_type'] == 'value']
        val_pairs = [vals[i] for i in range(0, len(vals)-1, 2)]
        chan_eng = {}
        for i, txt in enumerate(text_items):
            plat = PLAT_TEXT_MAP.get(txt)
            if plat and i < len(val_pairs): chan_eng[plat] = val_pairs[i]
        if chan_eng: result[month] = chan_eng
    return result

def extract_plat_meta(month_tabs):
    result = {}
    for month in MONTH_ORDER:
        if month not in month_tabs: continue
        month_data = {}
        for tab_name, rows in month_tabs[month].items():
            plat = TAB_TO_PLAT.get(tab_name)
            if not plat: continue
            pd = {}
            # YouTube uses "Current subscribers" inside Share section; others use Follower section
            if plat == 'YouTube':
                v = first_value_after(rows, 'Share', 'current subscribers')
                if not v:
                    v = first_value_after(rows, 'Subscriber', 'current subscribers')
            else:
                v = first_value_after(rows, 'Follower', 'current followers')
                if not v:
                    srows = get_section_rows(rows, 'Follower')
                    vs = [r['item'] for r in srows if r['item_type'] == 'value' and r['item'] != '0']
                    v = vs[0] if vs else ''
            if v and v != '0': pd['followers'] = v
            v2 = first_value_after(rows, 'Views', 'current month')
            if not v2:
                srows = get_section_rows(rows, 'Views')
                vs2 = [r['item'] for r in srows if r['item_type'] == 'value']
                v2 = vs2[0] if vs2 else ''
            if v2: pd['views'] = v2
            if pd: month_data[plat] = pd
        if month_data: result[month] = month_data
    return result

def parse_posts_csv(filepath):
    by_month_plat = defaultdict(lambda: defaultdict(list))
    with open(filepath, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            m, pl = row.get('month',''), row.get('platform','')
            if m in MONTH_ORDER and pl:
                by_month_plat[m][pl].append(row)
    for m in by_month_plat:
        for pl in by_month_plat[m]:
            by_month_plat[m][pl].sort(key=lambda r: int(r.get('rank_in_month',99) or 99))
    return by_month_plat

def build_post_obj(p):
    return {
        'platform': p.get('platform',''),
        'date': p.get('date',''),
        'message': p.get('message','')[:200],  # truncate cleanly via Python (char-safe)
        'image_url': p.get('image_url',''),
        'engagement': p.get('engagement','0'),
        'views': p.get('views',''),
    }

def extract_posts(by_month_plat):
    top_all, top_plat = {}, {}
    for month in MONTH_ORDER:
        if month not in by_month_plat: continue
        all_p = []
        for pl, posts in by_month_plat[month].items():
            all_p.extend(posts[:5])
        def eng(p):
            try: return int(str(p.get('engagement','0')).replace(',',''))
            except: return 0
        all_p.sort(key=eng, reverse=True)
        top_all[month] = [build_post_obj(p) for p in all_p[:10]]
        top_plat[month] = {pl: [build_post_obj(p) for p in posts[:5]]
                           for pl, posts in by_month_plat[month].items()}
    return top_all, top_plat

def build_platform_fb_data(by_month_plat, chan_eng, plat_meta):
    platform_data, fb_data = {}, {}
    for month in MONTH_ORDER:
        all_plats = set(list(by_month_plat.get(month,{}).keys()) + list(chan_eng.get(month,{}).keys()))
        if not all_plats: continue
        month_plat = {}
        for pl in all_plats:
            pd = {}
            posts = by_month_plat.get(month,{}).get(pl, [])
            if posts: pd['total_posts'] = str(len(posts))
            eng = chan_eng.get(month,{}).get(pl)
            if eng: pd['total_engagement'] = eng
            meta = plat_meta.get(month,{}).get(pl, {})
            if 'followers' in meta: pd['followers'] = meta['followers']
            if 'views' in meta: pd['views'] = meta['views']
            if pd: month_plat[pl] = pd
        if month_plat: platform_data[month] = month_plat
        fb = month_plat.get('Facebook', {})
        if fb:
            fd = {}
            if 'total_posts' in fb: fd['total_posts_fb'] = fb['total_posts']
            if 'total_engagement' in fb: fd['total_engagement_fb'] = fb['total_engagement']
            if fd: fb_data[month] = fd
    return platform_data, fb_data

# ─── JS builders using json.dumps for ALL string values ──────────────────────

def obj_line(d):
    """Build { "k": "v", ... } with proper JS escaping."""
    parts = [f'{js(k)}: {js(v)}' for k, v in d.items()]
    return '{ ' + ', '.join(parts) + ' }'

def build_DATA_js(all_data):
    lines = ['let DATA = {']
    for brand in ['MedCMU','จุฬาฯ','ศิริราช','สมิติเวช']:
        lines.append(f'  {js(brand)}: {{')
        for m in MONTH_ORDER:
            if m not in all_data.get(brand,{}): continue
            lines.append(f'    {m}: {obj_line(all_data[brand][m])},')
        lines.append('  },')
    lines.append('};')
    return '\n'.join(lines)

def build_FB_DATA_js(all_fb):
    lines = ['let FB_DATA = {']
    for brand in ['MedCMU','จุฬาฯ','ศิริราช','สมิติเวช']:
        lines.append(f'  {js(brand)}: {{')
        for m in MONTH_ORDER:
            if m not in all_fb.get(brand,{}): continue
            lines.append(f'    {m}: {obj_line(all_fb[brand][m])},')
        lines.append('  },')
    lines.append('};')
    return '\n'.join(lines)

def build_PLATFORM_DATA_js(all_plat):
    lines = ['const PLATFORM_DATA = {']
    for brand in ['MedCMU','จุฬาฯ','ศิริราช','สมิติเวช']:
        lines.append(f'  {js(brand)}: {{')
        for m in MONTH_ORDER:
            if m not in all_plat.get(brand,{}): continue
            lines.append(f'    {m}: {{')
            for pl, pd in all_plat[brand][m].items():
                lines.append(f'      {js(pl)}: {obj_line(pd)},')
            lines.append('    },')
        lines.append('  },')
    lines.append('};')
    return '\n'.join(lines)

def build_posts_block(varname, decl, all_top, by_plat=False):
    lines = [f'{decl} {varname} = {{']
    for brand in ['MedCMU','จุฬาฯ','ศิริราช','สมิติเวช']:
        lines.append(f'  {js(brand)}: {{')
        for m in MONTH_ORDER:
            if not by_plat:
                posts = all_top.get(brand,{}).get(m,[])
                if not posts: continue
                lines.append(f'    {m}: [')
                for p in posts:
                    lines.append(f'      {json.dumps(p, ensure_ascii=False)},')
                lines.append('    ],')
            else:
                plat_posts = all_top.get(brand,{}).get(m,{})
                if not plat_posts: continue
                lines.append(f'    {m}: {{')
                for pl, posts in plat_posts.items():
                    lines.append(f'      {js(pl)}: [')
                    for p in posts:
                        lines.append(f'        {json.dumps(p, ensure_ascii=False)},')
                    lines.append('      ],')
                lines.append('    },')
        lines.append('  },')
    lines.append('};')
    return '\n'.join(lines)

# ─── Main ─────────────────────────────────────────────────────────────────────
DATA_FILES = {
    'MedCMU':   '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/MEDCMU_data2026.csv',
    'จุฬาฯ':    '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/CU_data2026.csv',
    'ศิริราช':  '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/SI_data2026.csv',
    'สมิติเวช': '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/Samitivej_data2026.csv',
}
POST_FILES = {
    'MedCMU':   '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/MEDCMU2026.csv',
    'จุฬาฯ':    '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/CU2026.csv',
    'ศิริราช':  '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/SI2026.csv',
    'สมิติเวช': '/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/Samitivej2026.csv',
}

all_data, all_fb_data, all_platform_data = {}, {}, {}
all_top_posts, all_top_posts_plat = {}, {}

for brand, fp in DATA_FILES.items():
    mt = parse_data_file(fp)
    all_data[brand] = extract_overview(mt)
    chan = extract_channel_engagement(mt)
    meta = extract_plat_meta(mt)
    posts_csv = parse_posts_csv(POST_FILES[brand])
    tp, tpp = extract_posts(posts_csv)
    all_top_posts[brand] = tp
    all_top_posts_plat[brand] = tpp
    pd, fd = build_platform_fb_data(posts_csv, chan, meta)
    all_platform_data[brand] = pd
    all_fb_data[brand] = fd

blocks = {
    'DATA':           build_DATA_js(all_data),
    'FB_DATA':        build_FB_DATA_js(all_fb_data),
    'TOP_POSTS':      build_posts_block('TOP_POSTS', 'let', all_top_posts, False),
    'TOP_POSTS_PLAT': build_posts_block('TOP_POSTS_PLAT', 'const', all_top_posts_plat, True),
    'PLATFORM_DATA':  build_PLATFORM_DATA_js(all_platform_data),
}

# ─── Patch HTML ──────────────────────────────────────────────────────────────
with open('/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/brand_scan_dashboard.html', encoding='utf-8') as f:
    html = f.read()

def replace_block(html, start_pat, end_pat, new_block):
    m = re.search(start_pat, html)
    if not m: print(f'  NOT FOUND: {start_pat}'); return html
    rest = html[m.end():]
    m2 = re.search(end_pat, rest)
    if not m2: print(f'  END NOT FOUND'); return html
    end_pos = m.end() + m2.start()
    return html[:m.start()] + new_block + '\n' + html[end_pos:]

html = replace_block(html, r'let DATA = \{',          r'\nlet FB_DATA',         blocks['DATA'])
html = replace_block(html, r'let FB_DATA = \{',       r'\nlet TOP_POSTS = \{',  blocks['FB_DATA'])
html = replace_block(html, r'let TOP_POSTS = \{',     r'\nconst PLATFORM_DATA', blocks['TOP_POSTS'])
html = replace_block(html, r'const PLATFORM_DATA = \{', r'\nconst TOP_POSTS_PLAT', blocks['PLATFORM_DATA'])
html = replace_block(html, r'const TOP_POSTS_PLAT = \{', r'\nlet currentMonth', blocks['TOP_POSTS_PLAT'])

# ─── Validate: zero unescaped newlines inside JS strings ─────────────────────
import re as _re
scripts = _re.findall(r'<script[^>]*>(.*?)</script>', html, _re.DOTALL)
js_text = '\n'.join(scripts)

# Check for raw newlines that appear to be inside string literals
# Strategy: look for newline preceded by odd-number of " on the same "line"
bad = 0
for m2 in _re.finditer(r'(?m)^([^\n]*)"[^\n]*\n[^\n]*"', js_text):
    bad += 1
print(f'Newline-in-string check: {bad} suspicious patterns')

# Check all data blocks balanced
for var in ['DATA','FB_DATA','TOP_POSTS','PLATFORM_DATA','TOP_POSTS_PLAT']:
    pat = rf'(?:let|const)\s+{var}\s*=\s*\{{'
    m3 = _re.search(pat, js_text)
    if not m3: print(f'{var}: MISSING'); continue
    depth = 0
    for c in js_text[m3.start():]:
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: break
    print(f'{var}: {"OK" if depth == 0 else "BROKEN"}')

with open('/sessions/optimistic-practical-brown/mnt/MEDCMU DATA 2026/brand_scan_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(html)
print(f'\nSaved. Total chars: {len(html):,}')
