import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from patcwatch.background import definition
from patcwatch.microsoft import Collector, Graph, MicrosoftAuth, TrustedHttp, workbook_items
from patcwatch.scheduler import ProcessLock, Scheduler, SourceError, Store


class MicrosoftTests(unittest.TestCase):
    def test_refresh_once_after_unauthorized(self):
        auth = Mock()
        auth.token.side_effect = ['expired', 'fresh']
        http = Mock()
        http.get.side_effect = [Mock(status_code=401), Mock(status_code=200, json=lambda: {'value': []})]
        self.assertEqual(Graph(auth, http).get('/me/chats'), {'value': []})
        self.assertEqual([c.kwargs['force'] for c in auth.token.call_args_list], [False, True])
        self.assertEqual(http.get.call_args.kwargs['headers']['Authorization'], 'Bearer fresh')

    def test_silent_auth_requires_one_account_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = MicrosoftAuth(Path(tmp), Mock())
            auth.app, auth.cache, auth.vault = Mock(), Mock(has_state_changed=True), Mock()
            auth.app.get_accounts.return_value = [{'id': 'one'}]
            auth.app.acquire_token_silent_with_error.return_value = {'access_token': 'fixture'}
            self.assertEqual(auth.token(), 'fixture')
            auth.vault.save.assert_called_once()
            auth.app.get_accounts.return_value = []
            with self.assertRaisesRegex(SourceError, 'SIGN_IN_REQUIRED'): auth.token()

    def test_pagination_cannot_leak_auth(self):
        auth, http = Mock(), Mock()
        graph = Graph(auth, http)
        for url in ['https://evil.example/v1.0/me', 'https://graph.microsoft.com.evil.example/v1.0/me']:
            with self.assertRaisesRegex(SourceError, 'PAGINATION_DESTINATION_DENIED'): graph.get(url)
        auth.token.assert_not_called()
        http.get.assert_not_called()
        graph.get = Mock(return_value={'value': [], '@odata.nextLink': '/me/chats'})
        with self.assertRaisesRegex(SourceError, 'INCOMPLETE_PAGINATION'): graph.pages('/me/chats')

    def test_workbook_identity_is_not_row_position(self):
        config = {'sheet': 'QA', 'header_row': 1, 'id_column': 'ID', 'columns': ['Feedback']}
        rows = [['ID', 'Feedback'], ['2', 'B'], ['1', 'A']]
        self.assertEqual([x['id'] for x in workbook_items({'QA': rows}, config)], ['2','1'])
        for bad in [[['ID','Feedback'],['1','a'],['1','b']], [['ID','Feedback'],['','a']]]:
            with self.assertRaisesRegex(SourceError, 'DUPLICATE_OR_MISSING_ROW_ID'): workbook_items({'QA':bad},config)
        with self.assertRaisesRegex(SourceError, 'ROW_MAPPING_UNAVAILABLE'):
            workbook_items({'QA':[['ID','Feedback','Feedback'],['1','a','b']]}, config)

    def test_atomic_rollback_and_single_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner = ProcessLock(root)
            try:
                with self.assertRaises(RuntimeError): ProcessLock(root)
            finally: owner.close()
            replacement = ProcessLock(root); replacement.close()
            store = Store(root)
            try:
                store.add('teams','QA',{'chat_id':'fixed'})
                scheduler = Scheduler(store, Mock())
                scheduler.commit(store.sources()[0], {'complete':True,'items':[{'id':'1','content':'old'}]}, 100)
                before = store.sources()[0]
                store.db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON event BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
                with self.assertRaises(Exception):
                    scheduler.commit(before, {'complete':True,'items':[{'id':'1','content':'new'}]}, 200)
                self.assertEqual(store.sources()[0]['last_success'],100)
                self.assertEqual(store.events(),[])
                store.db.execute('DROP TRIGGER fail_event')
                scheduler.commit(store.sources()[0], {'complete':True,'items':[{'id':'1','content':'new'}]},200)
                self.assertEqual(len(store.events()),1)
            finally:store.close()

    def test_plain_text_teams_preserves_angle_brackets(self):
        graph = Mock()
        graph.pages.return_value = [{'id':'1','body':{'contentType':'text','content':'<first>'}}]
        capture = Collector(graph).read({'kind':'teams','config':{'chat_id':'qa'},'cursor':{}})
        self.assertIn('<first>',capture['items'][0]['content'])

    def test_background_does_not_need_browser(self):
        value = definition(Path('/tmp/state with spaces'),8793,300,'/runtime with spaces/python')
        self.assertEqual(value['ProgramArguments'][0],'/runtime with spaces/python')
        self.assertIn('--microsoft',value['ProgramArguments'])
        self.assertTrue(value['KeepAlive'])
        self.assertEqual(value['Umask'],0o077)

    def test_transport_rejects_model_and_mutating_graph(self):
        http = TrustedHttp()
        http.session = Mock()
        with self.assertRaisesRegex(SourceError,'NETWORK_DESTINATION_DENIED'):http.get('https://api.openai.com/v1/models')
        with self.assertRaisesRegex(SourceError,'READ_ONLY_POLICY'):http.post('https://graph.microsoft.com/v1.0/chats')
        http.session.request.assert_not_called()

if __name__ == '__main__':unittest.main()
