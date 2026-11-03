import unittest
import test_controller as controller_fixtures
import test_async_questions as async_fixtures


class AsyncQuestionRepro(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = async_fixtures.AsyncFixture.asyncSetUp
    incoming = controller_fixtures.ControllerTests.incoming
    command = controller_fixtures.ControllerTests.command
    select = controller_fixtures.ControllerTests.select

    async def test_structured_async_question_is_not_delayed_until_turn_completion(self):
        await self.select()
        await self.command('fixture business task')
        task = (await self.state.tasks())[0]
        thread, turn = task['thread_id'], 'fixture-business-turn'
        await self.engine.event({'method':'item/started','params':{'threadId':thread,'turnId':turn,
            'item':{'type':'userMessage','clientId':task['client_id']}}})
        await self.engine.event({'method':'item/completed','params':{'threadId':thread,'turnId':turn,
            'item':{'id':'fixture-async-item','type':'agentMessage','phase':'final_answer','delivery':'async',
                    'questions':[{'title':'Fixture public credit?','options':['ALPHA','BETA']}],
                    'text':'Fixture public credit? ALPHA / BETA'}}})
        rows = await self.state._call(lambda:list(self.state.db.execute(
            "SELECT text FROM outbox WHERE text LIKE '%/answer %'")))
        self.assertEqual(len(rows),1,'Structured async question must be actionable before the turn completes')
