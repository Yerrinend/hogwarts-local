import copy
import json
import io
from email.message import Message
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

test_root = Path(__file__).resolve().parents[2] / 'work'
test_root.mkdir(exist_ok=True)
temp = tempfile.TemporaryDirectory(dir=test_root)
os.environ['RPG_DATA_DIR'] = temp.name
import server

class RPGTests(unittest.TestCase):
    def post(self, endpoint, body=None, token=True, origin=None):
        payload = json.dumps(body or {}).encode()
        handler = server.Handler.__new__(server.Handler)
        handler.path = '/api/' + endpoint
        handler.headers = Message()
        handler.headers['Host'] = f'127.0.0.1:{server.PORT}'
        handler.headers['Content-Length'] = str(len(payload))
        if token: handler.headers['X-RPG-Token'] = server.TOKEN
        if origin: handler.headers['Origin'] = origin
        handler.rfile = io.BytesIO(payload)
        responses = []
        handler.reply = lambda data, code=200: responses.append((data, code))
        handler.do_POST()
        data, code = responses[0]
        if code >= 400: raise urllib.error.HTTPError('', code, data.get('error'), {}, None)
        return data

    def setUp(self):
        server.KEYS.clear()
        for mode in ('personal', 'shared'): server.write_state(mode, server.initial(mode))

    def test_modes_and_secrets_are_isolated(self):
        self.post('save', {'mode':'personal', 'hero':'Стас', 'memory':'Личный факт'})
        self.assertEqual(self.post('state')['state']['memory'], '')
        self.post('profile', {'provider':'OpenAI','model':'test','key':'TOP-SECRET'})
        self.assertNotIn('TOP-SECRET',json.dumps(self.post('state')))
        self.assertNotIn('TOP-SECRET',self.post('context')['context'])

    def test_csrf_and_origin(self):
        for kwargs in ({'token':False}, {'origin':'https://evil.example'}):
            with self.assertRaises(urllib.error.HTTPError) as error: self.post('save', {'hero':'X'}, **kwargs)
            self.assertEqual(error.exception.code,403)

    def test_generation_and_branch(self):
        profile=self.post('profile', {'provider':'Grok','model':'test','key':'SECRET'})['profiles'][0]['id']
        chapter={'title':'Письмо','text':'На столе лежало письмо.','choices':['Вариант']*6,'memory':'Письмо на столе'}
        with patch('server.remote', return_value={'choices':[{'message':{'content':json.dumps(chapter)}}], 'usage':{'total_tokens':123}}):
            result=self.post('generate', {'profile':profile,'action':'Начать'})
        self.assertEqual(len(result['state']['chapters']),1)
        self.assertEqual(result['state']['memory'],'Письмо на столе')
        self.assertEqual(result['profiles'][0]['tokens'],123)
        self.post('chapter', {'text':'Следующая сцена'})
        self.post('fork', {'index':0})
        self.assertEqual(len(self.post('state')['state']['chapters']),1)
        self.assertTrue(list(Path(temp.name).glob('branch-shared-*.json')))

    def test_bad_model_format_preserves_history(self):
        profile=self.post('profile', {'provider':'Grok','model':'test','key':'SECRET'})['profiles'][0]['id']
        with patch('server.remote', return_value={'choices':[{'message':{'content':'Ответ обычным текстом'}}]}):
            r=self.post('generate', {'profile':profile,'action':'Начать'})
        self.assertIn('draft',r)
        self.assertEqual(self.post('state')['state']['chapters'],[])

    def test_import_validation_and_context_limit(self):
        incoming=server.initial('shared');incoming['hero']='Другой';incoming['chapters']=[{'title':'Сцена','text':'Текст','choices':[]}]
        self.post('import',{'state':incoming})
        self.assertEqual(self.post('state')['state']['hero'],'Другой')
        self.assertTrue(list(Path(temp.name).glob('backup-shared-*.json')))
        incoming['files']={str(i):'x'*90000 for i in range(3)}
        packet=json.loads(server.context(incoming))
        self.assertTrue(packet['retrieval']['partly_included'])
        self.assertLessEqual(len(server.context(incoming)),180000)
        self.assertEqual(len(incoming['files']['0']),90000)

    def test_github_only_writes_save_and_never_key(self):
        with patch('server.remote', return_value={'default_branch':'main'}):
            self.post('github-connect',{'repo':'tester/game','token':'GITHUB-SECRET'})
        self.post('profile',{'provider':'OpenAI','model':'test','key':'MODEL-SECRET'})
        with patch('server.remote', side_effect=[{'sha':'old-sha'}, {'commit':{}}]) as remote:
            self.post('github-push')
        url,token,payload,method=remote.call_args.args
        self.assertTrue(url.endswith('/hogwarts-local/shared/save.json'))
        self.assertEqual(method,'PUT')
        self.assertEqual(payload['sha'],'old-sha')
        import base64
        saved=base64.b64decode(payload['content']).decode()
        self.assertNotIn('SECRET',saved)

    def test_subscription_generation_never_uses_api_key_route(self):
        pid='chatgpt-test'
        profile={'id':pid,'provider':'OpenAI','kind':'chatgpt','name':'Test','model':'allowed-model','sent':0,'tokens':0}
        chapter={'title':'Новая сцена','text':'Герой увидел письмо.','choices':['Вариант']*6,'memory':'Письмо ещё не открыто'}
        with patch.object(server,'CHATGPT') as accounts,patch('server.remote') as paid_api:
            accounts.public.return_value=[profile]
            accounts.generate.return_value={'choices':[{'message':{'content':json.dumps(chapter)}}]}
            result=self.post('generate',{'profile':pid,'action':'Посмотреть на стол'})
            paid_api.assert_not_called()
            self.assertEqual(result['state']['memory'],chapter['memory'])
            self.assertIn('подписка',result['state']['chapters'][0]['source'])
            accounts.generate.side_effect=ValueError('Достигнут лимит')
            with self.assertRaises(urllib.error.HTTPError):self.post('generate',{'profile':pid,'action':'Продолжить'})
            self.assertEqual(len(server.read_state('shared')['chapters']),1)
            paid_api.assert_not_called()

    def test_unicode_repository_paths_and_legacy_text(self):
        import base64
        path='rpg/Персонажи/Драка — характер.md'
        tree={'sha':'tree-snapshot','tree':[{'type':'blob','path':path,'sha':'blob-sha','size':100}]}
        with patch('server.remote',return_value={'default_branch':'main'}):self.post('github-connect',{'repo':'test/game','token':'SECRET'})
        with patch('server.remote',return_value=tree):index=self.post('github-index')
        self.assertEqual(index['files'][0]['path'],path)
        text='Драка: гордая, умная, самостоятельная.'
        blob={'content':base64.b64encode(text.encode('cp1251')).decode()}
        with patch('server.remote',return_value=blob) as remote:r=self.post('github-pull',{'paths':[path]})
        self.assertEqual(r['state']['files'][path],text)
        self.assertEqual(r['state']['source_encodings'][path],'Windows-1251')
        self.assertTrue(remote.call_args.args[0].endswith('/git/blobs/blob-sha'))
        packet=json.loads(server.context(r['state'],'Драка'))
        self.assertIn(path,packet['source_files'])

    def test_language_does_not_rewrite_russian_sources(self):
        original=self.post('state')['state']['files']
        self.post('save',{'story_language':'en'})
        self.assertEqual(self.post('state')['state']['files'],original)
        text=self.post('context')['context']
        self.assertIn('английском',text)
        self.assertIn('story_language',text)

    def test_new_world_preserves_personal_history(self):
        self.post('chapter',{'mode':'personal','title':'Личная глава','text':'Мой выбор'})
        self.post('chapter',{'title':'Старая новая игра','text':'Пример'})
        self.post('save',{'story_language':'uk','hero':'Артём'})
        fresh=self.post('new-game')['state']
        self.assertEqual(fresh['chapters'],[])
        self.assertEqual(fresh['hero'],'Артём')
        self.assertEqual(fresh['story_language'],'uk')
        self.assertEqual(len(self.post('state',{'mode':'personal'})['state']['chapters']),1)
        self.assertEqual(fresh['world_pack_version'],'1.2')

    def test_asset_and_export_have_no_private_seed(self):
        handler=server.Handler.__new__(server.Handler)
        handler.path='/'
        handler.headers={'Host':f'127.0.0.1:{server.PORT}'}
        handler.wfile=io.BytesIO()
        headers={}
        handler.send_response=lambda code: self.assertEqual(code,200)
        handler.send_header=lambda key,value: headers.update({key:value})
        handler.end_headers=lambda: None
        handler.do_GET()
        self.assertIn('ХРОНИКИ',handler.wfile.getvalue().decode())
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(server.initial('personal')['chapters'],[])
        self.assertEqual(server.initial('shared')['chapters'],[])

if __name__=='__main__':unittest.main()
