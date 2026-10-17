from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlparse
import base64
import json
import os


@dataclass(frozen=True)
class CloudConfig:
    url: str
    key: str

    def __post_init__(self):
        parsed = urlparse(self.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('SUPABASE_URL must be the HTTPS project URL, without credentials or a path.')
        if self.key.startswith('sb_secret_'):
            raise ValueError('Use the publishable key, never a Supabase secret key.')
        if not self.key.startswith('sb_publishable_'):
            try:
                middle = self.key.split('.')[1]
                payload = json.loads(base64.urlsafe_b64decode(middle + '=' * (-len(middle) % 4)))
                if payload.get('role') != 'anon':
                    raise ValueError
            except Exception:
                raise ValueError('Use a Supabase publishable key or the legacy anon key, never a service-role key.') from None

    @property
    def namespace(self):
        return sha256(self.url.rstrip('/').encode()).hexdigest()[:24]

    @classmethod
    def load(cls):
        from dotenv import load_dotenv
        load_dotenv(override=False)
        return cls(os.environ.get('SUPABASE_URL', '').rstrip('/'), os.environ.get('SUPABASE_PUBLISHABLE_KEY', ''))
