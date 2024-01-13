import json
import unittest
import responses
from django_activitypub.webfinger import finger, fetch_remote_profile, WebfingerException


class TestWebfinger(unittest.TestCase):
    finger_resp = '''
    {
        "links": [{
            "rel":"self",
            "type":"application/activity+json",
            "href":"https://example.com/profile"
        }]
    }
    '''

    profile_resp = '''
    {
        "@context": [
            "https://www.w3.org/ns/activitystreams"
        ],
        "id": "https://example.com/profile",
        "type": "Person",
        "preferredUsername": "foo",
        "name": "Foo Bar"
    }
    '''

    def test_finger_bad_json_raises_webfinger_exception(self):
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://example.com/.well-known/webfinger',
                     body='{not json}', status=200)
            with self.assertRaises(WebfingerException):
                finger('foo', 'example.com')

    def test_finger_404_raises_webfinger_exception(self):
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://example.com/.well-known/webfinger',
                     body='{}', status=404)
            with self.assertRaises(WebfingerException):
                finger('foo', 'example.com')

    def test_finger_no_profile(self):
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://example.com/.well-known/webfinger',
                     body='{"links": []}', status=200)
            data = finger('foo', 'example.com')
            self.assertEqual(data['webfinger'], {'links': []})
            self.assertEqual(data['profile'], None)

    def test_finger_with_404_profile_link(self):
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://example.com/.well-known/webfinger',
                     body=self.finger_resp, status=200)
            rsps.add(responses.GET, 'https://example.com/profile', body='{}', status=404)
            with self.assertRaises(WebfingerException):
                finger('foo', 'example.com')

    def test_fetch_remote_profile_bad_json_raises_webfinger_exception(self):
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://example.com/profile', body='{not json}', status=200)
            with self.assertRaises(WebfingerException):
                fetch_remote_profile('https://example.com/profile')

    def test_fetch_remote_profile_404_raises_webfinger_exception(self):
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://example.com/profile', body='{}', status=404)
            with self.assertRaises(WebfingerException):
                fetch_remote_profile('https://example.com/profile')

    def test_successful_finger(self):
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://example.com/.well-known/webfinger',
                     body=self.finger_resp, status=200)
            rsps.add(responses.GET, 'https://example.com/profile',
                     body=self.profile_resp, status=200)
            data = finger('foo', 'example.com')
            expected = {
                'profile': json.loads(self.profile_resp),
                'webfinger': json.loads(self.finger_resp),
            }
            self.assertEqual(data, expected)
