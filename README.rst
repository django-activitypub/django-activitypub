==================
django-activitypub
==================

This is an experimental Django app implementing the `ActivityPub <https://www.w3.org/TR/activitypub/>`_ protocol with
the intent of allowing any Django project to be federated with other ActivityPub-compliant servers.

Quick Start
-----------

1. Install django-activitypub:

    pip install django-activitypub

2. Add "django_activitypub" to your INSTALLED_APPS setting like this::

    INSTALLED_APPS = [
        ...,
        'django_activitypub',
    ]

3. Include the django_activitpub URLconf in your project urls.py like this::

    path('', include('django_activitypub.urls')),  # this can be customized later

4. Run ``python manage.py migrate`` to create the activitypub models.

5. Create instances of ``LocalActor`` for your user profiles::

    from django.contrib.auth import get_user_model
    from django_activitypub.models import LocalActor

    user = get_user_model().objects.get(username='myuser')
    LocalActor.objects.create(user=user, name=user.username, preferred_username=user.username)

6. Publish your content by creating a note::

    from django_activitypub.models import LocalActor, Note

    class MyModel(models.Model):
        # ... your model fields
        def publish(self, base_uri):
            actor = LocalActor.objects.get(user=self.author)
            Note.objects.upsert(
                base_uri=base_uri,
                local_actor=actor,
                content=self.formatted_content(),
                content_url=f'{base_uri}{self.get_absolute_url()}'
            )


7. Start the development server and check the ActivityPub URLs::

    python manage.py runserver
    http get http://127.0.0.1:8000/pub/myuser Accept:application/activity+json

8. You can also use the Django Admin to create new Notes and LocalActors.