import json
import urllib.parse
import uuid

import requests
from django.urls import resolve, reverse
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from tree_queries.models import TreeNode, TreeQuerySet

from django_activitypub.signed_requests import signed_post
from django_activitypub.webfinger import fetch_remote_profile, finger


class ActorChoices(models.TextChoices):
    PERSON = 'P', 'Person'
    SERVICE = 'S', 'Service'


class LocalActorManager(models.Manager):
    def get_by_url(self, url):
        parsed = urllib.parse.urlparse(url)
        match = resolve(parsed.path)
        if match.url_name == 'activitypub-profile':
            return self.get(preferred_username=match.kwargs['username'], domain=parsed.netloc)
        else:
            return None


class LocalActor(models.Model):
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)
    private_key = models.TextField(blank=True, editable=False)
    public_key = models.TextField(blank=True, editable=False)
    actor_type = models.CharField(max_length=1, choices=ActorChoices, default=ActorChoices.PERSON)
    preferred_username = models.SlugField(max_length=255)
    domain = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    icon = models.ImageField(upload_to='actor-media', null=True, blank=True)
    image = models.ImageField(upload_to='actor-media', null=True, blank=True)
    followers = models.ManyToManyField(
        'RemoteActor', through='Follower', related_name='followers',
        through_fields=('following', 'remote_actor'),
    )

    objects = LocalActorManager()

    class Meta:
        indexes = [
            models.Index(fields=['preferred_username', 'domain'], name='activitypub_local_actor_idx')
        ]

    @property
    def handle(self):
        return f'{self.user.username}@{self.domain}'

    @property
    def account_url(self):
        return f'https://{self.domain}{self.get_absolute_url()}'

    @property
    def icon_url(self):
        return self.icon.url if self.icon else None

    def __str__(self):
        return self.preferred_username

    def get_absolute_url(self):
        return reverse('activitypub-profile', kwargs={'username': self.preferred_username})

    def save(self, *args, **kwargs):
        if not self.id:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self.private_key = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode('utf-8')
            self.public_key = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode('utf-8')
        super().save(*args, **kwargs)

    def private_key_obj(self):
        return serialization.load_pem_private_key(
            self.private_key.encode('utf-8'),
            password=None,
        )

    def public_key_obj(self):
        return serialization.load_pem_public_key(
            self.public_key.encode('utf-8')
        )


class RemoteActorManager(models.Manager):
    def get_or_create_with_url(self, url):
        try:
            return self.get(url=url)  # TODO: check cache expiry
        except RemoteActor.DoesNotExist:
            data = fetch_remote_profile(url)
            parsed = urllib.parse.urlparse(url)
            return self.create(
                username=data.get('preferredUsername'),
                domain=parsed.netloc,
                url=url,
                profile=data,
            )

    def get_or_create_with_username_domain(self, username, domain):
        try:
            return self.get(username=username, domain=domain)
        except RemoteActor.DoesNotExist:
            data = finger(username, domain)
            if 'profile' not in data:
                return None
            url = data['profile'].get('id')
            try:
                return self.get(url=url)
            except RemoteActor.DoesNotExist:
                return self.create(
                    username=username,
                    domain=domain,
                    url=url,
                    profile=data['profile'],
                )


class RemoteActor(models.Model):
    username = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)
    url = models.URLField(db_index=True, unique=True)
    profile = models.JSONField(blank=True, default=dict)
    following = models.ManyToManyField(
        LocalActor, through='Follower', related_name='following',
        through_fields=('remote_actor', 'following'),
    )

    objects = RemoteActorManager()

    class Meta:
        indexes = [
            models.Index(fields=['username', 'domain'], name='activitypub_remote_actor_idx')
        ]

    def __str__(self):
        return f'{self.username}@{self.domain}'

    @property
    def handle(self):
        return f'{self.username}@{self.domain}'

    @property
    def account_url(self):
        return self.profile.get('url', '#')

    @property
    def icon_url(self):
        return self.profile.get('icon', {}).get('url', None)


class Follower(models.Model):
    remote_actor = models.ForeignKey(RemoteActor, on_delete=models.CASCADE)
    following = models.ForeignKey(LocalActor, on_delete=models.CASCADE)
    follow_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['remote_actor', 'following'], name='activitypub_unique_followers')
        ]
        indexes = [
            models.Index(fields=['following', 'follow_date'], name='activitypub_followers_date_idx')
        ]

    def __str__(self):
        return f'{self.remote_actor} -> {self.following}'


class NoteManager(TreeQuerySet):
    def upsert(self, base_uri, local_actor, content, content_url):
        try:
            note = self.get(content_url=content_url)
            note.updated_at = timezone.now()
            note.content = content
            note.save()
            send_update_note_to_followers(base_uri, note)
        except Note.DoesNotExist:
            note = super().create(local_actor=local_actor, content=content, content_url=content_url)
            send_create_note_to_followers(base_uri, note)
        return note

    def delete_local(self, base_uri, content_url):
        try:
            note = self.get(content_url=content_url)
            send_delete_note_to_followers(base_uri, note)
        except Note.DoesNotExist:
            pass

    def upsert_remote(self, base_uri, obj):
        full_obj = get_object(obj['id'])
        try:
            note = self.get(content_url=full_obj['id'])
        except Note.DoesNotExist:
            note = Note()
        note.remote_actor = RemoteActor.objects.get_or_create_with_url(full_obj['attributedTo'])
        note.published_at = parse_datetime(full_obj['published'])
        if updated_str := full_obj.get('updated', None):
            note.updated_at = parse_datetime(updated_str)
        note.content = full_obj['content']
        note.content_url = obj['id']
        if reply_url := full_obj.get('inReplyTo', None):
            if reply_url.startswith(base_uri):
                note.parent = self.get(content_url=reply_url)
            else:
                note.parent = Note.objects.upsert_remote(base_uri, get_object(reply_url))
        note.save()
        return note


class Note(TreeNode):
    local_actor = models.ForeignKey(LocalActor, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    remote_actor = models.ForeignKey(RemoteActor, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    content = models.TextField()
    content_url = models.URLField(db_index=True)
    likes = models.ManyToManyField(RemoteActor, blank=True, related_name='likes')
    announces = models.ManyToManyField(RemoteActor, blank=True, related_name='announces')

    objects = NoteManager.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=['local_actor', 'published_at'], name='activitypub_notes_by_date_idx')
        ]

    def __str__(self):
        return self.content_url

    def get_absolute_url(self):
        return self.content_url

    def as_json(self, base_uri):
        if self.local_actor:
            attributed = f'{base_uri}{self.local_actor.get_absolute_url()}'
        else:
            attributed = self.remote_actor.url
        data = {
            'type': 'Note',
            'id': self.content_url,
            'published': format_datetime(self.published_at),
            'attributedTo': attributed,
            'content': self.content,
            'tags': list(parse_mentions(self.content)),
            'to': 'https://www.w3.org/ns/activitystreams#Public'
        }
        if self.parent:
            data['inReplyTo'] = self.parent.content_url
        return data

    @property
    def actor(self):
        return self.local_actor or self.remote_actor

    @property
    def max_depth(self):
        return min(getattr(self, 'tree_depth', 1), 5)


def parse_mentions(content):
    """
    Parse a note's content for mentions and return a generator of mention objects
    """
    from django_activitypub.custom_markdown import mention_pattern

    mentioned = {}
    for m in mention_pattern.finditer(content):
        key = (m.group('username'), m.group('domain'))
        if key in mentioned:
            continue
        actor = RemoteActor.objects.get_or_create_with_username_domain(*key)
        yield {
            'type': 'Mention',
            'href': actor.url,
            'name': f'{key[0]}@{key[1]}',
        }


def format_datetime(time):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_datetime(time):
    return timezone.datetime.strptime(time, '%Y-%m-%dT%H:%M:%SZ')


def send_create_note_to_followers(base_url, note):
    actor_url = f'{base_url}{note.local_actor.get_absolute_url()}'
    create_msg = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
            'https://w3id.org/security/v1'
        ],
        'type': 'Create',
        'id': f'{base_url}/{uuid.uuid4()}',
        'actor': actor_url,
        'object': note.as_json(base_url)
    }

    for follower in note.local_actor.followers.all():
        resp = signed_post(
            follower.profile.get('inbox'),
            note.local_actor.private_key.encode('utf-8'),
            f'{actor_url}#main-key',
            body=json.dumps(create_msg)
        )
        resp.raise_for_status()


def send_update_note_to_followers(base_url, note):
    actor_url = f'{base_url}{note.local_actor.get_absolute_url()}'
    update_msg = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
        ],
        'type': 'Update',
        'id': f'{note.content_url}#updates/{note.updated_at.timestamp()}',
        'actor': actor_url,
        'object': note.as_json(base_url),
        'published': format_datetime(note.published_at),
    }

    for follower in note.local_actor.followers.all():
        resp = signed_post(
            follower.profile.get('inbox'),
            note.local_actor.private_key.encode('utf-8'),
            f'{actor_url}#main-key',
            body=json.dumps(update_msg)
        )
        resp.raise_for_status()


def send_delete_note_to_followers(base_url, note):
    actor_url = f'{base_url}{note.local_actor.get_absolute_url()}'
    delete_msg = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
        ],
        'type': 'Delete',
        'actor': actor_url,
        'object': {
            'id': note.content_url,
            'type': 'Tombstone',
        },
    }

    for follower in note.local_actor.followers.all():
        resp = signed_post(
            follower.profile.get('inbox'),
            note.local_actor.private_key.encode('utf-8'),
            f'{actor_url}#main-key',
            body=json.dumps(delete_msg)
        )
        resp.raise_for_status()


def get_object(url):
    resp = requests.get(url, headers={'Accept': 'application/activity+json'})
    resp.raise_for_status()
    return resp.json()
