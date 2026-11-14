"""Readonly account quota is scoped and distinct from thread token observations."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from wx_clawbot.agents.rpc import RpcError
from wx_clawbot.commands import CommandError
from wx_clawbot.native_controls import account_quota,rate_limit_lines


def response():
    row={'primary':{'usedPercent':86,'windowDurationMins':300,'resetsAt':1794338851},
         'secondary':{'usedPercent':98,'windowDurationMins':10080,'resetsAt':None}}
    return {'rateLimits':row,'rateLimitsByLimitId':{'codex':row},'accountId':'PRIVATE_ACCOUNT',
            'rateLimitUpsell':{'secret':'PRIVATE_BANNER'},'rateLimitResetCredits':{'credits':'PRIVATE_CREDITS'}}


class QuotaParsingTests(unittest.TestCase):
    def test_remaining_windows_and_reset_are_native_and_account_scoped(self):
        text='\n'.join(rate_limit_lines(response()))
        for value in ('非本会话专属','5 小时：剩余 **14%**','1 周：剩余 **2%**','重置 2026-11-11 03:27','未标注模型时不作推断'):
            self.assertIn(value,text)
        self.assertNotIn('PRIVATE',text)
        self.assertNotIn('上下文',text)

    def test_multiple_buckets_keep_their_native_model_labels_without_guessing(self):
        value=response();row=copy.deepcopy(value['rateLimits']);row.update(limitName='Special *bucket*',normalModelSlug='fixture-model')
        value['rateLimitsByLimitId']['special']=row
        text='\n'.join(rate_limit_lines(value))
        self.assertIn('Special *bucket*',text);self.assertIn('fixture-model',text)
        self.assertEqual(text.count('5 小时：'),2)

    def test_legacy_missing_and_empty_multibucket_have_distinct_meanings(self):
        value=response();value.pop('rateLimitsByLimitId')
        self.assertIn('原生默认桶','\n'.join(rate_limit_lines(value)))
        value['rateLimitsByLimitId']={}
        text='\n'.join(rate_limit_lines(value));self.assertIn('额度桶：原生未提供',text);self.assertNotIn('14%',text)
        value['rateLimitsByLimitId']={'codex':{}}
        text='\n'.join(rate_limit_lines(value));self.assertIn('额度窗口：原生未提供',text);self.assertNotIn('0%',text)

    def test_unknown_duration_never_becomes_five_hours_or_week(self):
        value=response();value['rateLimits']['primary']['windowDurationMins']=None
        self.assertIn('主窗口（时长未提供）','\n'.join(rate_limit_lines(value)))
        value['rateLimits']['primary']['windowDurationMins']=90
        self.assertIn('90 分钟','\n'.join(rate_limit_lines(value)))

    def test_invalid_percent_duration_reset_and_oversized_data_fail_closed(self):
        for field,values in (('usedPercent',(True,-1,101,3.5,None)),
                             ('windowDurationMins',(True,0,-1,'300')),
                             ('resetsAt',(True,-1,2**63,'tomorrow'))):
            for item in values:
                value=response();value['rateLimits']['primary'][field]=item
                with self.subTest(field=field,value=item),self.assertRaises(ValueError):rate_limit_lines(value)
        for value in (None,{},dict(response(),rateLimits=None),dict(response(),extra='x'*65536),
                      dict(response(),rateLimitsByLimitId={'x'+str(i):{} for i in range(17)}),
                      dict(response(),rateLimitsByLimitId={'bad\nkey':{}})):
            with self.assertRaises(ValueError):rate_limit_lines(value)


class QuotaReadTests(unittest.IsolatedAsyncioTestCase):
    def native(self):
        return SimpleNamespace(server_version='0.167.0',runtime_identity=(1,2),
                               rpc=SimpleNamespace(request=AsyncMock(return_value=response())))

    async def test_only_current_runtime_read_and_no_auth_reserve_reset_or_account_operations(self):
        native=self.native();self.assertIn('14%','\n'.join(await account_quota(native)))
        native.rpc.request.assert_awaited_once_with('account/rateLimits/read',{'excludeResetCreditDetails':True},timeout=5)

    async def test_unavailable_failure_and_invalid_response_do_not_claim_zero(self):
        for error in (RpcError(-32601,'PRIVATE_NATIVE'),TimeoutError('PRIVATE_TIMEOUT'),ValueError('PRIVATE_VALUE')):
            native=self.native();native.rpc.request.side_effect=error
            text='\n'.join(await account_quota(native));self.assertIn('暂时无法查询',text);self.assertNotIn('PRIVATE',text);self.assertNotIn('0%',text)
        native=self.native();native.rpc.request.return_value={}
        self.assertIn('暂时无法查询','\n'.join(await account_quota(native)))

    async def test_generation_change_rejects_returned_snapshot(self):
        native=self.native()
        async def changed(*a,**k):native.runtime_identity=(3,4);return response()
        native.rpc.request.side_effect=changed
        with self.assertRaisesRegex(CommandError,'连接已变化'):await account_quota(native)

    async def test_unverified_version_or_generation_does_not_query(self):
        for key,value in (('server_version','0.168.0'),('runtime_identity',None)):
            native=self.native();setattr(native,key,value)
            self.assertIn('未核验','\n'.join(await account_quota(native)));native.rpc.request.assert_not_awaited()
