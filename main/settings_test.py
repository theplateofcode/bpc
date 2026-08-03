"""Settings for running the test suite.

Identical to main.settings except the database, so tests can run on any machine
without a MySQL server. Nothing here is used in production.

    python manage.py test --settings=main.settings_test
"""
from main.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

DEBUG = False

# Keep password hashing out of the runtime of a 400-booking seed.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
