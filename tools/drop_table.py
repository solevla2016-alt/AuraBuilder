import sys
import xml.etree.ElementTree as ET
import zipfile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def ptext(p):
    return ''.join((n.text or '') for n in p.iter() if n.tag == W + 't')


def main(path, keep_marker, drop_marker):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    data = {n: z.read(n) for n in names}
    root = ET.fromstring(data['word/document.xml'])
    body = root.find(W + 'body')
    target = None
    for i, ch in enumerate(body):
        if ch.tag != W + 'tbl':
            continue
        flat = ' '.join(ptext(p) for r in ch.findall(W + 'tr') for p in r.iter(W + 'p'))
        if drop_marker in flat and keep_marker in flat:
            target = i
            break
    if target is None:
        print('not found')
        return 1
    body.remove(list(body)[target])
    data['word/document.xml'] = ET.tostring(root, encoding='UTF-8', xml_declaration=True)
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            zo.writestr(n, data[n])
    import shutil
    shutil.move(tmp, path)
    print(f'removed stale table at index {target}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
