from django import template
from django.utils.safestring import mark_safe
from html_sanitizer import Sanitizer

from django_activitypub.models import Note

register = template.Library()


@register.filter
def sanitize_content(content):
    sani = Sanitizer()
    return mark_safe(sani.sanitize(content))


@register.filter
def max_depth(value, num):
    try:
        return min(int(num), int(value))
    except (ValueError, TypeError):
        return value


@register.inclusion_tag('pub/static.html')
def pub_static():
    return {}


@register.inclusion_tag('pub/activity.html')
def pub_interactions(content_url):
    try:
        note = Note.objects.get(content_url=content_url)
    except Note.DoesNotExist:
        return {}
    replies = note.descendants().select_related('remote_actor')
    return {
        'note': note,
        'replies': replies,
    }
