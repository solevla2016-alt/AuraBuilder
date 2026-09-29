def lum(hexstr):
    h = hexstr.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def ch(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


PAIRS = [
    ('Акцент #D4B896', 'Фон #F5EFE0', '#D4B896', '#F5EFE0'),
    ('Текст #3A3428', 'Фон #F5EFE0', '#3A3428', '#F5EFE0'),
    ('Текст #3A3428', 'Панель #FBF6E8', '#3A3428', '#FBF6E8'),
    ('Мягкий текст #7A6F58', 'Фон #F5EFE0', '#7A6F58', '#F5EFE0'),
    ('Вторичный #C9B896', 'Фон #F5EFE0', '#C9B896', '#F5EFE0'),
]

print(f'{"элемент":34s} {"контраст":>9s}  норма')
print('-' * 66)
for name1, name2, c1, c2 in PAIRS:
    r = ratio(c1, c2)
    if r >= 7:
        verdict = 'AAA (>=7)'
    elif r >= 4.5:
        verdict = 'AA текст (>=4.5)'
    elif r >= 3:
        verdict = 'AA крупный / UI (>=3)'
    else:
        verdict = 'НЕ ПРОХОДИТ (<3)'
    print(f'{name1 + " на " + name2:34s} {r:8.2f}:1  {verdict}')

print()
print('Кандидаты на затемнение акцента для текста на фоне #F5EFE0:')
for c in ('#D4B896', '#B08D5F', '#9A7845', '#8A6A3A', '#7A5C30', '#6B4F28'):
    print(f'  {c} -> {ratio(c, "#F5EFE0"):.2f}:1')
