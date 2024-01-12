import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, ed25519, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
import requests


def get_gmt_now() -> str:
    return datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")


def sign_message(private_key, message):
    key = load_pem_private_key(private_key, password=None)

    return base64.standard_b64encode(
        key.sign(
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    ).decode("utf-8")


class HttpSignature:
    def __init__(self):
        self.fields = []

    def build_signature(self, key_id, private_key):
        message = self.build_message()

        signature_string = sign_message(private_key, message)
        headers = " ".join(name for name, _ in self.fields)

        signature_parts = [
            f'keyId="{key_id}"',
            'algorithm="rsa-sha256"',
            f'headers="{headers}"',
            f'signature="{signature_string}"',
        ]

        return ",".join(signature_parts)

    def build_message(self):
        return "\n".join(f"{name}: {value}" for name, value in self.fields)

    def with_field(self, field_name, field_value):
        self.fields.append((field_name, field_value))
        return self


def content_digest_sha256(content):
    if isinstance(content, str):
        content = content.encode("utf-8")

    digest = base64.standard_b64encode(hashlib.sha256(content).digest()).decode("utf-8")
    return "SHA-256=" + digest


def build_signature(host, method, target):
    return (
        HttpSignature()
        .with_field("(request-target)", f"{method} {target}")
        .with_field("host", host)
    )


def signed_post(url, private_key, public_key_url, headers=None, body=None):
    headers = {} if headers is None else headers

    parsed_url = urlparse(url)
    host = parsed_url.netloc
    target = parsed_url.path

    accept = "application/activity+json"
    content_type = "application/activity+json"
    date_header = get_gmt_now()

    digest = content_digest_sha256(body)

    signature_header = (
        build_signature(host, "post", target)
        .with_field("date", date_header)
        .with_field("digest", digest)
        .with_field("content-type", content_type)
        .build_signature(public_key_url, private_key)
    )

    headers["accept"] = accept
    headers["digest"] = digest
    headers["date"] = date_header
    headers["host"] = host
    headers["content-type"] = content_type
    headers["signature"] = signature_header
    headers["user-agent"] = "shimmy's django_activitypub service - unlike mozilla"

    response = requests.post(url, data=body, headers=headers)
    return response


def parse_signature_header(header):
    parts = header.split(",")
    headers = [x.split('="', 1) for x in parts]
    parsed = {x[0]: x[1].replace('"', '') for x in headers}
    return parsed


@dataclass
class ValidateResult:
    success: bool
    identity: str = None
    error: str = None

    @classmethod
    def success(cls, identity):
        return cls(True, identity=identity)

    @classmethod
    def fail(cls, error):
        return cls(False, error=error)


class SignatureChecker:
    def __init__(self, obj: dict):
        """
        Instantiate this with the fetched identity of a remote actor.

        :param obj: The actor 'publicKey' object
        """
        self.controller = obj.get('owner')
        self.key_id = obj.get('id')
        public_key = obj.get('publicKeyPem')

        if isinstance(public_key, dict):
            public_key = public_key.get('@value')

        self.public_key = load_pem_public_key(public_key.encode('utf-8'))

    def validate(self, method, url, headers, body) -> ValidateResult:
        if 'signature' not in headers:
            return ValidateResult.fail('Missing signature header')

        if method.lower() == 'post':
            digest = content_digest_sha256(body)
            req_digest = headers['digest']
            req_digest = req_digest[:4].upper() + req_digest[4:]
            if digest != req_digest:
                return ValidateResult.fail(f'Digest mismatch: {digest} != {req_digest}')
        else:
            digest = ''

        builder = HttpSignature()
        parsed = parse_signature_header(headers['signature'])
        fields = parsed['headers'].split(' ')

        if "(request-target)" not in fields or "date" not in fields:
            return ValidateResult.fail(f'Missing required signature fields in {fields}')

        if digest and 'digest' not in fields:
            return ValidateResult.fail('Missing digest field')

        # TODO: check date is within acceptable range

        for field in fields:
            if field == "(request-target)":
                parsed_url = urlparse(url)
                builder.with_field(field, f"{method.lower()} {parsed_url.path}")
            else:
                builder.with_field(field, headers[field])

        if self.key_id != parsed['keyId']:
            return ValidateResult.fail(f'Key ID mismatch: expected({self.key_id}) != parsed({parsed["keyId"]})')

        message = builder.build_message().encode('utf8')
        signature = base64.standard_b64decode(parsed['signature'])

        # TODO: support EC public keys
        if isinstance(self.public_key, rsa.RSAPublicKey):
            try:
                self.public_key.verify(
                    signature,
                    message,
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
                return ValidateResult.success(self.controller)
            except InvalidSignature as f:
                return ValidateResult.fail(f'Invalid signature: {f}')

        if isinstance(self.public_key, ed25519.Ed25519PublicKey):
            try:
                self.public_key.verify(
                    signature,
                    message,
                )
                return ValidateResult.success(self.controller)
            except InvalidSignature as f:
                return ValidateResult.fail(f'Invalid signature: {f}')

        return ValidateResult.fail(f'Unsupported public key type: {type(self.public_key)}')
