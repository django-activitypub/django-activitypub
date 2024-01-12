==================
django-activitypub
==================

This is an reusable Django app implementing the `ActivityPub <https://www.w3.org/TR/activitypub/>`_ protocol with
the intent of allowing any Django project to be federated with other ActivityPub-compliant servers.

It currently provides:

* Models for ActivityPub objects and associated admin interface
* View implementations for serving the ActivityPub protocol API
* Helpers for rendering ActivityPub interactions in Django templates
* @Mention parsing and auto-linking in content models

Current Status
--------------

This project is in the early stages of development. It is not yet ready for production use. The API is likely to change,
security issues are likely to be present, and there are many missing features. That said, it is usable for testing and
experimentation. The maintainer of the libray is using it for their own `website <https://sam.sutch.net>`_.

.. warning::

    This is alpha-quality software without significant production usage. It has not been security reviewed.
    It is not recommended for production use.

**Supported ActivityPub features:**

* `Webfinger <https://webfinger.net/>`_ endpoint and discovery (both acct adn http(s) URIs)
* One or more local actors (paired with your User model) with outbox and followers collections
* Local actor inbox supports Follow, Like, Announce, Create, and Undo [Follow, Like, Announce]
* Delivery of activities to local actor followers

**Roadmap:**

* Signing of incoming and outgoing GET requests
* Support for other ActivityPub object types (Article, Image, Video, etc.)
* Support background processing of incoming activities
* Support background delivery of outgoing activities

Quick Start
-----------

1. Install django-activitypub:

.. code-block:: bash

    pip install django-activitypub

2. Add "django_activitypub" to your INSTALLED_APPS setting like this:

.. code-block:: python

    INSTALLED_APPS = [
        ...,
        'django_activitypub',
    ]

3. Include the django_activitpub URLconf in your project urls.py like this:

.. code-block:: python

    path('', include('django_activitypub.urls')),  # this can be customized later

4. Run ``python manage.py migrate`` to create the activitypub models.

5. Create instances of ``LocalActor`` for your user profiles:

.. code-block:: python

    from django.contrib.auth import get_user_model
    from django_activitypub.models import LocalActor

    user = get_user_model().objects.get(username='myuser')
    LocalActor.objects.create(user=user, name=user.username, preferred_username=user.username)

6. Publish your content by creating a note:

.. code-block:: python

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


7. Start the development server and check the ActivityPub URLs:

.. code-block:: bash

    python manage.py runserver
    http get http://127.0.0.1:8000/pub/myuser Accept:application/activity+json

8. You can also use the Django Admin to create new Notes and LocalActors.

Security
--------

Currently there is a fairly bare-bone approach to security, implementing the the minimum required to successfully
communicate with other ActivityPub servers and protect library integrators from common attacks.

* HTTP POST requests to the inbox are currently verified
* HTTP POST requests to follower inboxes are signed by a local per-user key stored in the database
* When remote content is displayed in a template, the content is sanitized or escaped

Please send any security issues immediately to the maintainer: `security@steamboatlabs.com <mailto:security@steamboatlabs.com>`_

Interoperability
----------------

Verified interoperability with:

* ✅ Mastodon
* ❓Pleroma
* Others