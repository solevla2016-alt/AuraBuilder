import re
import sys
import zipfile
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def ptext(p):
    parts = []
    for n in p.iter():
        if n.tag == W + 't':
            parts.append(n.text or '')
        elif n.tag in (W + 'br', W + 'cr'):
            parts.append(' ')
        elif n.tag == W + 'tab':
            parts.append('\t')
    return ''.join(parts)


def rows_of(tbl):
    out = []
    for r in tbl.findall(W + 'tr'):
        out.append([' '.join(ptext(p) for p in tc.iter(W + 'p'))
                    for tc in r.findall(W + 'tc')])
    return out


def main(path):
    z = zipfile.ZipFile(path)
    print(f'zip entries: {len(z.namelist())}  testzip: {z.testzip()}')
    root = ET.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    print(f'body nodes: {len(list(body))}')

    # 1. целостность XML
    ET.fromstring(z.read('word/numbering.xml'))
    print('numbering.xml: OK')
    ET.fromstring(z.read('word/styles.xml'))
    print('styles.xml: OK')

    # 2. numId-ссылки существуют
    num = ET.fromstring(z.read('word/numbering.xml'))
    defined = {n.get(W + 'numId') for n in num.iter(W + 'num')}
    used = set()
    for p in body.iter(W + 'numId'):
        used.add(p.get(W + 'val'))
    missing = used - defined
    print(f'numId used={len(used)} defined={len(defined)} '
          f'missing={sorted(missing) if missing else "none"}')

    # 3. пустые абзацы подряд (потерянный контент)
    empties = [i for i, ch in enumerate(body)
               if ch.tag == W + 'p' and not ptext(ch).strip()]
    print(f'empty paragraphs: {len(empties)}')

    # 4. таблицы: единая ширина строк
    bad = []
    for i, ch in enumerate(body):
        if ch.tag != W + 'tbl':
            continue
        rows = rows_of(ch)
        widths = {len(r) for r in rows}
        if len(widths) > 1:
            bad.append((i, sorted(widths), rows[0][:3]))
    print(f'tables: {sum(1 for c in body if c.tag == W + "tbl")}, '
          f'inconsistent: {len(bad)}')
    for i, wdt, first in bad:
        print(f'  !! idx {i} widths={wdt} head={first}')

    # 5. заголовки без содержимого
    text = '\n'.join(ptext(p) for p in body.iter(W + 'p'))
    heads = re.findall(r'^\d+(?:\.\d+)*\.\s+[^\n]+$', text, re.M)
    print(f'section headings found: {len(heads)}')

    # 6. остатки запрещённых терминов
    for term in ['Resend', 'Dovecot', 'RabbitMQ', 'ClamAV', 'SonarQube',
                 'FOSSA', 'GitLab CE (self-hosted)', 'Redis 7+', 'python']:
        n = text.count(term)
        mark = '!!' if n else 'ok'
        print(f'  {mark} "{term}": {n}')

    # 7. длины абзацев
    long_p = [(i, len(ptext(p))) for i, p in enumerate(body.iter(W + 'p'))
              if len(ptext(p)) > 700]
    print(f'paragraphs >700 chars: {len(long_p)}')
    for i, n in long_p:
        print(f'  idx {i}: {n}')

    # 8. протечки директив спецификации в текст документа
    leaked = [(i, ptext(p).strip()) for i, p in enumerate(body.iter(W + 'p'))
              if ptext(p).strip() in ('TABLE', 'ENDTABLE', 'NEW', 'PARA',
                                      'ROW') or ptext(p).strip().startswith('B|')]
    print(f'leaked spec directives: {len(leaked)}')
    for i, t in leaked:
        print(f'  !! idx {i}: {t!r}')

    # 9. заголовки-разделители подряд
    print('--- готово ---')


if __name__ == '__main__':
    main(sys.argv[1])
