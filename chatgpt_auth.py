"""Official SIWC local OAuth flow, Windows protected storage and RS256 validation.

No browser cookies, ChatGPT backend endpoints or API billing fallback.
"""
import base64
import copy
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

AUTH = 'https://auth.openai.com'
API = 'https://api.openai.com/v1'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
DIRECT = 'chatgpt.tokens.use.direct'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Сервис вернул неожиданный redirect. Авторизация остановлена.')

OPENER = urllib.request.build_opener(NoRedirect())

def open_request(url, *, token=None, data=None, form=False):
    if not any(url.startswith(host + '/') for host in (AUTH, API)):
        raise ValueError('Недопустимый адрес сервиса авторизации.')
    headers = {'User-Agent':'Hogwarts-Local/1.1', 'Accept':'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    payload = None
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        payload = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    try:
        return OPENER.open(urllib.request.Request(url, data=payload, headers=headers), timeout=150)
    except urllib.error.HTTPError as e:
        # Only stable error codes are surfaced; do not echo tokens or remote HTML.
        try:
            detail = json.loads(e.read(32768))
            code = detail.get('error', {})
            code = code.get('code', '') if isinstance(code, dict) else code
        except Exception:
            code = ''
        if code in ('subscription_sharing_usage_limit_exceeded', 'subscription_sharing_user_not_eligible', 'subscription_sharing_unsupported_capability', 'invalid_grant'):
            msg = {'subscription_sharing_usage_limit_exceeded':'Достигнут лимит использования подписки. Открой ChatGPT → Настройки → Usage.',
                   'subscription_sharing_user_not_eligible':'Использование подписки недоступно этому аккаунту или рабочему пространству.',
                   'subscription_sharing_unsupported_capability':'Модель или функция не поддерживается подключением подписки.',
                   'invalid_grant':'Сессия истекла или отозвана. Выполни вход заново.'}[code]
        else:
            msg = f'ChatGPT вернул HTTP {e.code}. Проверь доступ и разрешения аккаунта.'
        raise ValueError(msg + ' Перехода на платный API нет.') from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('Нет соединения с OpenAI. Проверь интернет и повтори вход или запрос.') from None

def request_json(url, **kwargs):
    with open_request(url, **kwargs) as response:
        data = response.read(2_000_000)
        if not data:
            return {}
        return json.loads(data)

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def unb64(text):
    return base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)

def protect(data, decrypt=False):
    """Use per-user Windows DPAPI, never machine-wide protection."""
    if os.name != 'nt':
        raise ValueError('Защищённый вход через ChatGPT в этой сборке поддерживается только в Windows.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', W.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    api = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.POINTER(Blob)]
    fn.restype = W.BOOL
    buf = ctypes.create_string_buffer(data)
    inp = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out = Blob()
    if not fn(ctypes.byref(inp), None, None, None, None, 1, ctypes.byref(out)):
        raise ValueError('Windows не смогла открыть защищённое хранилище аккаунтов. Не переноси его между пользователями Windows.')
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        kernel.LocalFree(out.data)

def verify_rs256(message, signature, jwk):
    """Verify with Windows CNG instead of implementing RSA in Python."""
    if jwk.get('kty') != 'RSA' or jwk.get('use', 'sig') != 'sig' or jwk.get('alg', 'RS256') != 'RS256':
        raise ValueError('Неподдерживаемый ключ проверки ID token.')
    n, e = unb64(jwk['n']), unb64(jwk['e'])
    if not 256 <= len(n) <= 1024 or not 1 <= len(e) <= 8 or len(signature) != len(n):
        raise ValueError('Некорректный RSA-ключ или подпись.')
    bcrypt = ctypes.WinDLL('bcrypt', use_last_error=True)
    P = ctypes.c_void_p
    U = W.ULONG
    bcrypt.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(P), W.LPCWSTR, W.LPCWSTR, U]
    bcrypt.BCryptImportKeyPair.argtypes = [P,P,W.LPCWSTR,ctypes.POINTER(P),P,U,U]
    bcrypt.BCryptVerifySignature.argtypes = [P,P,P,U,P,U,U]
    bcrypt.BCryptDestroyKey.argtypes = [P]
    bcrypt.BCryptCloseAlgorithmProvider.argtypes = [P,U]
    for name in ('BCryptOpenAlgorithmProvider','BCryptImportKeyPair','BCryptVerifySignature','BCryptDestroyKey','BCryptCloseAlgorithmProvider'):
        getattr(bcrypt,name).restype = W.LONG
    algorithm, key = P(), P()
    if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm),'RSA',None,0) != 0:
        raise ValueError('Windows CNG недоступен.')
    try:
        blob = struct.pack('<6I',0x31415352,len(n)*8,len(e),len(n),0,0) + e + n
        blobbuf = ctypes.create_string_buffer(blob)
        if bcrypt.BCryptImportKeyPair(algorithm,None,'RSAPUBLICBLOB',ctypes.byref(key),blobbuf,len(blob),0) != 0:
            raise ValueError('Не удалось импортировать публичный ключ OpenAI.')
        class Padding(ctypes.Structure):
            _fields_ = [('algorithm',W.LPCWSTR)]
        padding = Padding('SHA256')
        digest = ctypes.create_string_buffer(hashlib.sha256(message).digest())
        sigbuf = ctypes.create_string_buffer(signature)
        if bcrypt.BCryptVerifySignature(key,ctypes.byref(padding),digest,32,sigbuf,len(signature),2) != 0:
            raise ValueError('Подпись ID token не прошла проверку.')
    finally:
        if key: bcrypt.BCryptDestroyKey(key)
        bcrypt.BCryptCloseAlgorithmProvider(algorithm,0)

def validate_id(encoded, client_id, nonce=None, expected_subject=None):
    try:
        head, body, sig = encoded.split('.')
        header, claims = json.loads(unb64(head)), json.loads(unb64(body))
    except Exception:
        raise ValueError('Некорректный ID token.') from None
    if header.get('alg') != 'RS256' or not header.get('kid') or header.get('crit'):
        raise ValueError('Недопустимый алгоритм ID token.')
    keys = request_json(AUTH + '/.well-known/jwks.json').get('keys', [])
    keys = [k for k in keys if k.get('kid') == header['kid']]
    if len(keys) != 1:
        raise ValueError('Ключ подписи OpenAI не найден. Повтори вход позже.')
    verify_rs256((head + '.' + body).encode('ascii'), unb64(sig), keys[0])
    audience = claims.get('aud')
    audiences = audience if isinstance(audience,list) else [audience]
    now = time.time()
    if claims.get('iss') != AUTH or client_id not in audiences or (len(audiences)>1 and claims.get('azp') != client_id):
        raise ValueError('ID token выдан другому приложению.')
    if not isinstance(claims.get('exp'),(int,float)) or claims['exp'] <= now or claims.get('iat',now) > now+60 or claims.get('nbf',0) > now+60:
        raise ValueError('Срок действия ID token не прошёл проверку.')
    if nonce is not None and not secrets.compare_digest(str(claims.get('nonce','')),nonce):
        raise ValueError('Nonce авторизации не совпадает.')
    if not isinstance(claims.get('sub'),str) or not claims['sub'] or (expected_subject and claims['sub'] != expected_subject):
        raise ValueError('Авторизован другой аккаунт. Исходный профиль не изменён.')
    return claims

class Accounts:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / 'chatgpt-accounts.dpapi'
        self.lock = threading.RLock()
        self.attempts = {}
        self.records = {'host':'urn:uuid:'+str(uuid.uuid4()),'accounts':{}}
        if self.path.exists():
            try:
                self.records = json.loads(protect(self.path.read_bytes(),True))
            except Exception:
                raise ValueError('Не удалось открыть хранилище ChatGPT. Исходный файл сохранён без изменений.') from None

    def save(self):
        encrypted = protect(json.dumps(self.records,ensure_ascii=False).encode())
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(encrypted)
        os.replace(temporary,self.path)

    def public(self):
        with self.lock:
            return self._public()

    def _public(self):
        out=[]
        for pid,a in self.records['accounts'].items():
            out.append({'id':pid,'provider':'OpenAI','kind':'chatgpt','name':a['email'] or 'ChatGPT',
                        'model':a.get('model',''),'sent':a.get('sent',0),'tokens':a.get('tokens',0),
                        'status':a.get('status','Вход выполнен'),'sharing':DIRECT in a.get('scopes',[]),
                        'connected':bool(a.get('access_token')),'label':pid[-6:]})
        return out

    def start(self, port, profile=None):
        with self.lock:
            old = self.records['accounts'].get(profile) if profile else None
            if profile and not old:
                raise ValueError('Неизвестный аккаунт ChatGPT.')
            self.save()  # Persist host identity BEFORE opening the browser.
            self.attempts={k:v for k,v in self.attempts.items() if time.time()-v['created']<600}
            if len(self.attempts)>=8:
                raise ValueError('Слишком много попыток входа. Подожди 10 минут.')
            attempt=secrets.token_urlsafe(32)
            pending={'created':time.time(),'state':secrets.token_urlsafe(32),'nonce':secrets.token_urlsafe(32),
                     'verifier':secrets.token_urlsafe(48),'redirect':f'http://127.0.0.1:{port}/auth/callback',
                     'profile':profile,'client':old['client_id'] if old else None,'status':'pending'}
            params={'client_id':pending['client'] or 'dynamic_agent_client','ext_agent_host_id':self.records['host'],
                    'response_type':'code','redirect_uri':pending['redirect'],'scope':SCOPE,'resource':API,
                    'state':pending['state'],'nonce':pending['nonce'],'code_challenge_method':'S256',
                    'code_challenge':b64(hashlib.sha256(pending['verifier'].encode()).digest())}
            if old:
                if old.get('id_token'):params['id_token_hint']=old['id_token']
                if old.get('email'):params['login_hint']=old['email']
            else:
                params['agent_name_hint']='Hogwarts Local'
            self.attempts[attempt]=pending
            # Auth URL with any ID hint stays server-side; never logs/browser storage.
            if not webbrowser.open(AUTH+'/api/accounts/authorize?'+urllib.parse.urlencode(params)):
                pending.update(status='error',message='Не удалось открыть системный браузер. Проверь браузер по умолчанию.')
            return {'attempt':attempt}

    def status(self, attempt):
        p=self.attempts.get(attempt)
        if not p:raise ValueError('Попытка входа не найдена.')
        if p['status']=='pending' and time.time()-p['created']>=600:
            p.update(status='error',message='Время входа истекло. Начни заново.')
        return {k:p[k] for k in ('status','message','result') if k in p}

    def callback(self, query):
        with self.lock:
            states=query.get('state',[])
            pending=None
            for p in self.attempts.values():
                if len(states)==1 and secrets.compare_digest(p['state'],states[0]) and p['status']=='pending':
                    pending=p;break
            if not pending or time.time()-pending['created']>=600:
                raise ValueError('Запрос авторизации истёк или state не совпадает.')
            try:
                if query.get('error'):
                    raise ValueError('Вход или разрешение отменены. Доступ к подписке не включён.')
                client=query.get('client_id',[pending['client']])
                codes=query.get('code',[])
                if len(client)!=1 or not client[0] or client[0]=='dynamic_agent_client' or len(codes)!=1 or not codes[0]:
                    raise ValueError('Регистрация не завершена: отсутствует код или выданный client_id.')
                client=client[0]
                if pending['client'] and client!=pending['client']:
                    raise ValueError('Получен client_id другого аккаунта.')
                tokens=request_json(AUTH+'/api/accounts/oauth/token',form=True,data={
                    'grant_type':'authorization_code','client_id':client,'code':codes[0],
                    'code_verifier':pending['verifier'],'redirect_uri':pending['redirect'],'resource':API})
                old=self.records['accounts'].get(pending['profile'])
                claims=validate_id(tokens.get('id_token',''),client,pending['nonce'],old['subject'] if old else None)
                if tokens.get('token_type','').lower()!='bearer' or not tokens.get('access_token'):
                    raise ValueError('Не получен access token для подключения.')
                pid=pending['profile'] or 'chatgpt-'+hashlib.sha256((client+'\0'+claims['sub']).encode()).hexdigest()[:24]
                existing=self.records['accounts'].get(pid,{})
                record={**existing,'client_id':client,'subject':claims['sub'],'email':claims.get('email',''),
                        'issuer':AUTH,'model':existing.get('model',''),'sent':existing.get('sent',0),'tokens':existing.get('tokens',0)}
                self.update_tokens(record,tokens)
                self.records['accounts'][pid]=record
                self.save()
                pending.update(status='complete',result=pid,message='Вход выполнен. Вернись в игру и выбери модель.' if DIRECT in record['scopes'] else 'Вход выполнен, но доступ к подписке не разрешён. Включи его через повторный вход.')
                return pending['message']
            except Exception as e:
                message=str(e) if isinstance(e,ValueError) else 'Не удалось завершить авторизацию. Повтори вход.'
                pending.update(status='error',message=message)
                raise ValueError(message) from None
            finally:
                pending.pop('verifier',None)

    def update_tokens(self,a,tokens):
        a.update(access_token=tokens['access_token'],refresh_token=tokens.get('refresh_token',a.get('refresh_token')),
                 id_token=tokens.get('id_token',a.get('id_token')),expires_at=time.time()+int(tokens.get('expires_in',3600)),
                 scopes=tokens['scope'].split() if 'scope' in tokens else a.get('scopes',[]))
        a['status']='Подписка подключена' if DIRECT in a['scopes'] else 'Нужно разрешение на использование подписки'

    def access(self,pid):
        a=self.records['accounts'].get(pid)
        if not a or not a.get('access_token'):raise ValueError('Выполни вход в этот аккаунт ChatGPT.')
        if DIRECT not in a.get('scopes',[]):raise ValueError('Вход выполнен без разрешения использовать подписку. Выполни вход повторно и предоставь разрешение.')
        if a['expires_at']<time.time()+60:
            if not a.get('refresh_token'):raise ValueError('Сессия истекла. Выполни вход повторно.')
            t=request_json(AUTH+'/api/accounts/oauth/token',form=True,data={'grant_type':'refresh_token',
                'client_id':a['client_id'],'refresh_token':a['refresh_token'],'resource':API})
            if t.get('id_token'):validate_id(t['id_token'],a['client_id'],expected_subject=a['subject'])
            if t.get('token_type','').lower()!='bearer' or not t.get('refresh_token') or not t.get('access_token'):
                raise ValueError('Неполный ответ обновления сессии. Выполни вход заново.')
            self.update_tokens(a,t);self.save()
            if DIRECT not in a['scopes']:raise ValueError('Доступ к подписке отозван. Выполни вход повторно.')
        return a

    def models(self,pid):
        with self.lock:
            a=self.access(pid)
            result=request_json(API+'/models',token=a['access_token'])
            models=[{'slug':x['slug'],'name':x.get('display_name',x['slug'])} for x in result.get('models',[]) if x.get('visibility')=='list' and x.get('slug')]
            a['models']=models
            if a.get('model') not in [m['slug'] for m in models]:a['model']=models[0]['slug'] if models else ''
            self.save()
            return {'models':models,'selected':a['model']}

    def choose_model(self,pid,slug):
        with self.lock:
            a=self.records['accounts'].get(pid,{})
            if slug not in [m['slug'] for m in a.get('models',[])]:raise ValueError('Выбери модель из каталога этого аккаунта.')
            a['model']=slug;self.save()

    def generate(self,pid,instructions,content):
        with self.lock:
            a=self.access(pid)
            if not a.get('model'):raise ValueError('Загрузи список моделей и выбери доступную модель ChatGPT.')
            try:
                with open_request(API+'/responses',token=a['access_token'],data={
                    'model':a['model'],'instructions':instructions,'input':[{'role':'user','content':content}],
                    'store':False,'stream':True}) as response:
                    result=read_stream(response)
                a['sent']=a.get('sent',0)+1
                a['tokens']=a.get('tokens',0)+result.get('usage',{}).get('total_tokens',0)
                a['status']='Подписка · последний запрос выполнен'
                self.save()
                return result
            except ValueError:
                a['status']='Запрос не выполнен — проверь лимит и доступ'
                self.save()
                raise

    def logout(self,pid):
        with self.lock:
            a=self.records['accounts'].get(pid)
            if not a:raise ValueError('Аккаунт не найден.')
            revoked=True
            try:
                if a.get('refresh_token'):
                    discovery=request_json(AUTH+'/.well-known/openid-configuration')
                    endpoint=discovery.get('revocation_endpoint','')
                    if not endpoint.startswith(AUTH+'/'):raise ValueError('Недопустимый revocation endpoint.')
                    request_json(endpoint,form=True,data={'token':a['refresh_token'],'token_type_hint':'refresh_token','client_id':a['client_id']})
            except Exception:
                revoked=False
            for key in ('access_token','refresh_token','id_token','expires_at','models'):a.pop(key,None)
            a['status']='Выход выполнен';a['scopes']=[];self.save()
            return 'Выход выполнен.' if revoked else 'Локальный выход выполнен. Отзыв сессии на сервере не подтверждён; отключи приложение в настройках ChatGPT.'

def read_stream(response):
    chunks=[]
    event=[]
    total=0
    for raw in response:
        total+=len(raw)
        if total>8_000_000:raise ValueError('Ответ слишком большой. История не изменена.')
        line=raw.decode('utf-8').rstrip('\r\n')
        if line.startswith('data:'):event.append(line[5:].lstrip())
        elif not line and event:
            data='\n'.join(event);event=[]
            if data=='[DONE]':break
            obj=json.loads(data)
            kind=obj.get('type')
            if kind=='response.output_text.delta':chunks.append(obj.get('delta',''))
            elif kind in ('response.failed','response.incomplete','error'):
                code=(obj.get('response',{}).get('error') or obj.get('error') or {}).get('code',obj.get('code',''))
                if code=='subscription_sharing_usage_limit_exceeded':
                    raise ValueError('Достигнут лимит подписки или приложения. Проверь ChatGPT → Настройки → Usage. Перехода на платный API нет.')
                raise ValueError('ChatGPT не завершил ответ. Проверь доступность модели и лимиты. История не изменена.')
            elif kind=='response.completed':
                r=obj.get('response',{})
                if r.get('status')!='completed':raise ValueError('Ответ не завершён.')
                text=''.join(chunks)
                if not text:
                    text=''.join(c.get('text','') for item in r.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
                if not text.strip():raise ValueError('ChatGPT вернул пустой ответ.')
                return {'choices':[{'message':{'content':text}}],'usage':r.get('usage') or {}}
    raise ValueError('Соединение прервано до завершения ответа. История не изменена; автоматического повтора нет.')
