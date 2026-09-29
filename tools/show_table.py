import sys
import xml.etree.ElementTree as ET
import zipfile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def ptext(p):
    return ''.join((n.text or '') for n in p.iter() if n.tag == W + 't')


def main(path, want):
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    for i, ch in enumerate(body):
        if ch.tag != W + 'tbl':
            continue
        rows = ch.findall(W + 'tr')
        flat = ' '.join(ptext(p) for r in rows for p in r.iter(W + 'p'))
        if want.lower() not in flat.lower():
            continue
        print(f'--- TABLE at index {i}, rows={len(rows)} ---')
        for r in rows:
            cells = [' '.join(ptext(p) for p in tc.iter(W + 'p'))
                     for tc in r.findall(W + 'tc')]
            print(' ||| '.join(cells))
        print()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
