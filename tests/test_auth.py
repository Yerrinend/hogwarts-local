import base64
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import urllib.parse
from unittest.mock import patch
import chatgpt_auth as auth

ROOT=Path(__file__).resolve().parents[2]/'work'
ROOT.mkdir(exist_ok=True)

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.accounts=auth.Accounts(self.temp.name)

    @unittest.skipUnless(os.name=='nt','Windows protection')
    def test_dpapi_roundtrip_and_persistent_host(self):
        raw=b'SECRET-REFRESH-TOKEN'
        encrypted=auth.protect(raw)
        self.assertNotIn(raw,encrypted)
        self.assertEqual(auth.protect(encrypted,True),raw)
        self.accounts.save()
        second=auth.Accounts(self.temp.name)
        self.assertEqual(second.records['host'],self.accounts.records['host'])

    @unittest.skipUnless(os.name=='nt','Windows RSA provider')
    def test_native_signature_and_tampering(self):
        fixture=json.loads((Path(__file__).parent/'rsa-public-fixture.json').read_text(encoding='utf-8-sig'))
        jwk={'kty':'RSA','n':fixture['n'],'e':fixture['e']}
        auth.verify_rs256(fixture['message'].encode(),auth.unb64(fixture['signature']),jwk)
        with self.assertRaises(ValueError):auth.verify_rs256(b'tampered',auth.unb64(fixture['signature']),jwk)

    def start(self,profile=None):
        with patch.object(self.accounts,'save'),patch('chatgpt_auth.webbrowser.open',return_value=True) as browser:
            r=self.accounts.start(8765,profile)
        url=browser.call_args.args[0]
        return r['attempt'],urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    def test_pkce_callback_validates_and_no_secrets_in_public(self):
        attempt,query=self.start()
        p=self.accounts.attempts[attempt]
        self.assertEqual(query['client_id'],['dynamic_agent_client'])
        self.assertEqual(query['redirect_uri'],['http://127.0.0.1:8765/auth/callback'])
        tokens={'access_token':'ACCESS-SECRET','refresh_token':'REFRESH-SECRET','id_token':'ID-SECRET',
                'token_type':'Bearer','expires_in':3600,'scope':auth.SCOPE}
        with patch('chatgpt_auth.request_json',return_value=tokens) as exchange,patch('chatgpt_auth.validate_id',return_value={'sub':'subject','email':'test@example.com'}),patch.object(self.accounts,'save'):
            self.accounts.callback({'state':[p['state']],'code':['code'],'client_id':['issued-client']})
        self.assertEqual(exchange.call_args.kwargs['data']['client_id'],'issued-client')
        self.assertEqual(exchange.call_args.kwargs['data']['redirect_uri'],query['redirect_uri'][0])
        self.assertEqual(self.accounts.status(attempt)['status'],'complete')
        self.assertNotIn('SECRET',json.dumps(self.accounts.public()))
        with self.assertRaises(ValueError):self.accounts.callback({'state':[p['state']],'code':['code'],'client_id':['issued-client']})
        pid=self.accounts.status(attempt)['result']
        _,returning=self.start(pid)
        self.assertEqual(returning['client_id'],['issued-client'])
        self.assertNotIn('agent_name_hint',returning)
        self.assertEqual(returning['ext_agent_host_id'],query['ext_agent_host_id'])

    def test_invalid_state_or_expired_attempt_does_not_exchange(self):
        attempt,query=self.start()
        with patch('chatgpt_auth.request_json') as request:
            with self.assertRaises(ValueError):self.accounts.callback({'state':['wrong'],'code':['x'],'client_id':['client']})
            self.accounts.attempts[attempt]['created']-=601
            with self.assertRaises(ValueError):self.accounts.callback({'state':query['state'],'code':['x'],'client_id':['client']})
            request.assert_not_called()

    def test_identity_checks(self):
        def token(claims,header=None):
            return '.'.join([auth.b64(json.dumps(header or {'alg':'RS256','kid':'key'}).encode()),auth.b64(json.dumps(claims).encode()),auth.b64(b'sig')])
        claims={'iss':auth.AUTH,'aud':'client','exp':time.time()+100,'sub':'subject','nonce':'nonce'}
        with patch('chatgpt_auth.request_json',return_value={'keys':[{'kid':'key'}]}),patch('chatgpt_auth.verify_rs256'):
            self.assertEqual(auth.validate_id(token(claims),'client','nonce')['sub'],'subject')
            for bad in ({'iss':'evil'},{'aud':'other'},{'exp':0},{'nonce':'wrong'},{'sub':'other'}):
                with self.assertRaises(ValueError):auth.validate_id(token({**claims,**bad}),'client','nonce','subject')
            with self.assertRaises(ValueError):auth.validate_id(token(claims,{'alg':'none','kid':'key'}),'client','nonce')

    def test_missing_permission_blocks_inference_and_refresh_is_saved(self):
        a={'client_id':'client','subject':'subject','access_token':'old','refresh_token':'old-refresh','scopes':[], 'expires_at':0}
        self.accounts.records['accounts']['profile']=a
        with patch('chatgpt_auth.request_json') as request:
            with self.assertRaises(ValueError):self.accounts.access('profile')
            request.assert_not_called()
        a['scopes']=[auth.DIRECT]
        with patch('chatgpt_auth.request_json',return_value={'access_token':'new','refresh_token':'new-refresh','token_type':'Bearer','expires_in':3600}),patch.object(self.accounts,'save') as save:
            self.assertEqual(self.accounts.access('profile')['access_token'],'new')
            self.assertEqual(a['refresh_token'],'new-refresh')
            save.assert_called_once()

    def test_sse_requires_terminal_success(self):
        def stream(events):return io.BytesIO(b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events))
        delta={'type':'response.output_text.delta','delta':'Text'}
        complete={'type':'response.completed','response':{'status':'completed','usage':{'total_tokens':4}}}
        r=auth.read_stream(stream([delta,complete]))
        self.assertEqual(r['choices'][0]['message']['content'],'Text')
        with self.assertRaises(ValueError):auth.read_stream(stream([delta]))
        with self.assertRaisesRegex(ValueError,'лимит'):auth.read_stream(stream([delta,{'type':'response.failed','response':{'error':{'code':'subscription_sharing_usage_limit_exceeded'}}}]))

    def test_response_uses_only_subscription_route(self):
        self.accounts.records['accounts']['p']={'access_token':'token','scopes':[auth.DIRECT],'expires_at':time.time()+1000,'model':'model','sent':0,'tokens':0}
        stream=io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"text"}\n\ndata: {"type":"response.completed","response":{"status":"completed"}}\n\n')
        with patch('chatgpt_auth.open_request',return_value=stream) as request,patch.object(self.accounts,'save'):
            self.accounts.generate('p','instructions','context')
        self.assertEqual(request.call_args.args[0],auth.API+'/responses')
        payload=request.call_args.kwargs['data']
        self.assertFalse(payload['store'])
        self.assertTrue(payload['stream'])
        self.assertEqual(payload['input'][0]['content'],'context')

    def test_logout_clears_tokens_even_if_remote_is_unavailable(self):
        self.accounts.records['accounts']['p']={'client_id':'client','access_token':'SECRET','refresh_token':'SECRET','id_token':'SECRET','scopes':[auth.DIRECT]}
        with patch('chatgpt_auth.request_json',side_effect=ValueError('offline')),patch.object(self.accounts,'save'):
            msg=self.accounts.logout('p')
        self.assertIn('не подтверждён',msg)
        self.assertNotIn('SECRET',json.dumps(self.accounts.records))
        self.assertEqual(self.accounts.records['accounts']['p']['client_id'],'client')

if __name__=='__main__':unittest.main()
