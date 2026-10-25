import time
import unittest
from unittest.mock import AsyncMock

from wx_clawbot.channels.http import ChannelError, ProtocolError, TransportError
from wx_clawbot.channels.wechat import BusinessError, Credentials, DeliveryUnknown, Login, SessionExpired, WechatApi


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http = AsyncMock()
        self.api = WechatApi(self.http)
        self.account = Credentials("fixture-bot", "fixture-owner", "https://ilinkai.weixin.qq.com/", "fixture-token")

    async def test_login_uses_no_other_clients_tokens_and_omits_authenticated_base_info(self):
        self.http.request.return_value = {"qrcode": "fixture-code", "qrcode_img_content": "fixture-display"}
        login = await self.api.start_login()
        self.assertEqual(login.qrcode, "fixture-code")
        self.assertNotIn("fixture-code", repr(login))
        call = self.http.request.await_args
        self.assertEqual(call.kwargs["body"], {"local_token_list": []})
        self.assertNotIn("token", call.kwargs)
        self.assertIn("bot_type=3", call.args[3])

    async def test_login_expiry_and_unsafe_redirect_are_not_success(self):
        old = Login("code", "display", time.time() - 301)
        self.assertEqual(await self.api.login_status(old), ("expired", None))
        self.http.request.assert_not_awaited()
        self.http.request.return_value = {"status": "scaned_but_redirect", "redirect_host": "attacker.test"}
        with self.assertRaises(ProtocolError):
            await self.api.login_status(Login("code", "display", time.time()))

    async def test_existing_binding_without_owned_credentials_is_not_claimed(self):
        self.http.request.return_value = {"status": "binded_redirect"}
        with self.assertRaises(ChannelError):
            await self.api.login_status(Login("code", "display", time.time()))

    async def test_confirmed_login_requires_all_identity_fields_and_safe_token(self):
        response = {"status": "confirmed", "bot_token": "fixture-token", "ilink_bot_id": "fixture-bot",
                    "ilink_user_id": "fixture-owner", "baseurl": "https://ilinkai.weixin.qq.com"}
        self.http.request.return_value = response
        state, account = await self.api.login_status(Login("code", "display", time.time()))
        self.assertEqual(state, "confirmed")
        self.assertEqual(account.owner_id, "fixture-owner")
        self.assertNotIn("fixture-token", repr(account))
        response.pop("ilink_user_id")
        with self.assertRaises(ProtocolError):
            await self.api.login_status(Login("code", "display", time.time()))

    async def test_return_codes_distinguish_expiry_rejection_and_malformed_success(self):
        for response, error in (({"ret": -14}, SessionExpired), ({"ret": 0, "errcode": -2}, BusinessError),
                                ({"ret": True}, ProtocolError), ({"msgs": []}, ProtocolError)):
            self.http.request.return_value = response
            with self.assertRaises(error):
                await self.api.updates(self.account, "previous-cursor")

    async def test_cursor_is_forwarded_exactly_and_deprecated_sync_buf_not_used(self):
        response = {"ret": 0, "msgs": [], "get_updates_buf": "next-cursor", "sync_buf": "deprecated"}
        self.http.request.return_value = response
        self.assertEqual(await self.api.updates(self.account, "previous-cursor"), response)
        body = self.http.request.await_args.kwargs["body"]
        self.assertEqual(body["get_updates_buf"], "previous-cursor")
        self.assertNotIn("sync_buf", body)
        self.assertTrue(body["base_info"]["bot_agent"].startswith("wx-clawbot/"))

    async def test_observed_update_envelope_can_omit_optional_return_code(self):
        response = {"msgs": [], "sync_buf": "unused", "get_updates_buf": "fixture-cursor"}
        self.http.request.return_value = response
        self.assertEqual(await self.api.updates(self.account, ""), response)
        for invalid in ({}, {"msgs": []}, {"msgs": [], "get_updates_buf": ""},
                        {"ret": None, **response}, {"errcode": -14, **response}):
            self.http.request.return_value = invalid
            with self.assertRaises((ProtocolError, SessionExpired)):
                await self.api.updates(self.account, "")

    async def test_send_is_bound_to_owner_context_and_stable_client_identity(self):
        with self.assertRaises(ValueError):
            await self.api.send_text(self.account, peer="someone-else", text="hello",
                                     context_token="context", client_id="delivery-1")
        self.http.request.assert_not_awaited()
        self.http.request.return_value = {"ret": 0, "message_id": "12345678901234567890"}
        await self.api.send_text(self.account, peer="fixture-owner", text="hello",
                                 context_token="fixture-context", client_id="delivery-1")
        message = self.http.request.await_args.kwargs["body"]["msg"]
        self.assertEqual(message["to_user_id"], "fixture-owner")
        self.assertEqual(message["context_token"], "fixture-context")
        self.assertEqual(message["client_id"], "delivery-1")
        self.assertEqual((message["message_type"], message["message_state"]), (2, 2))
        self.assertEqual(message["item_list"], [{"type": 1, "text_item": {"text": "hello"}}])

    async def test_send_transport_loss_or_missing_ack_never_retries_or_reports_success(self):
        self.http.request.side_effect = TransportError("connection lost")
        with self.assertRaises(DeliveryUnknown):
            await self.api.send_text(self.account, peer="fixture-owner", text="hello",
                                     context_token="context", client_id="delivery-1")
        self.assertEqual(self.http.request.await_count, 1)
        self.http.request.side_effect = None
        self.http.request.return_value = {}
        with self.assertRaises(DeliveryUnknown):
            await self.api.send_text(self.account, peer="fixture-owner", text="hello",
                                     context_token="context", client_id="delivery-2")
        self.assertEqual(self.http.request.await_count, 2)

    async def test_malformed_send_business_ack_is_an_unknown_delivery(self):
        for response in ({"ret": True}, {"ret": "0"}, {"ret": 0, "errcode": []}):
            self.http.request.return_value = response
            with self.assertRaises(DeliveryUnknown):
                await self.api.send_text(self.account, peer="fixture-owner", text="hello",
                                         context_token="context", client_id="delivery-malformed")
        self.assertEqual(self.http.request.await_count, 3)

    async def test_observed_native_message_id_ack_can_omit_optional_return_code(self):
        for identity in (1, 2**64 - 1, "18446744073709551615"):
            self.http.request.return_value = {"message_id": identity}
            response = await self.api.send_text(self.account, peer="fixture-owner", text="hello",
                                                 context_token="context", client_id="native-id-ack")
            self.assertEqual(response["message_id"], identity)
        for identity in (None, 0, -1, True, 1.5, "invalid", 2**64):
            self.http.request.return_value = {"message_id": identity}
            with self.assertRaises(DeliveryUnknown):
                await self.api.send_text(self.account, peer="fixture-owner", text="hello",
                                         context_token="context", client_id="invalid-id-ack")
        for response, error in (({"message_id": 1, "ret": -2}, DeliveryUnknown),
                                ({"message_id": 1, "errcode": -14}, DeliveryUnknown),
                                ({"ret": -2}, BusinessError),
                                ({"errcode": -14}, SessionExpired),
                                ({"message_id": 1, "ret": "0"}, DeliveryUnknown)):
            self.http.request.return_value = response
            with self.assertRaises(error):
                await self.api.send_text(self.account, peer="fixture-owner", text="hello",
                                         context_token="context", client_id="error-with-native-id")
