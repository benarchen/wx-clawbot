"""Bounded durable setting intents. No settings authority and no automatic replay."""

import hashlib
import json
import os
from pathlib import Path
import time

from .channels.http import ProtocolError
from .channels.private import private_directory, private_lease, read_json, write_json


class ControlJournal:
    LIMIT = 2048
    BYTES = 16384
    PHASES = {'intent', 'unknown', 'confirmed', 'unchanged', 'rejected'}

    def __init__(self, directory):
        self.directory = Path(directory)

    @staticmethod
    def key(message_id):
        if not isinstance(message_id, str) or not 0 < len(message_id) <= 4096:
            raise ValueError('Stable bounded source message identity required')
        return hashlib.sha256(message_id.encode()).hexdigest()

    def read(self, message_id):
        key = self.key(message_id)
        path = self.directory / (key + '.json')
        if not self.directory.exists() and not self.directory.is_symlink():
            return None
        private_directory(self.directory)
        if not path.exists() and not path.is_symlink():
            return None
        value = read_json(path)
        self._validate(value)
        if value['key'] != key:
            raise ProtocolError('Setting intent identity mismatch')
        return value

    def _validate(self, value):
        if (type(value.get('format')) is not int or value.get('format') != 1 or value.get('phase') not in self.PHASES
                or not isinstance(value.get('key'), str) or len(value['key']) != 64
                or not isinstance(value.get('target'), dict)
                or not isinstance(value.get('fingerprint'), str)
                or len(value['fingerprint']) != 64
                or any(c not in '0123456789abcdef' for c in value['key']+value['fingerprint'])
                or 'reply' in value and (not isinstance(value['reply'],str) or not 0<len(value['reply'])<=4000)
                or value['phase'] not in {'intent','unknown'} and 'reply' not in value
                or len(json.dumps(value, ensure_ascii=False).encode()) > self.BYTES):
            raise ProtocolError('Invalid or oversized setting intent')

    def _sync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def begin(self, message_id, payload):
        private_directory(self.directory)
        with private_lease(self.directory / '.lease'):
            existing = self.read(message_id)
            if existing is not None:
                return existing, False
            count = 0
            for _ in self.directory.glob('*.json'):
                count += 1
                if count >= self.LIMIT:
                    raise ProtocolError('Setting intent capacity reached')
            value = dict(payload, format=1, key=self.key(message_id), phase='intent', created_at=time.time())
            self._validate(value)
            write_json(self.directory / (value['key'] + '.json'), value)
            self._sync_directory()
            return value, True

    def finish(self, message_id, phase, reply, **evidence):
        with private_lease(self.directory / '.lease'):
            value = self.read(message_id)
            if value is None or value['phase'] != 'intent':
                raise ProtocolError('Only an original setting intent can be finalized')
            value.update(phase=phase, reply=reply, updated_at=time.time(), **evidence)
            self._validate(value)
            write_json(self.directory / (value['key'] + '.json'), value, replace=True)
            self._sync_directory()
            return reply
