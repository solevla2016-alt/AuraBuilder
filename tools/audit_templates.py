import glob
import os
import re

FILES = sorted(glob.glob(r'C:\Users\Пользователь\Downloads\Qwen_html_*.html'))

CHECKS = [
    ('fonts.googleapis', r'fonts\.googleapis\.com'),
    ('fonts.gstatic', r'fonts\.gstatic\.com'),
    ('prefers-reduced-motion', r'prefers-reduced-motion'),
    ('aria-роли', r'aria-(role|label|expanded|controls)='),
    ('role=', r'\brole='),
    (':focus-visible', r':focus-visible'),
    ('outline:none без замены', r'outline:\s*none'),
    ('emojи как иконки', r'font-size:\d+px[^;]*;\s*">[\U0001F300-\U0001FAFF☀-➿]'),
    ('inline style= в разметке', r'<div[^>]+style="'),
    ('position:fixed панелей', r'position:\s*fixed'),
    ('z-index:-1 backlight', r'z-index:\s*-1'),
    ('keyframes анимаций', r'@keyframes'),
    ('animation infinite', r'animation:[^;]*infinite'),
    ('will-change', r'will-change'),
    ('contain:', r'\bcontain:'),
    ('SVG инлайн', r'<svg'),
    ('canvas', r'<canvas'),
]

rows = []
for f in FILES:
    src = open(f, encoding='utf-8').read()
    title = re.search(r'<title>([^<]+)</title>', src)
    title = title.group(1).replace('AuraBuilder — ', '').replace('AuraBuilder - ', '') if title else '?'
    marks = []
    for label, pat in CHECKS:
        n = len(re.findall(pat, src))
        marks.append(f'{label}={n}')
    rows.append((title, marks, len(src)))

names = [c[0] for c in CHECKS]
w = max(len(n) for n in names) + 1
print('экран'.ljust(22) + ''.join(n.split('=')[0][:11].rjust(13) for n in names))
print('-' * (22 + 13 * len(names)))
for title, marks, size in rows:
    print(title[:21].ljust(22) + ''.join(
        m.split('=')[1].rjust(13) for m in marks))
