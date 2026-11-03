"""Real Unix peer + foreground polling + durable SQLite + counting fake WeChat."""
import asyncio
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from websockets.asyncio.server import unix_serve

import test_async_questions as fixtures
from test_wechat_state import message
from wx_clawbot.agents.codex import CodexConnection
from wx_clawbot.delivery import Sender
from wx_clawbot.execution import Execution
from wx_clawbot.service import poll


class AsyncServiceTests(fixtures.AsyncFixture):
    async def test_poll_and_unix_peer_answer_before_original_final(self):
        self.sock_temp = tempfile.TemporaryDirectory(prefix='wx-ask-',dir='/tmp')
        self.addCleanup(self.sock_temp.cleanup)
        socket = Path(self.sock_temp.name)/'native.sock'
        thread_id, turn_id = 'thread-two','unix-turn'
        thread = {'id':thread_id,'cwd':str(self.sessions[1].target.cwd),'sessionId':'native-session-two',
                  'model':'fixture','modelProvider':'fixture','status':{'type':'idle'}}
        turn = {'id':turn_id,'status':'inProgress','items':[]}
        methods, answers, delivered = [], [], []
        question_sent, finished = asyncio.Event(),asyncio.Event()

        async def peer(ws):
            async for raw in ws:
                request = json.loads(raw)
                method,params = request['method'],request.get('params',{})
                methods.append(method)
                if 'id' not in request:
                    continue
                result,events = {},[]
                if method == 'initialize':
                    result = {'userAgent':'fixture/0.166.0','platformFamily':'unix','platformOs':'macos','codexHome':'/fixture'}
                elif method in {'thread/read','thread/resume'}:
                    result = {'thread':thread}
                elif method == 'thread/loaded/list':
                    result = {'data':[thread_id],'nextCursor':None}
                elif method == 'thread/queue/list':
                    result = {'data':[],'nextCursor':None}
                elif method == 'thread/turns/list':
                    result = {'data':[turn],'nextCursor':None}
                elif method == 'thread/queue/add':
                    thread['status'] = {'type':'active'}
                    user = {'type':'userMessage','clientId':params['clientUserMessageId']}
                    turn['items'].append(user)
                    result = {'queuedSubmission':{'id':'unix-queue','clientUserMessageId':params['clientUserMessageId']}}
                    question = {'type':'agentMessage','id':'unix-question','delivery':'async','phase':'final_answer',
                                'questions':[{'title':'choose fixture','options':['ALPHA','BETA']}],'text':'fixture question'}
                    events = [('item/started',{'threadId':thread_id,'turnId':turn_id,'item':user}),
                              ('item/completed',{'threadId':thread_id,'turnId':turn_id,'item':question})]
                elif method == 'turn/steer':
                    assert params['expectedTurnId'] == turn_id
                    answers.append(params)
                    self.assertTrue(question_sent.is_set())
                    self.assertTrue(any('/answer q-' in text for text in delivered))
                    user = {'type':'userMessage','clientId':params['clientUserMessageId'],'content':params['input']}
                    turn['items'].extend([user,{'type':'agentMessage','phase':'final_answer','text':'UNIX-ANSWER-BETA-FINAL'}])
                    turn['status'] = 'completed'
                    thread['status'] = {'type':'idle'}
                    result = {'turnId':turn_id}
                    events = [('item/started',{'threadId':thread_id,'turnId':turn_id,'item':user}),
                              ('turn/completed',{'threadId':thread_id,'turn':{'id':turn_id,'status':'completed'}})]
                await ws.send(json.dumps({'id':request['id'],'result':result}))
                for name,params in events:
                    await ws.send(json.dumps({'method':name,'params':params}))

        server = await unix_serve(peer,socket)
        os.chmod(socket,0o600)
        native = await CodexConnection.connect(socket)
        self.agent = native
        self.catalog.agent = native
        for session in self.sessions:
            session.binding = replace(session.binding,runtime_identity=native.runtime_identity)
        self.engine = Execution(self.controller)
        await self.select()

        state = self.state
        class Api:
            def __init__(api):
                api.received = 0
            async def updates(api,*_):
                api.received += 1
                if api.received == 1:
                    text = 'fixture async service task'
                elif api.received == 2:
                    await question_sent.wait()
                    rows = await state.async_rows(active=True)
                    assert len(rows)==1
                    text = '/answer '+rows[0]['public_id']+' BETA'
                else:
                    await asyncio.Event().wait()
                return {'ret':0,'msgs':[message(900+api.received,text=text,created=900+api.received)]}
            async def send_text(api,*_,**kwargs):
                delivered.append(kwargs['text'])
                if '/answer q-' in kwargs['text']:
                    question_sent.set()
                if 'UNIX-ANSWER-BETA-FINAL' in kwargs['text']:
                    finished.set()
                return {'message_id':'fixture-server-'+str(len(delivered))}

        api = Api()
        jobs = [asyncio.create_task(self.engine.run()),asyncio.create_task(poll(self.controller,api)),
                asyncio.create_task(Sender(self.state,api).run())]
        try:
            async with asyncio.timeout(10):
                while not finished.is_set():
                    for job in jobs:
                        if job.done():
                            job.result()
                    await asyncio.sleep(.01)
            tasks = await self.state.tasks()
            self.assertEqual(len(tasks),1)
            self.assertEqual(tasks[0]['state'],'completed')
            self.assertEqual(methods.count('thread/queue/add'),1)
            self.assertEqual(methods.count('turn/steer'),1)
            self.assertEqual(len(answers),1)
            rows = await self.state.async_rows(task_id=tasks[0]['id'])
            self.assertEqual(rows[0]['state'],'observed')
            self.assertEqual(sum('UNIX-ANSWER-BETA-FINAL' in t for t in delivered),1)
        finally:
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs,return_exceptions=True)
            await native.close()
            server.close()
            await server.wait_closed()
