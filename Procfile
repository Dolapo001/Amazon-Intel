release: python manage.py migrate --noinput
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --log-file -
worker: celery -A config.celery worker -Q celery,default,high_priority -c 2 -l info
beat: celery -A config.celery beat -l info -s /tmp/celerybeat-schedule
