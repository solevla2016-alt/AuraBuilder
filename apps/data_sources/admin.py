from django.contrib import admin

from .models import DataRecord, DataSource

admin.site.register(DataSource)
admin.site.register(DataRecord)
