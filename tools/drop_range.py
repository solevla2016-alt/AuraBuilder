import sys
import xml.etree.ElementTree as ET
import zipfile
import shutil

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def ptext(p):
    return ''.join((n.text or '') for n in p.iter() if n.tag == W + 't')


def main(path, start, end):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    data = {n: z.read(n) for n in names}
    root = ET.fromstring(data['word/document.xml'])
    body = root.find(W + 'body')
    for lbl, i in (('first', start), ('last', end)):
        if i >= len(list(body)):
            raise SystemExit(f'{lbl} index {i} out of range')
        print(f'{lbl} {i}: {body[i].tag.replace(W, "")} '
              f'{ptext(body[i])[:70]!r}')
    children = list(body)
    for i in range(end, start - 1, -1):
        body.remove(children[i])
    data['word/document.xml'] = ET.tostring(root, encoding='UTF-8',
                                            xml_declaration=True)
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            zo.writestr(n, data[n])
    shutil.move(tmp, path)
    print(f'removed nodes [{start},{end}]')


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
