import asyncio
import base64
import json
import threading
import unittest
import urllib.error
from unittest.mock import patch

from wx_clawbot import __version__
from wx_clawbot.channels.http import HttpStatusError, NoRedirect, ProtocolError, WeixinHttp, api_base, encoded_version


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.body[:limit]


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = WeixinHttp()
        self.addAsyncCleanup(self.client.close)

    def test_api_origins_refuse_credentials_suffix_attacks_and_non_tls(self):
        self.assertEqual(api_base("https://ilinkai.weixin.qq.com"), "https://ilinkai.weixin.qq.com/")
        for value in ("http://ilinkai.weixin.qq.com", "https://ilinkai.weixin.qq.com.attacker.test",
                      "https://attacker.test@ilinkai.weixin.qq.com", "https://127.0.0.1",
                      "https://ilinkai.weixin.qq.com:invalid", "https://ilinkai.weixin.qq.com/other", None):
            with self.assertRaises(ProtocolError):
                api_base(value)

    def test_reference_version_encoding_and_invalid_components(self):
        self.assertEqual(encoded_version("1.0.11"), "65547")
        self.assertEqual(encoded_version("0.1.0.dev0"), "256")
        for value in ("1.0", "256.0.0", "1.-1.0", "not-a-version"):
            with self.assertRaises(ValueError):
                encoded_version(value)

    @patch("wx_clawbot.channels.http.urllib.request.build_opener")
    async def test_login_get_has_only_common_headers_and_does_not_send_a_token(self, factory):
        factory.return_value.open.return_value = Response(b'{"status":"wait"}')
        result = await self.client.request("auth", "GET", "https://ilinkai.weixin.qq.com",
                                           "ilink/bot/get_qrcode_status?qrcode=test")
        self.assertEqual(result, {"status": "wait"})
        request = factory.return_value.open.call_args.args[0]
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.assertEqual(headers["ilink-app-id"], "bot")
        self.assertEqual(headers["ilink-app-clientversion"], encoded_version(__version__))
        self.assertNotIn("authorization", headers)
        self.assertNotIn("authorizationtype", headers)
        self.assertNotIn("x-wechat-uin", headers)
        with self.assertRaises(ProtocolError):
            await self.client.request("auth", "GET", "https://ilinkai.weixin.qq.com",
                                      "ilink/bot/get_qrcode_status", token="fixture-token")

    @patch("wx_clawbot.channels.http.urllib.request.build_opener")
    async def test_post_headers_unicode_body_and_lossless_uint64(self, factory):
        factory.return_value.open.return_value = Response(b'{"ret":0,"message_id":18446744073709551615}')
        body = {"msg": {"text": "测试"}}
        result = await self.client.request("send", "POST", "https://ilinkai.weixin.qq.com",
                                           "ilink/bot/sendmessage", body=body, token="fixture-token")
        request = factory.return_value.open.call_args.args[0]
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.assertEqual(headers["authorization"], "Bearer fixture-token")
        self.assertEqual(headers["authorizationtype"], "ilink_bot_token")
        self.assertTrue(0 <= int(base64.b64decode(headers["x-wechat-uin"])) <= 2**32 - 1)
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual(result["message_id"], 2**64 - 1)

    @patch("wx_clawbot.channels.http.urllib.request.build_opener")
    async def test_malformed_oversized_duplicate_or_non_object_json_fails(self, factory):
        for body in (b'[]', b'{"ret":0,"ret":1}', b'{"ret":NaN}', b'\xff',
                     b'x' * (self.client.MAX_RESPONSE + 1)):
            factory.return_value.open.return_value = Response(body)
            with self.assertRaises(ProtocolError):
                await self.client.request("auth", "POST", "https://ilinkai.weixin.qq.com",
                                          "ilink/bot/get_bot_qrcode", body={})

    @patch("wx_clawbot.channels.http.urllib.request.build_opener")
    async def test_http_error_and_redirect_never_expose_secret_body_or_follow_location(self, factory):
        factory.return_value.open.side_effect = urllib.error.HTTPError(
            "https://example.test/?secret=hidden", 500, "private response", {}, None)
        with self.assertRaises(HttpStatusError) as error:
            await self.client.request("auth", "POST", "https://ilinkai.weixin.qq.com",
                                      "ilink/bot/get_bot_qrcode", body={})
        self.assertEqual(str(error.exception), "Weixin HTTP status 500")
        with self.assertRaises(ProtocolError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.test")

    async def test_cancelled_poll_keeps_lane_occupied_while_send_remains_independent(self):
        entered, release = threading.Event(), threading.Event()
        def blocking(method, url, body, token, timeout):
            if "getupdates" in url:
                entered.set()
                release.wait(3)
            return {"ret": 0}
        with patch.object(self.client, "_blocking", side_effect=blocking):
            poll = asyncio.create_task(self.client.request("poll", "POST", "https://ilinkai.weixin.qq.com",
                                                           "ilink/bot/getupdates", body={}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                poll.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await poll
                self.assertTrue(self.client.slots["poll"].locked())
                result = await asyncio.wait_for(self.client.request("send", "POST", "https://ilinkai.weixin.qq.com",
                                                                    "ilink/bot/sendmessage", body={}), 1)
                self.assertEqual(result["ret"], 0)
            finally:
                release.set()
