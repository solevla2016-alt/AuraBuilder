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
    path('api/projects/<str:project_id>/site/backup/',
         api.project_site_backup, name='project-site-backup'),
    path('sites/<slug:slug>/', views.published_site, name='published-site'),
    re_path(r'^sites/(?P<slug>[a-z0-9-]+)/(?P<path>.*)$',
            views.serve_site, name='published-site-file'),
]
