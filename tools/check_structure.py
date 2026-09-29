import collections
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def ptext(p):
    return ''.join((n.text or '') for n in p.iter() if n.tag == W + 't')


def main(path):
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')

    heads = []
    for i, ch in enumerate(body):
        if ch.tag != W + 'p':
            continue
        t = ptext(ch).strip()
        if re.match(r'^\d+(\.\d+)*\.\s+\S', t):
            heads.append((i, t))

    print(f'заголовков с нумерацией: {len(heads)}')
    seen = collections.Counter(t for _, t in heads)
    dups = {t: c for t, c in seen.items() if c > 1}
    if dups:
        print('ДУБЛИ ЗАГОЛОВКОВ:')
        for t, c in dups.items():
            idxs = [i for i, tt in heads if tt == t]
            print(f'  x{c} {t!r}  индексы {idxs}')
    else:
        print('дублей заголовков нет')

    # подряд идущие одинаковые непустые абзацы
    prev = None
    runs = 0
    for i, ch in enumerate(body):
        if ch.tag != W + 'p':
            prev = None
            continue
        t = ptext(ch).strip()
        if t and t == prev:
            runs += 1
            print(f'  !! повтор подряд, idx {i}: {t[:80]!r}')
        prev = t
    print(f'повторов подряд: {runs}')

    # последовательность номеров разделов
    nums = [re.match(r'^(\d+(?:\.\d+)*)\.', t).group(1) for _, t in heads]
    print('последовательность:', ', '.join(nums[:14]), '...')
    top = [n for n in nums if n.count('.') == 0]
    print('разделы верхнего уровня:', ', '.join(top))


if __name__ == '__main__':
    main(sys.argv[1])
