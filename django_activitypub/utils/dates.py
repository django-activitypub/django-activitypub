from django.utils import timezone


def format_datetime(time):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_datetime(time):
    try:
        return timezone.datetime.strptime(time, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return timezone.datetime.strptime(time, '%Y-%m-%dT%H:%M:%S.%fZ')
