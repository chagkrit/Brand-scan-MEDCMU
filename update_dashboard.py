import csv, json, re
from collections import defaultdict

MONTH_ORDER = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MONTH_ALIASES = {'June':'Jun','July':'Jul','Sept':'Sep'}
def norm_month(m):
    return MONTH_ALIASES.get(m, m)
PLAT_TEXT_MAP = {'facebook':'Facebook','Facebook':'Facebook','X':'x','x':'x','Twitter':'x',
                 'TikTok':'TikTok','tiktok':'TikTok','instagram':'Instagram','Instagram':'Instagram',
                 'YouTube':'YouTube','youtube':'YouTube'}
TAB_TO_PLAT = {'Facebook':'Facebook','TikTok':'TikTok','Instagram':'Instagram',
               'YouTube':'YouTube','x':'x','X':'x'}
PLATFORM_ORDER = ['Facebook', 'TikTok', 'Instagram', 'YouTube', 'x']

def js(v):
    """Safe JS string using json.dumps (handles newlines, backslashes, quotes, Thai etc.)"""
    return json.dumps(str(v), ensure_ascii=False)

def parse_data_file(filepath):
    result = defaultdict(lambda: defaultdict(list))
    with open(filepath, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            result[norm_month(row['month'])][row['tab']].append(row)
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

def regex_after_label(rows, label_regex):
    """Fallback for malformed exports where a metric's value is merged into one
    text/metric_or_label cell shortly after its label, instead of split into
    separate value cells (seen in some brands' May 2026 export). Looks up to
    3 rows ahead to skip intervening 'Owned'/'Earned' marker cells."""
    for i, r in enumerate(rows):
        if re.search(label_regex, r['item'], re.I):
            for j in range(i + 1, min(i + 4, len(rows))):
                m = re.match(r'^([\d,]+(?:\.\d+)?)\s*([+-]?[\d.]+%)?', rows[j]['item'])
                if m: return m.group(1), (m.group(2) or '0.0%')
    return None, None

def regex_total_engagement(rows):
    for r in rows:
        m = re.search(r'Total engagement\s+([\d,]+)\s*([+-]?[\d.]+%)?', r['item'], re.I)
        if m: return m.group(1)
    return None

def extract_overview(month_tabs):
    def score_and_change(rows, labels):
        """Read both legacy inline metrics and the newer per-metric sections.

        July's Social Metric export labels the aggregate score "Social Metric
        Score" and, for some brands, puts each metric in its own section.  Do
        not treat the informational "on Jul" value as a percentage change.
        """
        labels = {label.lower() for label in labels}
        candidates = []
        for i, row in enumerate(rows):
            section = row.get('section', '').lower()
            item = row.get('item', '')
            is_inline_label = row.get('item_type') == 'metric_or_label' and item.lower() in labels
            is_section = row.get('item_type') == 'section_heading' and section in labels
            if not (is_inline_label or is_section):
                continue
            values = []
            for next_row in rows[i + 1:]:
                if is_inline_label and next_row.get('item_type') == 'metric_or_label':
                    break
                if is_section and next_row.get('item_type') == 'section_heading':
                    break
                if next_row.get('item_type') == 'value':
                    values.append(next_row.get('item', ''))
            if values:
                candidates = values
                break
        score = next((value for value in candidates
                      if re.fullmatch(r'[+-]?[\d,]+(?:\.\d+)?', value.strip())), '')
        change = next((value for value in candidates if '%' in value), '')
        return score, change

    result = {}
    for month in MONTH_ORDER:
        if month not in month_tabs: continue
        rows = month_tabs[month].get('Overview', [])
        if not rows: continue
        d = {}
        for sec, aliases, k1, k2 in [
            ('Brand Score', ['Brand Score', 'Social Metric Score'], 'brand_score', 'brand_score_change'),
            ('Owned Score', ['Owned Score'], 'owned_score', 'owned_score_change'),
            ('Earned Score', ['Earned Score'], 'earned_score', 'earned_score_change'),
            ('Sentiment Score', ['Sentiment Score'], 'sentiment', 'sentiment_change'),
        ]:
            v, c = score_and_change(rows, aliases)
            if not v:
                v, c = first_two_values(rows, sec)
            if v: d[k1] = v; d[k2] = c
        for sec in ['Total Posts','Total Post','Total post']:
            srows = get_section_rows(rows, sec)
            vals = [r['item'] for r in srows if r['item_type'] == 'value']
            if vals: d['total_posts'] = vals[0]; break
        if 'total_posts' not in d:
            v, _ = regex_after_label(rows, r'^Total Posts$')
            if v: d['total_posts'] = v
        v = first_value_after(rows,'Daily Unique Messages','total')
        if not v:
            srows = get_section_rows(rows,'Daily Unique Messages')
            vals = [r['item'] for r in srows if r['item_type'] == 'value']
            v = vals[0] if vals else ''
        if v: d['daily_messages'] = v
        if 'daily_messages' not in d:
            v, _ = regex_after_label(rows, r'^Daily Unique Messages$')
            if v: d['daily_messages'] = v
        v = first_value_after(rows,'Engagement Timeline','total engagement')
        if not v:
            for sec in ['Total post','Total Posts','Total Post']:
                v = first_value_after(rows, sec, 'total engagement')
                if v: break
        if v: d['total_engagement'] = v
        if 'total_engagement' not in d:
            v = regex_total_engagement(rows)
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
    def follower_value(rows, platform):
        """Read the audience total from all known ZocialEye CSV layouts.

        July's four source exports use different heading names for the same
        owned-audience metric.  Keep the values in their original CSV rows;
        only normalize the extraction here.
        """
        sections = ['Follower', 'Followers', 'Owned Channel Followers',
                    'Owned Follower Snapshot', 'Follower Snapshot (Owned)']
        if platform == 'YouTube':
            sections = ['Share', 'Subscriber'] + sections
        labels = ['current subscribers', 'current followers', 'followers', 'subscribers']
        for section in sections:
            for label in labels:
                value = first_value_after(rows, section, label)
                if value:
                    return value
        return ''

    result = {}
    for month in MONTH_ORDER:
        if month not in month_tabs: continue
        month_data = {}
        for tab_name, rows in month_tabs[month].items():
            plat = TAB_TO_PLAT.get(tab_name)
            if not plat: continue
            pd = {}
            v = follower_value(rows, plat)
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
            m = norm_month(row.get('month',''))
            raw_pl = row.get('platform','')
            # Keep platform keys aligned with Engagement By Channel. The
            # Social Metric export uses both ``X`` and ``x`` in different
            # blocks; without this normalization the dashboard creates two
            # separate X rows and the July total appears split.
            pl = PLAT_TEXT_MAP.get(raw_pl, PLAT_TEXT_MAP.get(raw_pl.casefold(), raw_pl))
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
    latest_followers = {}
    for month in MONTH_ORDER:
        # July can contain performance data without a separate follower
        # section. Carry forward only the latest value already present in the
        # CSV and retain its month for transparent display in the dashboard.
        for pl, meta in plat_meta.get(month, {}).items():
            if meta.get('followers'):
                latest_followers[pl] = (meta['followers'], month)
        # Include follower-only platforms too.  A platform with no posts in a
        # month can still have a valid audience total in the CSV.
        all_plats = set(list(by_month_plat.get(month,{}).keys())
                       + list(chan_eng.get(month,{}).keys())
                       + list(plat_meta.get(month,{}).keys()))
        if not all_plats: continue
        month_plat = {}
        for pl in sorted(all_plats, key=lambda p: (PLATFORM_ORDER.index(p)
                                                    if p in PLATFORM_ORDER else len(PLATFORM_ORDER), p)):
            pd = {}
            posts = by_month_plat.get(month,{}).get(pl, [])
            if posts: pd['total_posts'] = str(len(posts))
            eng = chan_eng.get(month,{}).get(pl)
            if eng: pd['total_engagement'] = eng
            meta = plat_meta.get(month,{}).get(pl, {})
            if 'followers' in meta:
                pd['followers'] = meta['followers']
                pd['followers_as_of'] = month
            elif pl in latest_followers:
                pd['followers'], pd['followers_as_of'] = latest_followers[pl]
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


# ─── August 2026 source overlay ──────────────────────────────────────────────
# The three faculty/hospital CSV pairs already contain their August exports.
# Samitivej was collected from the authenticated Brand Scan view on 23 Sep
# 2026.  Brand and platform totals reflect every table row exposed there; the
# dashboard intentionally renders the five leading posts per platform.
SAMITIVEJ_AUGUST = {
    'summary': {
        'brand_score': '182', 'brand_score_change': '+4.60%',
        'owned_score': '177', 'owned_score_change': '+5.36%',
        'earned_score': '190', 'earned_score_change': '+2.15%',
        'sentiment': '52.4', 'sentiment_change': '-2.24%',
        'total_posts': '89', 'total_engagement': '132,781',
    },
    'platforms': {
        'Facebook': {'total_posts': '50', 'total_engagement': '46,692'},
        'TikTok': {'total_posts': '20', 'total_engagement': '50,744', 'views': '1,241,610'},
        'Instagram': {'total_posts': '6', 'total_engagement': '365', 'views': '3,515'},
        'YouTube': {'total_posts': '8', 'total_engagement': '1,385', 'views': '302,713'},
        'x': {'total_posts': '19', 'total_engagement': '33,595'},
    },
    'posts': {
        'Facebook': [
            ('20 Aug 2026', '⚠️10 สัญญาณเตือน "โรคเส้นเลือดหัวใจตีบ" 1. เจ็บแน่นกลางอก 2. เจ็บร้าวไปกราม ไหล่ แขน คอ 3. เจ็บเมื่อออกแรง 4. แน่นอกเกิน 5-10 นาที และไม่ดีขึ้นเมื่อพัก 5. เหงื่อออกเยอะโดยไม่มีสาเหตุ 6. เหงื่อออกมากแล', '', '10,282', ''),
            ('22 Aug 2026', 'เมื่อไหร่ควรตรวจ CT Calcium Scoring? และเมื่อไหร่ควรตรวจ หลอดเลือดคอ เพื่อประเมินความเสี่ยงหลอดเลือดตีบ? และใครควรตรวจ? มาฟังคำตอบจากนพ. นาวี ตันจรารักษ์ อายุรแพทย์โรคหัวใจกันค่ะ #โรงพยาบาลสมิติเวช #เ', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/22/facebook_113238002044013_1497639235740383_684767196.webp', '6,305', ''),
            ('20 Aug 2026', 'เส้นเลือดหัวใจตีบ 3 เส้น เกิดขึ้นได้อย่างไร? มาฟังคำตอบจากนพ. นาวี ตันจรารักษ์ อายุรแพทย์โรคหัวใจกันค่ะ ทำนัดปรึกษาแพทย์ คลิก https://smtvj.com/4d6rZ9R #โรงพยาบาลสมิติเวช #เราไม่อยากให้ใครป่วย เส้นเลื', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/20/facebook_113238002044013_1495869855917321_654968993.webp', '4,377', ''),
            ('25 Aug 2026', '🏃‍♀️ สมิติเวช ศรีนครินทร์ เปิดบ้านต้อนรับวัยเก๋า 50+ สู่สนามวิ่ง ในงาน Age Friendly Run 2026 by Samitivej : วิ่งละ YOUNG ครั้งที่ 3 วิ่งปลอดภัยกับ Doctor & Nurse Runners กว่า 100 คน ร่วมดูแลความปลอดภ', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/25/facebook_113238002044013_1500222808815359_617747529.webp', '2,399', ''),
            ('29 Aug 2026', '💚 เพราะคนที่เราอยากดูแล ไม่ได้มีแค่ตัวเราเอง การดูแลสุขภาพจึงเป็นอีกหนึ่งเรื่องที่ คุณนุ่น และคุณหลุยส์ สก๊อต ให้ความสำคัญ เพราะการมีสุขภาพที่ดี คือการได้ใช้เวลาอยู่ด้วยกันและทำสิ่งที่รักไปได้นาน ๆ ท', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/29/facebook_113238002044013_1500128982158075_331533465.webp', '2,201', ''),
        ],
        'TikTok': [
            ('20 Aug 2026', 'เส้นเลือดหัวใจตีบ 3 เส้น เกิดขึ้นได้อย่างไร? #เรย์แม็คโดนัลด์ #เส้นเลือดหัวใจตีบ #ข่าวtiktok #โรคหัวใจ', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/20/tiktok_7676011805377973525_134021036.webp', '6,934', '164,564'),
            ('24 Aug 2026', 'หัวใจเต้นผิดจังหวะ ป้องกันได้ไหม? #เส้นเลือดหัวใจตีบ #โรคหัวใจ #LDL #ไขมันสูง #ไหลตาย', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/24/tiktok_7677587141307895060_456681501.webp', '5,767', '135,394'),
            ('22 Aug 2026', 'เราเริ่มตรวจไขมันที่อายุ?#เส้นเลือดหัวใจตีบ #โรคหัวใจ #LDL #ไขมันสูง', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/22/tiktok_7676494274296368404_100805978.webp', '5,706', '137,461'),
            ('22 Aug 2026', 'ดูแลสุขภาพดีแล้วแต่ทำไมยังเสี่ยง? #เส้นเลือดหัวใจตีบ #โรคหัวใจ #LDL #ไขมันสูง', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/22/tiktok_7676496323050245397_548470923.webp', '3,021', '85,400'),
            ('20 Aug 2026', 'สาเหตุการเสียชีวิตเฉียบพลัน #โรคหัวใจ #เส้นเลือดหัวใจตีบ #เรย์แม็คโดนัลด์ #พันธุกรรม', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/20/tiktok_7676074306425720085_729749908.webp', '2,206', '54,291'),
        ],
        'Instagram': [
            ('21 Aug 2026', '|❤️ เส้นเลือดหัวใจตีบ 3 เส้น เกิดขึ้นได้อย่างไร? แล้วเราจะรู้ได้อย่างไรว่ากำลังมีความเสี่ยง? 🎥 มาฟังคำตอบจาก นพ. นาวี ตันจรารักษ์ อายุรแพทย์โรคหัวใจ ได้ในคลิปนี้ค่ะ #โรงพยาบาลสมิติเวช #samitivej #เรา', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/21/instagram_344275618_DcSnH-0xUPA_133463797.webp', '138', '3,515'),
            ('20 Aug 2026', '|สมิติเวชร่วมส่งเสริมการเลี้ยงลูกด้วยนมแม่ ในงาน World Breastfeeding Week 2026 นำทีมโดย พญ.สุรางคณา เตชะไพฑูรย์ รองประธานเจ้าหน้าที่บริหารกลุ่ม รพ.สมิติเวช และ รพ.บีเอ็นเอช, นพ.อดินันท์ กิตติรัตนไพบูล', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/20/instagram_344275618_DcQJs3xkXnF_282408536.webp', '62', ''),
            ('11 Aug 2026', '|🤱World Breastfeeding Week 2026 โรงพยาบาลสมิติเวช สุขุมวิท ร่วมรณรงค์ “สายใยรักนมแม่” ส่งเสริมความสำคัญของนมแม่ในฐานะจุดเริ่มต้นของการดูแลลูกน้อย และสายใยความผูกพันของครอบครัว ได้รับเกียรติจาก นพ.นิธ', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/11/instagram_344275618_Db5bJjGCU9w_157239158.webp', '58', ''),
            ('28 Aug 2026', '|🏃‍♀️ สมิติเวช ศรีนครินทร์ เปิดบ้านต้อนรับวัยเก๋า 50+ ในงาน Age Friendly Run 2026 by Samitivej : วิ่งละ YOUNG ครั้งที่ 3 วิ่งปลอดภัยกับ Doctor & Nurse Runners กว่า 100 คน ร่วมดูแลความปลอดภัยตลอดเส้นท', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/28/instagram_344275618_DckWc9eEUsm_134271457.webp', '56', ''),
            ('18 Aug 2026', '|💚 สมิติเวชอยากให้ ”ชุดตรวจสุขภาพ“ ไม่ได้เป็นเพียงเรื่องของความสะดวกในการตรวจ แต่ใส่ใจในรายละเอียดของผู้สวมใส่ ตั้งแต่ ดีไซน์ที่เรียบหรู สวมใส่สบาย เคลื่อนไหวได้สะดวก ไปจนถึงรูปแบบที่สามารถนำไปสวมใส่', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/18/instagram_344275618_DcKuKSbkfKj_128642578.webp', '44', ''),
        ],
        'YouTube': [
            ('13 Aug 2026', 'นอนหลับทั้งคืน แต่ง่วงทั้งวัน? เช็ก Sleep Quality และ “หนี้การนอน” | Healthspan with Smith EP.21|หลายคนเชื่อว่า แค่นอนให้ครบ 7–8 ชั่วโมง ร่างกายก็น่าจะได้พักเพียงพอแล้ว แต่ความจริง “จำนวนชั่วโมงที่นอน', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/15/youtube_s-n1mfpdSPs_113779488.webp', '724', '250,615'),
            ('25 Aug 2026', 'ไขมันในเลือดสูง โรคที่ไม่มีอาการ...แต่เสี่ยงโรคหัวใจได้มากกว่าที่คิด! | Healthspan with Smith EP.22|ผอม…แต่ไขมันสูง! ทำไมถึงเสี่ยงโรคหัวใจ? เชื่อว่า…หลายคนตรวจพบว่า “ไขมันในเลือดสูง” แต่เพราะยังแข็งแร', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/29/youtube_edSdBoLCr7g_143989248.webp', '405', '43,864'),
            ('18 Aug 2026', 'นอนอย่างไรให้มีคุณภาพ? เทคนิคง่าย ๆ ที่ช่วยให้ร่างกายฟื้นได้ดีขึ้น | Healthspan with Smith EP.21|#healthspanwithsmith #เราไม่อยากให้ใครป่วย #โรงพยาบาลสมิติเวช #SamitivejHospital 📞 ติดต่อนัดหมายแพทย์ ', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/18/youtube_DvJjV3f2Ark_468054862.webp', '89', '1,910'),
            ('25 Aug 2026', 'Healthspan with Smith EP.22 | ไขมันในเลือดสูง โรคที่ไม่มีอาการ...แต่เสี่ยงโรคหัวใจได้มากกว่าที่คิด!|Highlights Healthspan with Smith EP.22 | ไขมันในเลือดสูง โรคที่ไม่มีอาการ...แต่เสี่ยงโรคหัวใจได้มากก', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/25/youtube__Qb5_FESYhY_119283811.webp', '53', '1,576'),
            ('17 Aug 2026', 'นอนน้อยเมื่อคืน วันนี้นอนเพิ่ม ชดเชยกันได้ไหม? | Healthspan with Smith EP.21|#healthspanwithsmith #เราไม่อยากให้ใครป่วย #โรงพยาบาลสมิติเวช #SamitivejHospital 📞 ติดต่อนัดหมายแพทย์ ได้ที่ 02-022-2086 ห', 'https://wisesight-image-attachments.s3.ap-southeast-1.amazonaws.com/2026/08/17/youtube_TnEa_BJkGU4_118380043.webp', '44', '1,555'),
        ],
        'x': [
            ('06 Aug 2026', 'โรคไหลตาย (Sudden Unexplained Nocturnal Death Syndrome: SUNDS) คือภาวะเสียชีวิตกะทันหันระหว่างนอนหลับโดยไม่ทราบสาเหตุที่แน่ชัด อาจเกี่ยวข้องกับความผิดปกติของระบบไฟฟ้าหัวใจ หรือโครงสร้างหัวใจที่ทำให้หั', '', '7,268', ''),
            ('20 Aug 2026', 'โรคหลอดเลือดหัวใจตีบตันตัน เกิดจากไขมันและหินปูน สะสมอยู่ภายในหลอดเลือดแดงจนเกิดการอุดตัน หรือเส้นเลือดเกิดการปริแตกขึ้น ทำให้กล้ามเนื้อหัวใจขาดเลือดไปเลี้ยงได้ค่ะ อาการของ #โรคหลอดเลือดหัวใจตีบชนิดเฉ', '', '7,032', ''),
            ('09 Aug 2026', 'อยากกินผลไม้ แต่กลัวน้ำตาลสูง ลองเลือกผลไม้ 4 ชนิดนี้ดูค่ะ - แอปเปิ้ล มีกากใยสูง ช่วยเรื่องระบบขับ และมีวิตามินซี ป้องกันโรคหวัด - ชมพู่ ช่วยเรื่องระบบขับถ่าย ลดคอเลสเตอรอล - ฝรั่ง มีวิตามินซีสูง ป้อง', '', '4,375', ''),
            ('18 Aug 2026', '5 วิธีดูแลสมอง ช่วยให้ความจำดีขึ้น 1. กินอาหารที่ดีต่อสมอง เช่น โอเมก้า-3 สารต้านอนุมูลอิสระ เช่น ปลาทะเล ถั่วและเมล็ดพืช บลูเบอร์รี และผักใบเขียว 2. ควรนอนประมาณ 7–9 ชั่วโมงต่อคืน เพราะระหว่างนอน สมอ', '', '2,861', ''),
            ('29 Aug 2026', 'อาการหลงลืมตามวัย VS สัญญาณเตือนภาวะสมองเสื่อม 🟢 หลงลืมตามวัย - ลืมกุญแจบ้านหรือแว่นตาไว้ผิดที่นานๆ ครั้ง - นึกชื่อคนหรือคำศัพท์บางคำไม่ออกในทันที แต่นึกออกในภายหลัง - ลืมเรื่องราวบางช่วงในอดีต แต่ยั', '', '2,246', ''),
        ],
    },
}

AUGUST_2026_SUMMARIES = {
    'MedCMU': {
        'brand_score': '219', 'brand_score_change': '+3.79%',
        'owned_score': '256', 'owned_score_change': '+3.64%',
        'earned_score': '151', 'earned_score_change': '+4.14%',
        'sentiment': '43.7', 'sentiment_change': '+0.46%',
        'total_posts': '199', 'total_engagement': '161,992',
    },
    'จุฬาฯ': {
        'brand_score': '192', 'brand_score_change': '+2.67%',
        'owned_score': '154', 'owned_score_change': '+1.99%',
        'earned_score': '264', 'earned_score_change': '+3.53%',
        'sentiment': '43.4', 'sentiment_change': '0.00%',
        'total_posts': '150', 'total_engagement': '27,577',
    },
    'ศิริราช': {
        'brand_score': '172', 'brand_score_change': '+2.99%',
        'owned_score': '116', 'owned_score_change': '0.00%',
        'earned_score': '276', 'earned_score_change': '+5.75%',
        'sentiment': '45.8', 'sentiment_change': '-0.87%',
        'total_posts': '26', 'total_engagement': '3,365',
    },
    'สมิติเวช': SAMITIVEJ_AUGUST['summary'],
}

# Counts, engagement and views are aggregates of the August post tables.  A
# missing platform means the source had no post row, so the dashboard leaves it
# blank instead of replacing it with a zero.
AUGUST_2026_PLATFORM_TOTALS = {
    'MedCMU': {
        'Facebook': {'total_posts': '100', 'total_engagement': '60,878'},
        'TikTok': {'total_posts': '17', 'total_engagement': '50,567', 'views': '501,023'},
        'Instagram': {'total_posts': '27', 'total_engagement': '12,324', 'views': '209,899'},
        'YouTube': {'total_posts': '23', 'total_engagement': '14,269', 'views': '481,888'},
        'x': {'total_posts': '32', 'total_engagement': '23,954'},
    },
    'จุฬาฯ': {
        'Facebook': {'total_posts': '70', 'total_engagement': '22,953'},
        'TikTok': {'total_posts': '7', 'total_engagement': '2,044', 'views': '10,718,220'},
        'Instagram': {'total_posts': '41', 'total_engagement': '2,396', 'views': '617,287,281'},
        'x': {'total_posts': '32', 'total_engagement': '184'},
    },
    'ศิริราช': {
        'Facebook': {'total_posts': '10', 'total_engagement': '3,084'},
        'TikTok': {'total_posts': '4', 'total_engagement': '27'},
        'Instagram': {'total_posts': '4', 'total_engagement': '64', 'views': '1,386'},
        'YouTube': {'total_posts': '4', 'total_engagement': '163', 'views': '22,437'},
        'x': {'total_posts': '4', 'total_engagement': '27'},
    },
    'สมิติเวช': SAMITIVEJ_AUGUST['platforms'],
}


def apply_august_2026_overlay(all_data, all_fb_data, all_platform_data,
                              all_top_posts, all_top_posts_plat):
    """Merge the authenticated August source into the dashboard projection."""
    month = 'Aug'
    for brand, summary in AUGUST_2026_SUMMARIES.items():
        all_data.setdefault(brand, {})[month] = summary.copy()
        latest = all_platform_data.get(brand, {}).get('Jul', {})
        month_platforms = {}
        for platform, values in AUGUST_2026_PLATFORM_TOTALS[brand].items():
            prior = latest.get(platform, {})
            carried = {key: prior[key] for key in ('followers', 'followers_as_of') if key in prior}
            month_platforms[platform] = {**carried, **values}
        all_platform_data.setdefault(brand, {})[month] = month_platforms
        facebook = AUGUST_2026_PLATFORM_TOTALS[brand].get('Facebook')
        if facebook:
            all_fb_data.setdefault(brand, {})[month] = {
                'total_posts_fb': facebook['total_posts'],
                'total_engagement_fb': facebook['total_engagement'],
            }

    brand = 'สมิติเวช'

    platform_posts = {}
    for platform, records in SAMITIVEJ_AUGUST['posts'].items():
        platform_posts[platform] = [
            {'platform': platform, 'date': date, 'message': message, 'image_url': image_url,
             'engagement': engagement, 'views': views}
            for date, message, image_url, engagement, views in records
        ]
    all_top_posts_plat.setdefault(brand, {})[month] = platform_posts
    all_posts = [post for posts in platform_posts.values() for post in posts]
    all_posts.sort(key=lambda post: int(post['engagement'].replace(',', '')), reverse=True)
    all_top_posts.setdefault(brand, {})[month] = all_posts[:10]

# ─── Main ─────────────────────────────────────────────────────────────────────
DATA_FILES = {
    'MedCMU':   '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/MEDCMU_data2026.csv',
    'จุฬาฯ':    '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/CU_data2026.csv',
    'ศิริราช':  '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/SI_data2026.csv',
    'สมิติเวช': '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/Samitivej_data2026.csv',
}
POST_FILES = {
    'MedCMU':   '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/MEDCMU2026.csv',
    'จุฬาฯ':    '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/CU2026.csv',
    'ศิริราช':  '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/SI2026.csv',
    'สมิติเวช': '/Users/chagkrit/Library/CloudStorage/GoogleDrive-nansurg7@gmail.com/My Drive/04_งานแพทย์ & โรงพยาบาล/Social MEDCMU/MEDCMU DATA 2026/Samitivej2026.csv',
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

apply_august_2026_overlay(
    all_data, all_fb_data, all_platform_data, all_top_posts, all_top_posts_plat
)

blocks = {
    'DATA':           build_DATA_js(all_data),
    'FB_DATA':        build_FB_DATA_js(all_fb_data),
    'TOP_POSTS':      build_posts_block('TOP_POSTS', 'let', all_top_posts, False),
    'TOP_POSTS_PLAT': build_posts_block('TOP_POSTS_PLAT', 'const', all_top_posts_plat, True),
    'PLATFORM_DATA':  build_PLATFORM_DATA_js(all_platform_data),
}

# ─── Patch HTML ──────────────────────────────────────────────────────────────
DASHBOARD_DIR = __file__.rsplit('/', 1)[0]
DASHBOARD_PATH = DASHBOARD_DIR + '/brand_scan_dashboard.html'
INDEX_PATH = DASHBOARD_DIR + '/index.html'
with open(DASHBOARD_PATH, encoding='utf-8') as f:
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
html = html.replace('Data: Jan–Jul 2026', 'Data: Jan–Aug 2026')
html = html.replace('Jan – Jul 2026', 'Jan – Aug 2026')
html = html.replace("let currentMonth = 'Jul';", "let currentMonth = 'Aug';")
html = html.replace('ยอด Engagement รายเดือน Jan–Jul 2026', 'ยอด Engagement รายเดือน Jan–Aug 2026')

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

for output_path in (DASHBOARD_PATH, INDEX_PATH):
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
print(f'\nSaved dashboard and index. Total chars: {len(html):,}')
