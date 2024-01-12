import json
import re
import uuid
import urllib.parse

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse, resolve
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
from django_activitypub.models import ActorChoices, LocalActor, RemoteActor, Follower, Note
from django_activitypub.signed_requests import signed_post, SignatureChecker
from django_activitypub.webfinger import fetch_remote_profile, WebfingerException


def webfinger(request):
    resource = request.GET.get('resource')
    acct_m = re.match(r'^acct:(?P<username>.+?)@(?P<domain>.+)$', resource)
    if acct_m:
        username = acct_m.group('username')
        domain = acct_m.group('domain')
    elif resource.startswith('http'):
        parsed = urllib.parse.urlparse(resource)
        if parsed.scheme != request.scheme or parsed.netloc != request.get_host():
            return JsonResponse({'error': 'invalid resource'}, status=404)
        url = resolve(parsed.path)
        if url.url_name != 'activitypub-profile':
            return JsonResponse({'error': 'unknown resource'}, status=404)
        username = url.kwargs.get('username')
        domain = request.get_host()
    else:
        return JsonResponse({'error': 'unsupported resource'}, status=404)

    try:
        actor = LocalActor.objects.get(preferred_username=username, domain=domain)
    except LocalActor.DoesNotExist:
        return JsonResponse({'error': 'no actor by that name'}, status=404)

    data = {
        'subject': f'acct:{actor.preferred_username}@{actor.domain}',
        'links': [
            {
                'rel': 'self',
                'type': 'application/activity+json',
                'href': request.build_absolute_uri(reverse('activitypub-profile', kwargs={'username': actor.preferred_username})),
            }
        ]
    }

    if actor.icon:
        data['links'].append({
            'rel': 'http://webfinger.net/rel/avatar',
            'type': 'image/jpeg',  # todo make this dynamic
            'href': request.build_absolute_uri(actor.icon.url),
        })

    return JsonResponse(data, content_type="application/jrd+json")


def profile(request, username):
    try:
        actor = LocalActor.objects.get(preferred_username=username)
    except LocalActor.DoesNotExist:
        return JsonResponse({}, status=404)

    data = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
            'https://w3id.org/security/v1',
        ],
        'type': ActorChoices(actor.actor_type).label,
        'discoverable': True,
        'preferredUsername': actor.preferred_username,
        'name': actor.name,
        'summary': actor.summary,
        'id': request.build_absolute_uri(reverse('activitypub-profile', kwargs={'username': actor.preferred_username})),
        'followers': request.build_absolute_uri(reverse('activitypub-followers', kwargs={'username': actor.preferred_username})),
        'inbox': request.build_absolute_uri(reverse('activitypub-inbox', kwargs={'username': actor.preferred_username})),
        'outbox': request.build_absolute_uri(reverse('activitypub-outbox', kwargs={'username': actor.preferred_username})),
        'publicKey': {
            'id': request.build_absolute_uri(
                reverse('activitypub-profile', kwargs={'username': actor.preferred_username})) + '#main-key',
            'owner': request.build_absolute_uri(reverse('activitypub-profile', kwargs={'username': actor.preferred_username})),
            'publicKeyPem': actor.public_key,
        }
    }
    if actor.icon:
        data['icon'] = {
            'type': 'Image',
            'mediaType': 'image/jpeg',  # todo make this dynamic
            'url': request.build_absolute_uri(actor.icon.url),
        }
    if actor.image:
        data['image'] = {
            'type': 'Image',
            'mediaType': 'image/jpeg',  # todo make this dynamic
            'url': request.build_absolute_uri(actor.image.url),
        }

    return JsonResponse(data, content_type="application/activity+json")


def followers(request, username):
    try:
        actor = LocalActor.objects.get(preferred_username=username)
    except LocalActor.DoesNotExist:
        return JsonResponse({}, status=404)

    query = Follower.objects.order_by('-follow_date').select_related('remote_actor').filter(following=actor)
    paginator = Paginator(query, 10)
    page_num_arg = request.GET.get('page', None)
    followers_url = request.build_absolute_uri(reverse('activitypub-followers', kwargs={'username': actor.preferred_username}))
    data = {
        '@context': 'https://www.w3.org/ns/activitystreams',
        'type': 'OrderedCollection',
        'totalItems': paginator.count,
        'id': followers_url,
    }

    if page_num_arg is None:
        data['first'] = followers_url + '?page=1'
        return JsonResponse(data, content_type="application/activity+json")

    page_num = int(page_num_arg)

    if 1 <= page_num <= paginator.num_pages:
        page = paginator.page(page_num)
        if page.has_next():
            data['next'] = followers_url + f'?page={page.next_page_number()}'
        data['id'] = followers_url + f'?page={page_num}'
        data['type'] = 'OrderedCollectionPage'
        data['orderedItems'] = [follower.remote_actor.url for follower in page.object_list]
        data['partOf'] = followers_url
        return JsonResponse(data, content_type="application/activity+json")
    else:
        return JsonResponse({'error': f'invalid page number {page_num}'}, status=404)


@csrf_exempt
def inbox(request, username):
    response = {}

    if request.method == 'POST':
        activity = json.loads(request.body)

        if validate_resp := validate_post_request(request, activity):
            return validate_resp

        try:
            actor = LocalActor.objects.get(preferred_username=username)
        except LocalActor.DoesNotExist:
            return JsonResponse({}, status=404)

        if activity['type'] == 'Follow':
            # validate the 'object' is the actor
            local_actor = LocalActor.objects.get_by_url(activity['object'])
            if local_actor.id != actor.id:
                return JsonResponse({'error': f'follow object does not match actor: {activity["object"]}'}, status=400)

            # find or create a remote actor
            remote_actor = RemoteActor.objects.get_or_create_with_url(url=activity['actor'])

            Follower.objects.get_or_create(
                remote_actor=remote_actor,
                following=actor,
            )

            # send an Accept activity
            accept_data = {
                '@context': [
                    'https://www.w3.org/ns/activitystreams',
                    'https://w3id.org/security/v1',
                ],
                'id': request.build_absolute_uri(f'/{uuid.uuid4()}'),
                'type': 'Accept',
                'actor': request.build_absolute_uri(reverse('activitypub-profile', kwargs={'username': actor.preferred_username})),
                'object': activity,
            }

            sign_resp = signed_post(
                url=remote_actor.profile.get('inbox'),
                private_key=actor.private_key.encode('utf-8'),
                public_key_url=accept_data['actor'] + '#main-key',
                body=json.dumps(accept_data),
            )
            sign_resp.raise_for_status()

            response['ok'] = True

        elif activity['type'] == 'Like':
            note = get_object_or_404(Note, content_url=activity['object'])
            if not note:
                return JsonResponse({'error': f'like object is not a note: {activity["object"]}'}, status=400)

            remote_actor = RemoteActor.objects.get_or_create_with_url(url=activity['actor'])
            note.likes.add(remote_actor)

            response['ok'] = True

        elif activity['type'] == 'Announce':
            note = get_object_or_404(Note, content_url=activity['object'])
            if not note:
                return JsonResponse({'error': f'announce object is not a note: {activity["object"]}'}, status=400)

            remote_actor = RemoteActor.objects.get_or_create_with_url(url=activity['actor'])
            note.announces.add(remote_actor)

            response['ok'] = True

        elif activity['type'] == 'Create':
            base_uri = f'{request.scheme}://{request.get_host()}'
            if activity['object']['id'].startswith(base_uri):
                pass  # there is nothing to do, this is our note
            else:
                Note.objects.upsert_remote(base_uri, activity['object'])
            response['ok'] = True

        elif activity['type'] == 'Undo':
            to_undo = activity['object']
            if to_undo['type'] == 'Follow':
                # validate the 'object' is the actor
                local_actor = LocalActor.objects.get_by_url(to_undo['object'])
                if local_actor.id != actor.id:
                    return JsonResponse({'error': f'undo follow object does not match actor: {to_undo["object"]}'}, status=400)

                remote_actor = get_object_or_404(RemoteActor, url=to_undo['actor'])

                local_actor.followers.remove(remote_actor)

                response['ok'] = True

            elif to_undo['type'] == 'Like':
                note = get_object_or_404(Note, content_url=to_undo['object'])
                if not note:
                    return JsonResponse({'error': f'undo like object is not a note: {to_undo["object"]}'}, status=400)

                remote_actor = get_object_or_404(RemoteActor, url=to_undo['actor'])
                note.likes.remove(remote_actor)

                response['ok'] = True

            elif to_undo['type'] == 'Announce':
                note = get_object_or_404(Note, content_url=to_undo['object'])
                if not note:
                    return JsonResponse({'error': f'undo announce object is not a note: {to_undo["object"]}'}, status=400)

                remote_actor = get_object_or_404(RemoteActor, url=to_undo['actor'])
                note.announces.remove(remote_actor)

                response['ok'] = True

            else:
                return JsonResponse({'error': f'unsupported undo type: {to_undo["type"]}'}, status=400)

        elif activity['type'] == 'Delete':
            response['ok'] = True  # TODO: support deletes for notes and actors

        else:
            return JsonResponse({'error': f'unsupported activity type: {activity["type"]}'}, status=400)

        return JsonResponse(response, content_type="application/activity+json")
    else:
        return JsonResponse({}, status=405)


def outbox(request, username):
    try:
        actor = LocalActor.objects.get(preferred_username=username)
    except LocalActor.DoesNotExist:
        return JsonResponse({}, status=404)

    query = Note.objects.order_by('-published_at').filter(local_actor=actor)

    paginator = Paginator(query, 10)
    page_num_arg = request.GET.get('page', None)
    outbox_url = request.build_absolute_uri(reverse('activitypub-outbox', kwargs={'username': actor.preferred_username}))
    data = {
        '@context': 'https://www.w3.org/ns/activitystreams',
        'type': 'OrderedCollection',
        'totalItems': paginator.count,
        'id': outbox_url,
    }

    if page_num_arg is None:
        data['first'] = outbox_url + '?page=1'
        return JsonResponse(data, content_type="application/activity+json")

    page_num = int(page_num_arg)

    if 1 <= page_num <= paginator.num_pages:
        page = paginator.page(page_num)
        base_uri = f'{request.scheme}://{request.get_host()}'
        if page.has_next():
            data['next'] = outbox_url + f'?page={page.next_page_number()}'
        data['id'] = outbox_url + f'?page={page_num}'
        data['type'] = 'OrderedCollectionPage'
        data['orderedItems'] = [note.as_json(base_uri) for note in page.object_list]
        data['partOf'] = outbox_url
        return JsonResponse(data, content_type="application/activity+json")
    else:
        return JsonResponse({'error': f'invalid page number: {page_num}'}, status=404)


def validate_post_request(request, activity):
    if request.method != 'POST':
        raise Exception('Invalid method')

    if 'actor' not in activity:
        return JsonResponse({'error': f'no actor in activity: {activity}'}, status=400)

    try:
        actor_data = fetch_remote_profile(activity['actor'])
    except WebfingerException as e:
        if e.error.response.status_code == 410 and activity['type'] == 'Delete':
            # special case for deletes, the resulting actor will be gone from the server
            return JsonResponse({}, status=410)
        return JsonResponse({'error': 'validate - error fetching remote profile'}, status=401)

    checker = SignatureChecker(actor_data.get('publicKey'))
    result = checker.validate(
        method=request.method.lower(),
        url=request.build_absolute_uri(),
        headers=request.headers,
        body=request.body,
    )

    if not result.success:
        return JsonResponse({'error': 'invalid signature'}, status=401)

    return None
