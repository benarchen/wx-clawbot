import base64
import io
import json
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PIL import Image
from wx_clawbot.channels import media


class ImageMediaTests(unittest.TestCase):
    def setUp(self):
        out = io.BytesIO()
        Image.new('RGB', (8, 6), 'red').save(out, format='PNG')
        self.png = out.getvalue()
        self.image = {'media': {'encrypt_query_param': 'synthetic-query'}}

    def test_key_sources_priority_and_both_base64_encodings(self):
        key = b'\x12' * 16
        self.assertEqual(media.image_key({'aeskey': key.hex(), 'media': {'aes_key': 'bad'}}), key)
        for raw in (key, key.hex().encode()):
            self.assertEqual(media.image_key({'media': {'aes_key': base64.b64encode(raw).decode()}}), key)
        self.assertIsNone(media.image_key({'media': {}}))

    def test_bad_keys_and_ciphertext_never_become_plaintext(self):
        for image in ({'aeskey': 'bad', 'media': {}}, {'media': {'aes_key': 'secret-invalid!'}}):
            with self.assertRaises(media.ImageError) as error:
                media.image_key(image)
            self.assertNotIn('secret-invalid', str(error.exception))
        for raw in (b'bad-length', b'\0' * 16):
            with self.assertRaises(media.ImageError):
                media.decrypt_image(raw, b'\x12' * 16)

    def test_aes_known_vector_and_padding(self):
        key = bytes.fromhex('000102030405060708090a0b0c0d0e0f')
        plain = bytes.fromhex('00112233445566778899aabbccddeeff')
        cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        encrypted = cipher.update(plain + b'\x10' * 16) + cipher.finalize()
        self.assertEqual(encrypted[:16].hex(), '69c4e0d86a7b0430d8cdb78070b4c55a')
        self.assertEqual(media.decrypt_image(encrypted, key), plain)

    def test_cdn_url_priority_encoding_and_host_boundaries(self):
        self.assertTrue(media.media_url({'media': {'encrypt_query_param': 'a+b/&'}}).endswith('a%2Bb%2F%26'))
        full = 'https://novac2c.cdn.weixin.qq.com/c2c/download?test=1'
        self.assertEqual(media.media_url({'media': {'full_url': full, 'encrypt_query_param': 'ignored'}}), full)
        for url in ('http://novac2c.cdn.weixin.qq.com/x', 'https://127.0.0.1/x',
                    'https://novac2c.cdn.weixin.qq.com.evil.test/x',
                    'https://user@novac2c.cdn.weixin.qq.com/x', 'https://novac2c.cdn.weixin.qq.com:444/x'):
            with self.subTest(url=url), self.assertRaises(media.ImageError):
                media.media_url({'media': {'full_url': url}})

    def test_complete_decode_format_frames_and_limits(self):
        self.assertEqual(media.validate_image(self.png)['format'], 'PNG')
        out = io.BytesIO()
        Image.new('RGB', (8, 6)).save(out, format='JPEG')
        self.assertEqual(media.validate_image(out.getvalue())['format'], 'JPEG')
        for raw in (self.png[:40], b'<html>secret-error-body</html>', b'GIF89a' + b'\0' * 40):
            with self.assertRaises(media.ImageError):
                media.validate_image(raw)
        with patch.object(media, 'MAX_PIXELS', 48):
            media.validate_image(self.png)
        with patch.object(media, 'MAX_PIXELS', 47), self.assertRaises(media.ImageError):
            media.validate_image(self.png)
        with patch.object(media, 'MAX_BYTES', len(self.png)):
            media.validate_image(self.png)
        with patch.object(media, 'MAX_BYTES', len(self.png) - 1), self.assertRaises(media.ImageError):
            media.validate_image(self.png)
        out = io.BytesIO()
        Image.new('RGB', (8, 6), 'red').save(out, format='PNG', save_all=True,
            append_images=[Image.new('RGB', (8, 6), 'blue')], duration=100)
        with self.assertRaises(media.ImageError):
            media.validate_image(out.getvalue())

    def test_direct_connection_uses_checked_address_without_second_resolution(self):
        address = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        with patch.object(media.socket, 'getaddrinfo', return_value=[address]) as dns, \
             patch.object(media.socket, 'socket') as factory:
            connection = media.public_connection((media.CDN_HOST, 443), 10)
        dns.assert_called_once()
        factory.return_value.connect.assert_called_once_with(address[4])
        self.assertIs(connection, factory.return_value)

    def test_direct_private_fake_dns_and_mixed_addresses_are_refused_before_connect(self):
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        for private in ('127.0.0.1', '10.0.0.1', '198.18.0.1'):
            with patch.object(media.socket, 'getaddrinfo', return_value=[public, (2, 1, 6, '', (private, 443))]), \
                 patch.object(media.socket, 'socket') as create, self.assertRaises(media.ImageError):
                media.public_connection((media.CDN_HOST, 443), 10)
            create.assert_not_called()

    def test_existing_connect_proxy_preserves_hostname_tls_and_does_not_use_fake_dns(self):
        with patch.object(media.urllib.request, 'getproxies', return_value={'https': 'http://localhost:7890'}), \
             patch.object(media.urllib.request, 'proxy_bypass', return_value=False), \
             patch.object(media.socket, 'getaddrinfo', side_effect=AssertionError('origin DNS must be resolved by proxy')):
            opener = media.download_opener()
        https = next(h for h in opener.handlers if type(h) is media.urllib.request.HTTPSHandler)
        self.assertTrue(https._context.check_hostname)
        self.assertEqual(https._context.verify_mode, media.ssl.CERT_REQUIRED)

    def test_proxy_bypass_uses_checked_direct_handler(self):
        with patch.object(media.urllib.request, 'getproxies', return_value={'https': 'http://localhost:7890'}), \
             patch.object(media.urllib.request, 'proxy_bypass', return_value=True):
            opener = media.download_opener()
        self.assertTrue(any(isinstance(h, media.PublicHTTPSHandler) for h in opener.handlers))
        self.assertFalse(any(type(h) is media.urllib.request.ProxyHandler and h.proxies for h in opener.handlers))

    def response(self, chunks):
        response = MagicMock()
        response.read1.side_effect = chunks
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        return response, opener

    def test_download_has_no_bot_auth_headers_and_decodes_real_bytes(self):
        response, opener = self.response([self.png, b''])
        with patch.object(media, 'download_opener', return_value=opener):
            plain, info = media._download_image(self.image)
        self.assertEqual(plain, self.png)
        self.assertEqual(info['byte_size'], len(self.png))
        request = opener.open.call_args.args[0]
        self.assertFalse(any('auth' in key.lower() for key, _ in request.header_items()))
        response.read.assert_not_called()

    def test_stream_limit_and_elapsed_deadline_do_not_trust_content_length(self):
        _, opener = self.response([b'x' * 20, b''])
        with patch.object(media, 'download_opener', return_value=opener), patch.object(media, 'MAX_BYTES', 10), self.assertRaises(media.ImageError):
            media._download_image(self.image)
        _, opener = self.response([self.png, b''])
        with patch.object(media, 'download_opener', return_value=opener), \
             patch.object(media.time, 'monotonic', side_effect=[0, 31]), self.assertRaises(media.ImageError) as error:
            media._download_image(self.image)
        self.assertEqual(error.exception.code, 'download_timeout')

    def test_redirect_is_refused_and_response_closed(self):
        stream = MagicMock()
        with self.assertRaises(media.ImageError):
            media.NoMediaRedirect().redirect_request(None, stream, 302, 'ignored', {}, 'https://evil.test/')
        stream.close.assert_called_once()

    def test_blocking_dns_worker_is_killed_and_reaped_within_total_deadline(self):
        original = subprocess.Popen
        children = []
        def blocked_worker(*args, **kwargs):
            # A blocked resolver has no Python cancellation point. Use a real
            # sleeping child to verify the parent can forcibly end and reap it.
            child = original([sys.executable, '-I', '-c', 'import time; time.sleep(60)'], **kwargs)
            children.append(child)
            return child
        started = time.monotonic()
        with patch.object(media.subprocess, 'Popen', side_effect=blocked_worker), \
             patch.object(media, 'DOWNLOAD_SECONDS', .2), self.assertRaises(media.ImageError) as error:
            media.download_image(self.image)
        self.assertEqual(error.exception.code, 'download_timeout')
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdin.closed)
        self.assertTrue(children[0].stdout.closed)

    def test_worker_protocol_keeps_secrets_on_stdin_and_preserves_failure_category(self):
        info = media.validate_image(self.png)
        child = MagicMock(returncode=0)
        child.communicate.return_value = (json.dumps(info).encode() + b'\n' + self.png, None)
        with patch.object(media.subprocess, 'Popen', return_value=child) as create:
            plain, actual = media.download_image(self.image)
        self.assertEqual((plain, actual), (self.png, info))
        self.assertNotIn('synthetic-query', str(create.call_args))
        self.assertIn(b'synthetic-query', child.communicate.call_args.args[0])
        child.returncode = 1
        child.communicate.return_value = (b'{"error":"invalid_key"}\n', None)
        with patch.object(media.subprocess, 'Popen', return_value=child), self.assertRaises(media.ImageError) as error:
            media.download_image(self.image)
        self.assertEqual(error.exception.code, 'invalid_key')

    def test_worker_invalid_or_corrupted_output_cannot_become_an_attachment(self):
        info = media.validate_image(self.png)
        for output in (b'not-json\nsecret', json.dumps(info).encode() + b'\nchanged', b'{}\n'):
            child = MagicMock(returncode=0)
            child.communicate.return_value = (output, None)
            with patch.object(media.subprocess, 'Popen', return_value=child), self.assertRaises(media.ImageError):
                media.download_image(self.image)
