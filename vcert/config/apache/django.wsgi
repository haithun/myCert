import os
import sys

sys.path.append('/home/ubuntu/django-apps/vcert/')

os.environ['DJANGO_SETTINGS_MODULE'] = 'vcert.settings'

import django.core.handlers.wsgi
application = django.core.handlers.wsgi.WSGIHandler()

