from django.contrib import admin

from django_activitypub.models import LocalActor, RemoteActor, Follower, Note


admin.site.register(LocalActor)
admin.site.register(RemoteActor)
admin.site.register(Follower)
admin.site.register(Note)
