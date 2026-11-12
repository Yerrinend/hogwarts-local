"""Local RPG server. Python 3.10+, standard library only."""
import base64
from contextlib import contextmanager
import copy
import html
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from chatgpt_auth import Accounts
from context_pack import build as build_context, decode_text

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DATA = Path(os.environ.get('RPG_DATA_DIR', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get('RPG_PORT', '8765'))
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
KEYS = {}
GITHUB = {}
CHATGPT = None
ENDPOINTS = {'OpenAI': 'https://api.openai.com/v1', 'Grok': 'https://api.x.ai/v1'}
STARTER = json.loads((ROOT / 'starter' / 'game.json').read_text(encoding='utf-8'))

@contextmanager
def db():
    c = sqlite3.connect(DATA / 'game.sqlite3')
    try:
        with c:
            c.execute('CREATE TABLE IF NOT EXISTS states (mode TEXT PRIMARY KEY, body TEXT NOT NULL)')
            yield c
    finally:
        c.close()

def initial(mode):
    return {'hero': 'Гарри' if mode == 'shared' else 'Стас', 'memory': '', 'chapters': [],
            'files': copy.deepcopy(STARTER['files']), 'repo': None, 'branch': 'Основная история',
            'story_language':'ru','world_pack_version':STARTER.get('version','1.2')}

def read_state(mode):
    with db() as c:
        row = c.execute('SELECT body FROM states WHERE mode=?', (mode,)).fetchone()
    return json.loads(row[0]) if row else initial(mode)

def write_state(mode, state):
    validate_state(state)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO states VALUES (?, ?)', (mode, json.dumps(state, ensure_ascii=False)))

def validate_state(s):
    if not isinstance(s, dict) or not isinstance(s.get('hero'), str) or not 1 <= len(s['hero']) <= 80:
        raise ValueError('Укажите имя героя длиной до 80 символов.')
    if not isinstance(s.get('memory'), str) or not isinstance(s.get('chapters'), list) or not isinstance(s.get('files'), dict):
        raise ValueError('Некорректный формат сохранения.')
    if len(s['memory']) > 60000 or len(s['files']) > 5000:
        raise ValueError('Слишком большой пакет контекста.')
    for name, content in s['files'].items():
        if not isinstance(name, str) or not isinstance(content, str) or len(content) > 2000000:
            raise ValueError('Файлы должны содержать текст, не более 2 000 000 символов каждый.')
    if sum(len(v) for v in s['files'].values()) > 16000000:
        raise ValueError('Материалы превышают 16 миллионов символов.')
    if s.get('story_language','ru') not in ('ru','uk','en'):
        raise ValueError('Неизвестный язык истории.')
    for ch in s['chapters']:
        if not isinstance(ch, dict) or not isinstance(ch.get('text'), str) or not isinstance(ch.get('title'), str):
            raise ValueError('У каждой главы должны быть title и text.')
        if not isinstance(ch.get('choices', []), list) or any(not isinstance(x, str) for x in ch.get('choices', [])):
            raise ValueError('Варианты действий должны быть списком строк.')

def context(s,query=''):
    return build_context(s,query)

def remote(url, token, body=None, method=None):
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
               'User-Agent': 'Hogwarts-Local/1.0', 'Accept': 'application/json'}
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=150) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        # Do not echo remote response bodies: they may contain request data or credentials.
        labels = {401: 'Ключ или токен не принят', 403: 'Недостаточно прав или доступа',
                  404: 'Модель, репозиторий или файл не найден', 409: 'Конфликт версий — обновите данные',
                  422: 'Сервис отклонил параметры запроса', 429: 'Ограничение частоты или баланса'}
        raise ValueError(f'{labels.get(e.code, "Ошибка сервиса")} (HTTP {e.code}).') from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('Сервис недоступен или не ответил вовремя. Сохранение не изменено.') from None

def chatgpt():
    global CHATGPT
    if CHATGPT is None:
        CHATGPT = Accounts(DATA)
    return CHATGPT

def public_profiles():
    return chatgpt().public() + [{k: v for k, v in p.items() if k != 'key'} for p in KEYS.values()]

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value, code=200):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def trusted(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):
            return False
        origin = self.headers.get('Origin')
        return not origin or origin in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}')

    def do_GET(self):
        if not self.trusted():
            return self.reply({'error': 'Доступ только с локального адреса.'}, 403)
        path = urllib.parse.urlparse(self.path).path
        if path == '/auth/callback':
            try:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                message = chatgpt().callback(query)
            except Exception as e:
                message = str(e) if isinstance(e, ValueError) else 'Вход не завершён. Вернись в приложение и повтори попытку.'
            page = ('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Вход через ChatGPT</title>'
                    '<h1>Hogwarts Local</h1><p>' + html.escape(message) + '</p><p><a href="/">Вернуться в игру</a></p></html>').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(page)
            return
        if path == '/api/bootstrap':
            return self.reply({'token': TOKEN, 'starter': STARTER['name'], 'version': '1.3.1'})
        assets = {'/': 'index.html', '/app.js': 'app.js', '/view.js':'view.js', '/style.css': 'style.css', '/i18n.js':'i18n.js','/locales.json':'locales.json'}
        if path not in assets:
            return self.reply({'error': 'Не найдено'}, 404)
        data = (ROOT / 'web' / assets[path]).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', {'/': 'text/html; charset=utf-8', '/app.js': 'text/javascript; charset=utf-8','/view.js':'text/javascript; charset=utf-8', '/i18n.js':'text/javascript; charset=utf-8','/locales.json':'application/json; charset=utf-8', '/style.css': 'text/css; charset=utf-8'}[path])
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.trusted() or self.headers.get('X-RPG-Token') != TOKEN:
            return self.reply({'error': 'Недопустимый запрос.'}, 403)
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n < 1 or n > 32_000_000:
                raise ValueError('Размер запроса должен быть меньше 32 МБ.')
            body = json.loads(self.rfile.read(n))
            mode = body.get('mode', 'shared')
            if mode not in ('shared', 'personal'):
                raise ValueError('Неизвестный режим.')
            # Serialize mutations so a slow generation cannot overwrite a newer save.
            with LOCK:
                result = self.action(self.path, body, mode)
            self.reply(result)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            self.reply({'error': str(e)}, 400)
        except Exception:
            self.reply({'error': 'Не удалось выполнить действие. Текущая история сохранена.'}, 500)

    def action(self, path, b, mode):
        s = read_state(mode)
        if path == '/api/state':
            return {'state': s, 'profiles': public_profiles(), 'github': mode in GITHUB}
        if path == '/api/chatgpt-start':
            return chatgpt().start(PORT, b.get('profile'))
        if path == '/api/chatgpt-status':
            return chatgpt().status(b['attempt'])
        if path == '/api/chatgpt-models':
            return chatgpt().models(b['profile'])
        if path == '/api/chatgpt-model':
            chatgpt().choose_model(b['profile'],b['model'])
            return {'ok':True}
        if path == '/api/chatgpt-logout':
            return {'message':chatgpt().logout(b['profile'])}
        if path == '/api/save':
            for k in ('hero', 'memory', 'files', 'story_language'):
                if k in b:
                    s[k] = b[k]
            write_state(mode, s)
        elif path == '/api/import':
            incoming = b['state']
            validate_state(incoming)
            incoming['repo'] = None
            # Preserve a recovery copy even when explicitly replacing a local game.
            (DATA / f'backup-{mode}-{time.time_ns()}.json').write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
            write_state(mode, incoming)
        elif path == '/api/profile':
            provider = b['provider']
            if provider not in ENDPOINTS or not b.get('key', '').strip() or not b.get('model', '').strip():
                raise ValueError('Укажите провайдера, API-ключ и ID модели.')
            pid = secrets.token_hex(8)
            KEYS[pid] = {'id': pid, 'provider': provider, 'name': str(b.get('name') or provider)[:80],
                         'model': b['model'].strip(), 'key': b['key'].strip(), 'sent': 0, 'tokens': 0, 'status': 'Готов к запросу'}
        elif path == '/api/delete-profile':
            KEYS.pop(b['id'], None)
        elif path == '/api/context':
            language={'ru':'русском','uk':'украинском','en':'английском'}[s.get('story_language','ru')]
            return {'context': STARTER['instructions'] + '\nПиши следующую главу на '+language+' языке. Материалы могут быть на другом языке; не меняй их исходный текст.\n\n' + context(s,b.get('action',''))}
        elif path == '/api/chapter':
            text = b.get('text', '').strip()
            if not text:
                raise ValueError('Вставьте текст главы.')
            s['chapters'].append({'title': b.get('title') or f'Глава {len(s["chapters"]) + 1}', 'text': text,
                                  'choices': [], 'action': b.get('action', ''), 'source': 'Импорт', 'created': time.time()})
            write_state(mode, s)
        elif path == '/api/fork':
            index = int(b['index'])
            if index < 0 or index >= len(s['chapters']):
                raise ValueError('Неизвестная глава.')
            (DATA / f'branch-{mode}-{time.time_ns()}.json').write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
            s['chapters'] = s['chapters'][:index + 1]
            s['memory'] = s['chapters'][-1].get('memory', '')
            s['branch'] = f'Ветка после главы {index + 1}'
            write_state(mode, s)
        elif path == '/api/generate':
            is_chatgpt = str(b.get('profile','')).startswith('chatgpt-')
            profile = next((p for p in chatgpt().public() if p['id']==b['profile']),None) if is_chatgpt else KEYS.get(b.get('profile'))
            if not profile:
                raise ValueError('Выберите аккаунт ChatGPT или API-подключение, либо используйте перенос текста.')
            action = b.get('action', '').strip()
            if not action:
                raise ValueError('Напишите действие или выберите вариант.')
            instructions = STARTER['instructions'] + '\nОтвет верни только JSON: {"title": "Название главы", "text": "Текст главы в Markdown", "choices": ["ровно шесть вариантов"], "memory": "Полное актуальное краткое сохранение: сохрани важные прежние факты, знания, хронологию и добавь новые; отличай предложения от совершённых событий"}.'
            instructions += '\nЯзык НОВОЙ главы, вариантов и памяти: '+{'ru':'русский','uk':'українська','en':'English'}[s.get('story_language','ru')]+'. Читай русские и иноязычные материалы как данные; имена сохраняй последовательно. Оригиналы файлов не переводи и не переписывай. Извлечения с неполным покрытием не дают права утверждать, что прочитан весь источник.'
            response = chatgpt().generate(profile['id'],instructions,context(s,action)+'\n\nВыбор игрока: '+action) if is_chatgpt else remote(ENDPOINTS[profile['provider']] + '/chat/completions', profile['key'],
                {'model': profile['model'], 'messages': [{'role': 'system', 'content': instructions},
                {'role': 'user', 'content': context(s,action) + '\n\nВыбор игрока: ' + action}]})
            raw = response['choices'][0]['message']['content']
            try:
                ch = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip()))
                if not all(isinstance(ch.get(k), str) and ch[k].strip() for k in ('title', 'text', 'memory')) or not isinstance(ch.get('choices'), list) or len(ch['choices']) != 6 or any(not isinstance(x, str) for x in ch['choices']):
                    raise ValueError()
            except (ValueError, TypeError):
                profile['status'] = 'Ответ требует ручного импорта'
                return {'draft': raw, 'error': 'Модель вернула другой формат. Текст сохранён в окне для проверки; история не изменена.'}
            ch.update({'action': action, 'source': ('ChatGPT · подписка' if is_chatgpt else profile['provider']) + ' · ' + profile['model'], 'created': time.time()})
            s['chapters'].append(ch)
            s['memory'] = ch['memory']
            write_state(mode, s)
            if not is_chatgpt:
                profile['sent'] += 1
                profile['tokens'] += response.get('usage', {}).get('total_tokens', 0)
                profile['status'] = 'Последний запрос выполнен'
        elif path == '/api/quit':
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif path == '/api/github-connect':
            repo = b.get('repo', '').strip().removeprefix('https://github.com/').removesuffix('.git').strip('/')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
                raise ValueError('Репозиторий указывается как владелец/название.')
            token = b.get('token', '').strip()
            info = remote('https://api.github.com/repos/' + repo, token)
            GITHUB[mode] = token
            s['repo'] = {'name': repo, 'branch': info['default_branch']}
            write_state(mode, s)
        elif path == '/api/github-create':
            name = b.get('name', '').strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name):
                raise ValueError('Имя: латинские буквы, цифры, дефис или подчёркивание.')
            token = b.get('token', '').strip()
            repo = remote('https://api.github.com/user/repos', token, {'name': name, 'private': True, 'auto_init': True})
            GITHUB[mode] = token
            s['repo'] = {'name': repo['full_name'], 'branch': repo['default_branch']}
            write_state(mode, s)
        elif path == '/api/github-pull':
            repo, token = self.repository(s, mode)
            paths=b.get('paths',[])
            snapshot=s.get('repo_snapshot')
            if not snapshot or not paths or not isinstance(paths,list):
                raise ValueError('Сначала загрузите список файлов и выберите материалы.')
            indexed={x['path']:x for x in snapshot['files']}
            if any(not isinstance(p,str) or p not in indexed for p in paths):
                raise ValueError('Файл отсутствует в выбранном снимке репозитория. Обновите список.')
            candidates=[indexed[p] for p in dict.fromkeys(paths)]
            if sum(x.get('size',0) for x in candidates)>16000000:
                raise ValueError('Выбрано больше 16 МБ текста. Импортируйте материалы частями.')
            files = {}
            encodings={}
            for item in candidates:
                blob = remote(f'https://api.github.com/repos/{repo}/git/blobs/{item["sha"]}', token)
                files[item['path']],encodings[item['path']]=decode_text(base64.b64decode(blob['content']))
            if not files:
                raise ValueError('Нет выбранных текстовых файлов.')
            s['files'].update(files)
            s.setdefault('source_encodings',{}).update(encodings)
            write_state(mode, s)
        elif path == '/api/github-index':
            repo,token=self.repository(s,mode)
            branch=urllib.parse.quote(s['repo']['branch'],safe='')
            tree=remote(f'https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1',token)
            if tree.get('truncated'):raise ValueError('GitHub вернул неполный список. Выберите меньший репозиторий.')
            candidates=[x for x in tree['tree'] if x['type']=='blob' and x['path'].lower().endswith(('.md','.txt','.json')) and not any(p.startswith('.') for p in x['path'].split('/'))]
            s['repo_snapshot']={'tree_sha':tree['sha'],'files':[{k:x[k] for k in ('path','sha','size')} for x in candidates]}
            write_state(mode,s)
            return {'files':s['repo_snapshot']['files'],'snapshot':tree['sha']}
        elif path == '/api/new-game':
            if mode!='shared':raise ValueError('Личное прохождение не сбрасывается этим действием.')
            (DATA/f'backup-{mode}-{time.time_ns()}.json').write_text(json.dumps(s,ensure_ascii=False),encoding='utf-8')
            fresh=initial(mode)
            fresh.update(hero=s['hero'],story_language=s.get('story_language','ru'),repo=s.get('repo'))
            write_state(mode,fresh)
        elif path == '/api/github-push':
            repo, token = self.repository(s, mode)
            name = f'hogwarts-local/{mode}/save.json'
            url = f'https://api.github.com/repos/{repo}/contents/{name}'
            old = None
            try:
                old = remote(url + '?ref=' + urllib.parse.quote(s['repo']['branch'], safe=''), token)
            except ValueError as e:
                if '404' not in str(e):
                    raise
            payload = {'message': 'Save local RPG progress', 'branch': s['repo']['branch'],
                       'content': base64.b64encode(json.dumps(s, ensure_ascii=False, indent=2).encode()).decode()}
            if old:
                payload['sha'] = old['sha']
            remote(url, token, payload, 'PUT')
        elif path == '/api/github-restore':
            repo, token = self.repository(s, mode)
            file = remote(f'https://api.github.com/repos/{repo}/contents/hogwarts-local/{mode}/save.json?ref=' + urllib.parse.quote(s['repo']['branch'], safe=''), token)
            restored = json.loads(base64.b64decode(file['content']))
            validate_state(restored)
            (DATA / f'backup-{mode}-{time.time_ns()}.json').write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
            restored['repo'] = s['repo']
            write_state(mode, restored)
        else:
            raise ValueError('Неизвестная операция.')
        return {'ok': True, 'state': read_state(mode), 'profiles': public_profiles(), 'github': mode in GITHUB}

    def repository(self, s, mode):
        if not s.get('repo') or mode not in GITHUB:
            raise ValueError('Подключите GitHub. После перезапуска токен нужно ввести заново.')
        return s['repo']['name'], GITHUB[mode]

if __name__ == '__main__':
    print(f'Hogwarts Local: http://127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
