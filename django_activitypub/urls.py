from django.urls import path
from django_activitypub.views import webfinger, profile, followers, inbox, outbox

urlpatterns = [
    path('.well-known/webfinger', webfinger, name='activitypub-webfinger'),
    path('pub/<slug:username>', profile, name='activitypub-profile'),
    path('pub/<slug:username>/followers', followers, name='activitypub-followers'),
    path('pub/<slug:username>/inbox', inbox, name='activitypub-inbox'),
    path('pub/<slug:username>/outbox', outbox, name='activitypub-outbox'),
]
