"""Инструмент правки ТЗ (docx).

Работает напрямую с word/document.xml через ElementTree.
Основные операции:
  map     - показать карту абзацев (индекс, текст)
  find    - найти абзацы по подстроке
  replace - заменить текст в абзаце
  cell    - заменить текст ячейки таблицы (номер строки, номер столбца)
  set     - заменить целый диапазон абзацев новым содержимым
"""

import copy
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

DOCX = None
XML = None


def load(path):
    global DOCX, XML
    DOCX = path
    with zipfile.ZipFile(path) as z:
        XML = z.read('word/document.xml')
    return ET.fromstring(XML)


MONO = 'Consolas'


def save(root, path, extra=None):
    out = XML[:0] + ET.tostring(root, encoding='UTF-8', xml_declaration=True)
    tmp = path + '.tmp'
    with zipfile.ZipFile(DOCX) as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}
    data['word/document.xml'] = out
    if extra:
        for name, content in extra.items():
            data[name] = content if isinstance(content, bytes) else content.encode('utf-8')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, data[n])
    shutil.move(tmp, path)


def ensure_numbering(numids):
    """Создаёт w:num для указанных numId, ссылаясь на существующие abstractNum.
    numids: [(numId, abstractNumId), ...]"""
    path = 'word/numbering.xml'
    with zipfile.ZipFile(DOCX) as z:
        raw = z.read(path).decode('utf-8')
    added = []
    for numid, absid in numids:
        if f'w:numId="{numid}"' in raw:
            continue
        block = (f'<w:num w:numId="{numid}">'
                 f'<w:abstractNumId w:val="{absid}"/>'
                 f'</w:num>')
        raw = raw.replace('</w:numbering>', block + '</w:numbering>')
        added.append(numid)
    return path, raw, added


def body(root):
    return root.find(W + 'body')


def ptext(p):
    parts = []
    for node in p.iter():
        if node.tag == W + 't':
            parts.append(node.text or '')
        elif node.tag in (W + 'br', W + 'cr'):
            parts.append(' ')
        elif node.tag == W + 'tab':
            parts.append('\t')
    return ''.join(parts)


def cmd_map(root, args):
    b = body(root)
    for i, ch in enumerate(b):
        if ch.tag == W + 'p':
            t = ptext(ch).strip()
            st = style_of(ch)
            np = numpr(ch)
            mark = 'P'
            if np:
                mark = f'L{np[1]}.{np[0]}'
            if st:
                mark += f'[{st}]'
            print(f'{i:5d} {mark:14s} {t[:150]}')
        elif ch.tag == W + 'tbl':
            rows = len(ch.findall(W + 'tr'))
            print(f'{i:5d} {"TABLE":14s} rows={rows}')
        else:
            print(f'{i:5d} {ch.tag.replace(W, ""):14s}')
    return 0


def style_of(p):
    ppr = p.find(W + 'pPr')
    if ppr is None:
        return ''
    st = ppr.find(W + 'pStyle')
    return st.get(W + 'val') if st is not None else ''


def numpr(p):
    ppr = p.find(W + 'pPr')
    if ppr is None:
        return None
    n = ppr.find(W + 'numPr')
    if n is None:
        return None
    ilvl = n.find(W + 'ilvl')
    numid = n.find(W + 'numId')
    return (
        ilvl.get(W + 'val') if ilvl is not None else '0',
        numid.get(W + 'val') if numid is not None else '?',
    )


def cmd_find(root, args):
    needle = args[0].lower()
    b = body(root)
    for i, ch in enumerate(b):
        if ch.tag == W + 'p':
            t = ptext(ch).strip()
            if needle in t.lower():
                print(f'{i:5d} {t[:200]}')
    return 0


def set_text(p, text):
    """Заменяет текст абзаца, сохраняя форматирование первого run."""
    runs = p.findall(W + 'r')
    if not runs:
        r = ET.SubElement(p, W + 'r')
        t = ET.SubElement(r, W + 't')
        t.text = text
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        return
    first = runs[0]
    rpr = first.find(W + 'rPr')
    for r in runs[1:]:
        p.remove(r)
    for tnode in first.findall(W + 't'):
        first.remove(tnode)
    for br in first.findall(W + 'br'):
        first.remove(br)
    for pict in first.findall(W + 'pict'):
        first.remove(pict)
    t = ET.SubElement(first, W + 't')
    t.text = text
    t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def mkpara(text, bold=False, ilvl=None, numid=None, style=None, code=False, italic=False):
    p = ET.Element(W + 'p')
    ppr = ET.SubElement(p, W + 'pPr')
    if style:
        s = ET.SubElement(ppr, W + 'pStyle')
        s.set(W + 'val', style)
    if code:
        shd = ET.SubElement(ppr, W + 'shd')
        shd.set(W + 'val', 'clear')
        shd.set(W + 'color', 'auto')
        shd.set(W + 'fill', 'F5EFE0')
        spc = ET.SubElement(ppr, W + 'spacing')
        spc.set(W + 'before', '0')
        spc.set(W + 'after', '0')
        ind = ET.SubElement(ppr, W + 'ind')
        ind.set(W + 'left', '284')
    if numid is not None:
        npr = ET.SubElement(ppr, W + 'numPr')
        il = ET.SubElement(npr, W + 'ilvl')
        il.set(W + 'val', str(ilvl or 0))
        ni = ET.SubElement(npr, W + 'numId')
        ni.set(W + 'val', str(numid))
    r = ET.SubElement(p, W + 'r')
    rpr = ET.SubElement(r, W + 'rPr')
    if code:
        rf = ET.SubElement(rpr, W + 'rFonts')
        rf.set(W + 'ascii', MONO)
        rf.set(W + 'hAnsi', MONO)
        rf.set(W + 'cs', MONO)
        sz = ET.SubElement(rpr, W + 'sz')
        sz.set(W + 'val', '18')
        szcs = ET.SubElement(rpr, W + 'szCs')
        szcs.set(W + 'val', '18')
    if bold:
        ET.SubElement(rpr, W + 'b')
        ET.SubElement(rpr, W + 'bCs')
    if italic:
        ET.SubElement(rpr, W + 'i')
        ET.SubElement(rpr, W + 'iCs')
    t = ET.SubElement(r, W + 't')
    t.text = text
    t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return p


def cmd_replace(root, args):
    old, new = args[0], args[1]
    b = body(root)
    n = 0
    for ch in b:
        if ch.tag != W + 'p':
            continue
        t = ptext(ch)
        if old in t:
            set_text(ch, t.replace(old, new))
            n += 1
    print(f'replaced in {n} paragraphs')
    return 0


BULLET_ABS = '1'
DECIMAL_ABS = '0'


def parse_spec(spec_path, first_id=200):
    """Разбирает файл спецификации в список узлов Word.

    Возвращает (nodes, needed), где needed — список пар (numId, abstractNumId),
    которые нужно создать в numbering.xml.
    """
    with open(spec_path, encoding='utf-8') as fh:
        lines = [l.rstrip('\n').rstrip('\r') for l in fh]

    nodes = []
    needed = []
    state = {'numid': None, 'kind': None, 'next': first_id}
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line == 'PARA':
            i += 1
            continue
        if line == 'NEW':
            state['numid'] = None
            state['kind'] = None
            i += 1
            continue
        if line == 'TABLE':
            rows = []
            j = i + 1
            while j < len(lines) and lines[j].rstrip() != 'ENDTABLE':
                rl = lines[j].rstrip()
                if rl.startswith('ROW|'):
                    rows.append(rl[4:].split(' ||| '))
                j += 1
            widths = {len(r) for r in rows}
            if len(widths) > 1:
                raise SystemExit(
                    f'ERROR в {spec_path}: строки таблицы разной ширины {sorted(widths)}')
            nodes.append(build_table(rows, header_rows=[0] if rows else []))
            i = j + 1
            continue
        if line.startswith('B|'):
            nodes.append(mkpara(line[2:], bold=True))
        elif line.startswith('P|'):
            nodes.append(mkpara(line[2:]))
        elif line.startswith('I|'):
            nodes.append(mkpara(line[2:], italic=True))
        elif line.startswith('CB'):
            nodes.append(mkpara('', code=True))
        elif line.startswith('C|'):
            nodes.append(mkpara(line[2:], code=True))
        elif line[:3] in ('BL|', 'DL|'):
            kind = line[:2]
            if state['numid'] is None or state['kind'] != kind:
                state['numid'] = str(state['next'])
                state['next'] += 1
                state['kind'] = kind
                needed.append((state['numid'],
                               BULLET_ABS if kind == 'BL' else DECIMAL_ABS))
            parts = line[3:].split('|', 1)
            ilvl = parts[0] if len(parts) > 1 else '0'
            text = parts[1] if len(parts) > 1 else ''
            nodes.append(mkpara(text, numid=state['numid'], ilvl=ilvl))
        else:
            nodes.append(mkpara(line))
        i += 1
    return nodes, needed


def cell_paras(tr):
    """Абзацы ячеек строки в порядке следования ячеек."""
    out = []
    for tc in tr.findall(W + 'tc'):
        out.append(tc.findall(W + 'p'))
    return out


def cmd_cell(root, args):
    """cell <table_index> <row_index> <col_index> <new_text>

    Заменяет текст ячейки таблицы. Все индексы с нуля.
    Нужна потому, что `replace` обходит только прямых потомков body
    и не заходит внутрь таблиц.
    """
    t_i = int(args[0])
    r_i = int(args[1])
    c_i = int(args[2])
    new = args[3]
    tables = body(root).findall(W + 'tbl')
    if t_i >= len(tables):
        print(f'table {t_i} not found (total: {len(tables)})')
        return 0
    trs = tables[t_i].findall(W + 'tr')
    if r_i >= len(trs):
        print(f'table {t_i} has {len(trs)} rows, no row {r_i}')
        return 0
    cells = cell_paras(trs[r_i])
    if c_i >= len(cells):
        print(f'row {r_i} has {len(cells)} cells, no cell {c_i}')
        return 0
    paras = cells[c_i]
    if not paras:
        print(f'cell {t_i},{r_i},{c_i} is empty')
        return 0
    set_text(paras[0], new)
    for extra in paras[1:]:
        for r in extra.findall(W + 'r'):
            extra.remove(r)
    print(f'cell [{t_i},{r_i},{c_i}] set: {new[:60]}')
    return 0


def cmd_set(root, args):
    """set <start> <end> <spec> [docx]

    Заменяет узлы [start, end) содержимым spec-файла.
    Директивы (по одной на строку):
      B|text          жирный абзац
      P|text          обычный абзац
      I|text          курсив
      C|text          строка кода (моноширинный, фон #F5EFE0)
      CB              пустая строка кода (разделитель)
      BL|ilvl|text    маркированный список (новый numId на блок)
      DL|ilvl|text    нумерованный список (новый numId на блок)
      NEW             начать новый блок списка
      TABLE           начало таблицы, далее ROW|a ||| b ||| c ... , затем ENDTABLE
    """
    start, end, spec = int(args[0]), int(args[1]), args[2]
    nodes, needed = parse_spec(spec)

    b = body(root)
    children = list(b)
    for idx in range(end - 1, start - 1, -1):
        if 0 <= idx < len(children):
            b.remove(children[idx])
    remaining = list(b)
    pos = min(start, len(remaining))
    for off, node in enumerate(nodes):
        b.insert(pos + off, node)

    extra = None
    if needed:
        npath, nraw, added = ensure_numbering(needed)
        extra = {npath: nraw}
        print(f'numbering: added {added}')
    print(f'replaced [{start},{end}) -> inserted {len(nodes)} nodes at {pos}')
    return extra


def build_table(rows, ncols=None, header_rows=None):
    header_rows = header_rows or []
    tbl = ET.Element(W + 'tbl')
    tblpr = ET.SubElement(tbl, W + 'tblPr')
    st = ET.SubElement(tblpr, W + 'tblStyle')
    st.set(W + 'val', 'TableGrid')
    tw = ET.SubElement(tblpr, W + 'tblW')
    tw.set(W + 'w', '0')
    tw.set(W + 'type', 'auto')
    borders = ET.SubElement(tblpr, W + 'tblBorders')
    for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        b = ET.SubElement(borders, W + side)
        b.set(W + 'val', 'single')
        b.set(W + 'sz', '4')
        b.set(W + 'color', 'D4B896')
    if ncols is None:
        ncols = max((len(r) for r in rows), default=1)
    grid = ET.SubElement(tbl, W + 'tblGrid')
    for _ in range(ncols):
        gc = ET.SubElement(grid, W + 'gridCol')
        gc.set(W + 'w', str(9000 // ncols))
    for ridx, row in enumerate(rows):
        tr = ET.SubElement(tbl, W + 'tr')
        if ridx in header_rows:
            trpr = ET.SubElement(tr, W + 'trPr')
            ET.SubElement(trpr, W + 'tblHeader')
        for c in range(ncols):
            tc = ET.SubElement(tr, W + 'tc')
            tcpr = ET.SubElement(tc, W + 'tcPr')
            tcw = ET.SubElement(tcpr, W + 'tcW')
            tcw.set(W + 'w', str(9000 // ncols))
            tcw.set(W + 'type', 'dxa')
            if ridx in header_rows:
                shd = ET.SubElement(tcpr, W + 'shd')
                shd.set(W + 'val', 'clear')
                shd.set(W + 'color', 'auto')
                shd.set(W + 'fill', 'F5EFE0')
            text = row[c] if c < len(row) else ''
            tc.append(mkpara(text, bold=(ridx in header_rows)))
    return tbl


def cmd_settable(root, args):
    """settable <index> <spec> — заменить узел (обычно таблицу) по индексу.

    Спецификация та же, что у команды set: TABLE/ROW/ENDTABLE, B|, P|, I|,
    C|, BL|, DL|, NEW. Узлы вставляются на место указанного индекса.
    """
    idx, spec = int(args[0]), args[1]
    b = body(root)
    nodes, needed = parse_spec(spec)
    children = list(b)
    old = children[idx]
    pos = list(b).index(old)
    b.remove(old)
    for off, node in enumerate(nodes):
        b.insert(pos + off, node)
    extra = None
    if needed:
        npath, nraw, added = ensure_numbering(needed)
        extra = {npath: nraw}
        print(f'numbering: added {added}')
    print(f'replaced node at {idx} ({old.tag.replace(W, "")}) '
          f'-> inserted {len(nodes)} nodes')
    return extra


def main():
    cmd = sys.argv[1]
    path = sys.argv[2]
    root = load(path)
    args = sys.argv[3:]
    extra = None
    if cmd == 'map':
        cmd_map(root, args)
        return 0
    if cmd == 'find':
        cmd_find(root, args)
        return 0
    if cmd == 'replace':
        cmd_replace(root, args)
    elif cmd == 'cell':
        extra = cmd_cell(root, args)
    elif cmd == 'set':
        extra = cmd_set(root, args)
    elif cmd == 'settable':
        extra = cmd_settable(root, args)
    else:
        print('unknown command')
        return 1
    save(root, path, extra)
    return 0


if __name__ == '__main__':
    sys.exit(main())
