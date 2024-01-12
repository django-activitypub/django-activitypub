import re
import markdown
from markdown import inlinepatterns
from xml.etree.ElementTree import Element, SubElement
from django_activitypub.models import RemoteActor
from django_activitypub.webfinger import WebfingerException


mention_pattern = re.compile(r'(([\W|^])(@(?P<username>[^@\s]+)@(?P<domain>[\w.]+))(\W))')


class MentionPattern(inlinepatterns.Pattern):
    def handleMatch(self, m):
        try:
            remote_actor = RemoteActor.objects.get_or_create_with_username_domain(
                username=m.group(5), domain=m.group(6),
            )
        except (RemoteActor.DoesNotExist, WebfingerException):
            remote_actor = None
        if remote_actor:
            parent = Element('span')
            pre_text = SubElement(parent, 'span')
            pre_text.text = m.group(3)
            el = SubElement(parent, 'a')
            el.text = m.group(4)
            el.set('class', 'ap-mention')
            el.set('href', remote_actor.url)
            el.set('target', '_blank')
            post_text = SubElement(parent, 'span')
            post_text.text = m.group(7)
            return parent
        else:
            el = Element('span')
            el.text = m.group(2)
            return el


class ActivityPubExtension(markdown.Extension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(MentionPattern(mention_pattern.pattern), 'mention', 176)
