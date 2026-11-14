"""Маршруты публикации и раздачи опубликованных сайтов.

Раздача объявлена последней и через префикс /sites/, чтобы не мешать
API платформы: опубликованный сайт не должен отвечать на запросы,
которые адресуются к самой платформе.
"""

from django.urls import path, re_path

from . import api, views

urlpatterns = [
    path('api/projects/<str:project_id>/site/',
         api.project_site, name='project-site'),
    path('api/projects/<str:project_id>/site/withdraw/',
         api.project_site_withdraw, name='project-site-withdraw'),
    # Отложенная публикация: задание живёт рядом с сайтом, а не как
    # отдельная сущность проекта — публикуется всегда сайт.
    path('api/projects/<str:project_id>/site/schedule/',
         api.site_schedule, name='site-schedule'),
    path('api/projects/<str:project_id>/site/schedule/<str:schedule_id>/',
         api.site_schedule_cancel, name='site-schedule-cancel'),
    path('api/projects/<str:project_id>/site/backup/',
         api.project_site_backup, name='project-site-backup'),
    path('api/projects/<str:project_id>/site/backups/',
         api.site_backups, name='site-backups'),
    # Отдельный маршрут, а не действие у списка: восстановление меняет
    # то, что увидит посетитель, и его нельзя вызвать тем же щелчком,
    # что и простое обновление списка.
    path('api/projects/<str:project_id>/site/backups/<str:backup_id>/restore/',
         api.backup_restore, name='backup-restore'),
    path('sites/<slug:slug>/', views.published_site, name='published-site'),
    re_path(r'^sites/(?P<slug>[a-z0-9-]+)/(?P<path>.*)$',
            views.serve_site, name='published-site-file'),
]
