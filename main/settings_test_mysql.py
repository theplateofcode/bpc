"""Run the test suite against MySQL, which is what production actually uses.

    python manage.py test tests --settings=main.settings_test_mysql

main.settings_test runs on SQLite so the suite works anywhere with no server.
That is convenient but it is not the real engine, and two differences matter:

  * SQLite's SUM() drops the scale of a DECIMAL; MySQL's keeps it.
  * MySQL's default collation (utf8mb4_0900_ai_ci) compares strings
    case-insensitively. SQLite's does not. The money properties test whether a
    payment mode is called "Cash", so this is not academic.

Point it at any throwaway MySQL. Defaults assume a local server with a
passwordless root; override with environment variables rather than editing
credentials into this file.

    set BPC_TEST_DB_HOST=127.0.0.1
    set BPC_TEST_DB_PORT=3307
    set BPC_TEST_DB_USER=root
    set BPC_TEST_DB_PASSWORD=

Django creates and drops its own test_<NAME> database, so nothing here touches
existing data.
"""
import os

from main.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('BPC_TEST_DB_NAME', 'bpc_test'),
        'USER': os.environ.get('BPC_TEST_DB_USER', 'root'),
        'PASSWORD': os.environ.get('BPC_TEST_DB_PASSWORD', ''),
        'HOST': os.environ.get('BPC_TEST_DB_HOST', '127.0.0.1'),
        'PORT': os.environ.get('BPC_TEST_DB_PORT', '3306'),
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
        },
        'TEST': {
            # Match production's defaults so collation-sensitive behaviour is
            # exercised the way it behaves on the real server.
            'CHARSET': 'utf8mb4',
            'COLLATION': 'utf8mb4_0900_ai_ci',
        },
    }
}

DEBUG = False

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
