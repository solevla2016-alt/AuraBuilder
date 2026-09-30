import sys
import xml.etree.ElementTree as ET
import zipfile
import shutil

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def ptext(p):
    return ''.join((n.text or '') for n in p.iter() if n.tag == W + 't')


def main(path):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    data = {n: z.read(n) for n in names}
    root = ET.fromstring(data['word/document.xml'])
    body = root.find(W + 'body')
    leaked = [i for i, ch in enumerate(body)
              if ch.tag == W + 'p'
              and ptext(ch).strip() in ('ENDTABLE', 'TABLE', 'NEW', 'PARA', 'ROW')]
    for i in leaked:
        print(f'removing idx {i}: {ptext(list(body)[i]).strip()!r}')
    for i in sorted(leaked, reverse=True):
        body.remove(list(body)[i])
    data['word/document.xml'] = ET.tostring(root, encoding='UTF-8',
                                            xml_declaration=True)
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            zo.writestr(n, data[n])
    shutil.move(tmp, path)
    print(f'removed {len(leaked)} leaked directives')


if __name__ == '__main__':
    main(sys.argv[1])
