import glob
import os
import re

files = sorted(glob.glob(r'C:\Users\Пользователь\Downloads\Qwen_html_*.html'))

for f in files:
    src = open(f, encoding='utf-8').read()
    title = re.search(r'<title>([^<]+)</title>', src)
    title = title.group(1) if title else '?'
    btns = re.findall(r'sw-btn[^>]*data-v="(\d+)"[^>]*>([^<]+)<', src)
    vbtns = re.findall(r'variant-btn[^>]*data-variant="(\d+)"[^>]*>([^<]+)<', src)
    rows = btns or vbtns
    size_kb = os.path.getsize(f) // 1024
    name = os.path.basename(f)
    print(f'\n=== {name} ({size_kb} KB) :: {title} ===')
    for _, label in rows:
        print(f'   {label.strip()}')
    # ключевые структурные признаки
    flags = []
    if 'class="floating"' in src:
        flags.append('floating-palette')
    if 'grid-canvas' in src or 'graph-canvas' in src:
        flags.append('canvas/graph')
    if 'data-table' in src:
        flags.append('table')
    if 'conic-gradient' in src or 'svg' in src:
        flags.append('charts')
    if 'prefers-reduced-motion' in src:
        flags.append('HAS-reduced-motion')
    else:
        flags.append('NO-reduced-motion')
    print('   flags:', ', '.join(flags))
