import subprocess
import sys

DOCX, TZE = sys.argv[1], sys.argv[2]

REPL = [
    ('🆕 Email-сервис РФ: Mailganer (основной) + self-hosted SMTP (резерв) — восстановление пароля и уведомления',
     '🆕 Email-сервис: Яндекс 360 SMTP (основной) + локальный relay (резерв) — восстановление пароля и уведомления'),
    ('Автоматический фейловер на self-hosted SMTP при недоступности Mailganer (3 ошибки подряд)',
     'Автоматический фейловер на локальный relay при недоступности SMTP Яндекса (3 ошибки подряд)'),
    ('🆕 Mailganer (транзакционные письма, в реестре российского ПО): от 30 000 ₽ (до 1 000 000 писем/мес)',
     '🆕 Яндекс 360 (почта для бизнеса, SMTP-релей): от 0 ₽ при своём домене; тарифы зависят от числа пользователей'),
    ('Mailganer — основной провайдер (участник реестра российского ПО № 20310, серверы в РФ, 152-ФЗ)',
     'Яндекс 360 — основной провайдер (российский резидент, серверы в РФ, 152-ФЗ, трансграничная передача исключена)'),
    ('Fallback: собственный SMTP (Maddy + Rspamd) на серверах платформы в РФ',
     'Fallback: локальный relay (Postfix или Maddy + Rspamd) на серверах платформы в РФ'),
    ('Автоматическое переключение по circuit breaker; Resend, Dovecot и ClamAV исключены по п.7.6.4',
     'Автоматическое переключение по circuit breaker; Resend, Dovecot и ClamAV исключены по п.7.6.4. Mailganer — резервный вариант при нехватке квоты Яндекса'),
    ('🆕 Резервный SMTP (Maddy + Rspamd, прогрев IP): от 3 000 ₽ + выделенный IP',
     '🆕 Резервный локальный relay (Maddy + Rspamd): от 3 000 ₽ + выделенный IP для прогрева репутации'),
]

for old, new in REPL:
    r = subprocess.run([sys.executable, TZE, 'replace', DOCX, old, new],
                       capture_output=True, text=True, encoding='utf-8')
    out = (r.stdout or '').strip()
    n = out.replace('replaced in ', '').replace(' paragraphs', '')
    print(('OK  ' if n != '0' else '!!  ') + f'{n:>2s}  ' + old[:58])
