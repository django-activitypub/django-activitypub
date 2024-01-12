import os
import sys
import django
from django.conf import settings
from django.core.management import call_command

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

sys.path.insert(0, PROJECT_DIR)

settings.configure(
    DEBUG=True,
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(PROJECT_DIR, "db.sqlite3"),
        }
    },
    INSTALLED_APPS=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django_activitypub",
    ],
    TIME_ZONE="UTC",
    USE_TZ=True,
)

django.setup()

call_command("makemigrations", "activitypub")
