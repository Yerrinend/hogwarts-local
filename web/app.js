'use strict';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token, state, profiles=[], selected=sessionStorage.getItem('profile'), provider='all', page='game', chapterIndex=null, github=false, busy=false;
let mode = new URLSearchParams(location.search).get('mode') === 'personal' ? 'personal' : 'shared';
$('#mode').value=mode;
const modeName = () => mode==='personal' ? 'Личное прохождение' : 'Новое прохождение';
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('visible'),6500);}
async function api(path, body={}){
  const res=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-RPG-Token':token},body:JSON.stringify({mode,ui_language:window.RPGI18n?.language||'ru',...body})});
  const data=await res.json();
  if(data.draft){ draftModal(data.draft);throw Error(data.error); }
  if(!res.ok || data.error)throw Error(data.error || 'Не удалось выполнить запрос.');
  return data;
}
async function refresh(){const draft=$('#action')?.value;const data=await api('state');state=data.state;profiles=data.profiles;github=data.github;render();if(draft&&$('#action'))$('#action').value=draft;}
async function run(fn){if(busy)return;busy=true;document.body.setAttribute('aria-busy','true');$$('button[type=submit],#generate').forEach(x=>x.disabled=true);try{await fn();}catch(e){toast(e.message);$('#save-status').textContent='Действие не завершено — проверь сообщение';}finally{busy=false;document.body.removeAttribute('aria-busy');$$('button[type=submit],#generate').forEach(x=>x.disabled=false);}}
function download(name,text,type='application/json'){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function inline(s){return esc(s).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g,'$1<em>$2</em>').replace(/`([^`]+)`/g,'<code>$1</code>');}
function markdown(text){
  const lines=String(text).split('\n');let out='',table=false,list=false,code=false;
  for(let i=0;i<lines.length;i++){
    const line=lines[i];
    if(line.startsWith('```')){if(table){out+='</tbody></table>';table=false;}if(list){out+='</ul>';list=false;}out+=code?'</pre>':'<pre>';code=!code;continue;}
    if(code){out+=esc(line)+'\n';continue;}
    if(line.trim().startsWith('|')){if(!table){out+='<table><tbody>';table=true;}if(/^\s*\|?[\s:|-]+\|\s*$/.test(line))continue;const tag=lines[i+1]&&/^\s*\|?[\s:|-]+\|\s*$/.test(lines[i+1])?'th':'td';out+='<tr>'+line.trim().replace(/^\||\|$/g,'').split('|').map(x=>`<${tag}>${inline(x.trim())}</${tag}>`).join('')+'</tr>';continue;}
    if(table){out+='</tbody></table>';table=false;}
    if(/^[-*] /.test(line)){if(!list){out+='<ul>';list=true;}out+='<li>'+inline(line.slice(2))+'</li>';continue;}
    if(list){out+='</ul>';list=false;}
    const h=line.match(/^(#{1,3}) (.+)/);if(h){out+=`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`;continue;}
    if(line.startsWith('> ')){out+='<blockquote>'+inline(line.slice(2))+'</blockquote>';continue;}
    if(line.trim())out+='<p>'+inline(line)+'</p>';
  }
  return out+(table?'</tbody></table>':'')+(list?'</ul>':'')+(code?'</pre>':'');
}
function render(){
  $('#breadcrumb').textContent=(page==='game'?'ИГРА':({archive:'АРХИВ ГЛАВ',characters:'ПЕРСОНАЖИ',timeline:'ХРОНОЛОГИЯ',repository:'РЕПОЗИТОРИЙ'}[page]||'МАТЕРИАЛЫ'))+' / '+modeName().toUpperCase();
  $('#chapter-count').textContent=state.chapters.length;
  $('#hero-label').textContent='Герой: '+state.hero+' Поттер';
  $('#save-title').textContent=state.chapters.length?'Глава '+state.chapters.length:'Новая история';
  $('#save-branch').textContent=state.branch || 'Основная история';
  $('#repo-status').innerHTML=`<span class="${github?'live-dot':'muted-dot'}"></span> ${esc(state.repo?.name || 'Не подключён')}`;
  $('#repo-branch').textContent=state.repo ? state.repo.branch+(github?'':' · нужен токен') : 'Локальное сохранение';
  $('#connect-repo').textContent=github?'Открыть репозиторий →':'Подключить GitHub ↗';
  $('#file-links').innerHTML=Object.keys(state.files).slice(0,3).map(name=>`<button class="file-link" data-file="${esc(name)}">▧ ${esc(name)}</button>`).join('');
  $$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===page));
  renderProfiles();renderPage();
}
function renderProfiles(){
  const query=$('#profile-search').value.toLowerCase();
  const list=profiles.filter(p=>(provider==='all'||p.provider===provider)&&(p.name+' '+p.model).toLowerCase().includes(query));
  if(!profiles.some(p=>p.id===selected)){selected=profiles[0]?.id || null;sessionStorage.setItem('profile',selected||'');}
  $('#profiles').innerHTML=list.length?list.map(p=>`<div class="profile ${p.id===selected?'active':''}" data-profile="${p.id}" role="button" tabindex="0" aria-pressed="${p.id===selected}">${p.kind==='chatgpt'?'':`<button class="delete-profile" data-delete="${p.id}" aria-label="Удалить ${esc(p.name)}">×</button>`}<div class="profile-name"><span class="provider-icon">${p.provider==='Grok'?'𝕏':'✺'}</span><div><span data-source>${esc(p.name)}${p.kind==='chatgpt'?` · ${esc(p.label)}`:''}</span><div class="model-id"><span>${p.kind==='chatgpt'?'Подписка ChatGPT · ':'API · '} </span><span data-source>${esc(p.model||'—')}</span></div></div></div><small>${p.id===selected?'<span>● Выбрано · </span>':''}<span>${esc(p.status)}</span></small><div class="usage-meter"></div><div class="usage-line"><span>Запросов: ${p.sent}</span><span>Токенов: ${p.tokens.toLocaleString('ru')}</span></div><small>${p.kind==='chatgpt'?'Лимиты — в настройках ChatGPT':'Остаток лимита неизвестен'}</small>${p.kind==='chatgpt'?`<div class="account-actions"><button data-models="${p.id}">Модель</button><button data-login="${p.id}">${p.connected?'Повторить вход':'Войти'}</button>${p.connected?`<button data-logout="${p.id}">Выйти</button>`:''}</div>`:''}</div>`).join(''):`<div class="empty-profiles"><div class="star">✧</div><p>${profiles.length?'Ничего не найдено':'Выбери своего рассказчика'}</p><small>${profiles.length?'Измени фильтр или поиск.':'Войди через ChatGPT с подпиской.<br>Или добавь API-подключение.'}</small></div>`;
}
function renderPage(){
  if(page==='game')return renderGame();
  if(page==='archive'){
    $('#page').innerHTML='<div class="ornament">✦</div><h1 class="section-title">Архив твоей истории</h1><div class="archive-toolbar"><input id="archive-search" placeholder="Поиск по названию или тексту…" aria-label="Поиск глав"><button class="secondary" id="import-chapter">＋ Добавить главу</button></div><div id="archive-list"></div>';
    renderArchive();return;
  }
  if(page==='repository'){
    $('#page').innerHTML=`<div class="ornament">✦</div><h1 class="section-title">Материалы и репозиторий</h1><p class="page-note">${esc(state.repo?.name || 'GitHub ещё не подключён. Материалы игры доступны локально.')}</p><div class="actions-row"><button class="primary" id="github-dialog">Подключить GitHub</button><button class="secondary" id="github-pull">Загрузить .md</button><button class="secondary" id="github-push">Сохранить в GitHub</button><button class="secondary" id="github-restore">Восстановить</button></div><p class="warning">Исходные тексты сохраняют язык и кодировку. Для генерации на другом языке выбери язык новых глав в настройках.</p>${mode==='shared'?'<button class="secondary" id="new-world">Новая игра с обновлённым миром</button>':''}<div class="actions-row"><button class="secondary" id="import-files">Добавить .md файлы</button><button class="secondary" id="import-save">Импорт сохранения JSON</button></div><div class="file-list">${Object.keys(state.files).map(f=>`<button data-file="${esc(f)}">▧ ${esc(f)} <span>→</span></button>`).join('')}</div>`;return;
  }
  const file=page==='characters'?'character_profiles.md':page==='timeline'?'full_timeline.md':page.slice(5);
  $('#page').innerHTML=`<div class="ornament">✦</div><h1 class="section-title file-heading">${esc(file)}</h1><div class="actions-row"><button class="secondary" id="edit-file" data-edit="${esc(file)}">Редактировать материал</button></div><div class="story">${markdown(state.files[file]||'Материал пока не заполнен.')}</div>${page==='timeline'?'<h2 class="section-title">Актуальное сохранение</h2><div class="story">'+markdown(state.memory||'Появится после первой главы.')+'</div>':''}`;
}
function renderArchive(){
  const q=($('#archive-search')?.value||'').toLowerCase();
  $('#archive-list').innerHTML=state.chapters.map((ch,i)=>({ch,i})).filter(({ch})=>(ch.title+' '+ch.text).toLowerCase().includes(q)).map(({ch,i})=>`<button class="archive-item" data-chapter="${i}"><strong>${i+1}. ${esc(ch.title)}</strong><small>${esc(ch.source||'Импорт')} · ${esc(ch.action||'Начало сцены')}</small></button>`).join('')||'<p class="page-note">Здесь появятся главы твоего прохождения.</p>';
}
function renderGame(){
  const index=chapterIndex===null?state.chapters.length-1:chapterIndex;
  const ch=state.chapters[index];
  if(!ch){
    $('#page').innerHTML=`<div><span class="paper-tag">✧ Стартовый пакет включён</span><span class="paper-tag">▧ История ещё не началась</span></div><div class="chapter-head"><div class="ornament">— ✦ —</div><div class="eyebrow">${mode==='personal'?'ТВОЁ ЛИЧНОЕ ПРОХОЖДЕНИЕ':'НОВОЕ ПУТЕШЕСТВИЕ'}</div><h1>У каждой истории<br>есть начало</h1><h2>Следующую страницу напишешь ты.</h2></div><div class="welcome-emblem">♜</div><p class="intro-copy">${mode==='personal'?'Импортируй свои главы и сохранение, чтобы продолжить с того места, где остановился. Личная история не входит в распространяемый комплект.':'Письмо ещё не пришло. За окном — обычное утро на Тисовой улице. Но скоро привычный мир изменится навсегда.'}</p><form id="start-game" class="setup-form"><label for="hero">Имя главного героя</label><input id="hero" maxlength="80" required value="${esc(state.hero)}"><label for="start-story-language">Язык новых глав</label><select id="start-story-language">${languageOptions(state.story_language||'ru')}</select><button class="primary" type="submit">${mode==='personal'?'Сохранить имя героя':'Начать историю'} <span>→</span></button></form><div class="setup-actions"><button class="text-button" id="import-save">↑ Импорт сохранения</button><button class="text-button" id="import-chapter">＋ Вставить главу</button><button class="text-button" id="import-files">▧ Добавить материалы</button></div><div class="setup-note">${mode==='personal'?'Твоё прохождение не загружено. Подключи репозиторий и импортируй актуальные материалы. Номера глав и факты не выдумываются.':'В комплекте — авторский мир, персонажи и семь сюжетных лет. События личного прохождения не перенесены.'}</div><div class="paper-hint">Для генерации войди через ChatGPT или добавь API-ключ. Также доступен перенос в другой чат.</div>`;return;
  }
  const historical=index!==state.chapters.length-1;
  $('#page').innerHTML=`<div><span class="paper-tag">▧ Сохранено локально</span><span class="paper-tag">${esc(ch.source||'Импорт')}</span></div><div class="chapter-head"><div class="ornament">— ✦ —</div><div class="eyebrow">${esc(state.branch||'Основная история')}</div><h1>Глава ${index+1}</h1>${window.RPGView.chapterTitle(ch.title,index+1)?`<h2>${esc(window.RPGView.chapterTitle(ch.title,index+1))}</h2>`:''}<div class="meta"><span data-source>${esc(state.hero)} Поттер</span> · <span>${historical?'Страница из архива':'Текущая сцена'}</span></div></div>${historical?'':'<button id="jump-actions" class="reader-jump">К выбору ↓</button>'}${window.RPGView.chapterBody(ch.text,markdown)}<div class="ornament centered">— ✦ —</div>${historical?'<div class="setup-note">Это прошлая глава. Для другого выбора создай ветку; исходная история сохранится в резервной копии.</div><div class="actions-row"><button id="fork" class="primary" data-index="'+index+'">Создать ветку отсюда</button><button id="latest" class="secondary">К текущей главе</button></div>':`<div class="choice-grid">${(ch.choices||[]).map((c,i)=>`<button class="choice" data-choice="${esc(c)}"><span>${i+1}</span>${esc(c)}</button>`).join('')}</div><form class="composer" id="continue-form"><textarea id="action" placeholder="Твой ответ или действие…" aria-label="Твоё действие" required></textarea><button id="generate" class="primary" type="submit">Продолжить главу →</button></form><div class="paper-hint">Важные решения остаются за тобой. Продолжение отправится выбранной модели.</div>`}<div class="chapter-tools"><button id="import-chapter" class="text-button">＋ Вставить ответ из другого чата</button><button id="edit-memory-inline" class="text-button">Проверить сохранение</button></div>`;
}
let submitModal=null;
function modal(title,html,button,onSubmit){$('#modal-title').textContent=title;$('#modal-body').innerHTML=html;$('#modal-submit').textContent=button;$('#modal-status').textContent='';submitModal=onSubmit;if(!$('#modal').open)$('#modal').showModal();}
function profileModal(){modal('Новое API-подключение',`<p>Для ChatGPT с подпиской используй отдельную кнопку Continue with ChatGPT. Grok здесь подключается только через платный API; его подписка API не оплачивает. Укажи API-ключ и точный ID модели из своего кабинета. Ключ хранится только в памяти локального сервера.</p><label>Название</label><input name="name" required placeholder="Например: Grok — основной"><label>Провайдер</label><select name="provider"><option>OpenAI</option><option>Grok</option></select><label>ID модели</label><input name="model" required placeholder="Точный ID из кабинета провайдера"><label>API-ключ</label><input name="key" type="password" required autocomplete="off" placeholder="Вставь ключ">`,'Добавить',async data=>{await api('profile',data);await refresh();});}
function githubModal(){modal('Подключить GitHub',`<p>Для этой локальной версии используется персональный токен GitHub. Для существующего репозитория достаточно доступа Contents: read/write только к нему. Создание нового требует права создания репозиториев. Токен действует до закрытия приложения и не записывается в сохранение.</p><label>Действие</label><select name="operation"><option value="connect">Подключить существующий</option><option value="create">Создать новый приватный репозиторий</option></select><label>Владелец/репозиторий либо имя нового</label><input name="repo" required value="${esc(state.repo?.name||'')}" placeholder="username/my-hogwarts"><label>GitHub token</label><input name="token" type="password" required autocomplete="off"><p>В выбранный репозиторий будут отправляться только материалы и история текущего режима. API-ключи исключены.</p>`,'Подключить',async d=>{await api(d.operation==='create'?'github-create':'github-connect',{...d,name:d.repo});await refresh();});}
function memoryModal(){modal('Краткое сохранение',`<p>Перед переходом между моделями проверь время, место, отношения, знания и незавершённые события. Последние восемь глав передаются целиком; более ранние события должны быть отражены здесь.</p><textarea name="memory" aria-label="Краткое сохранение">${esc(state.memory||state.files['quick_save.md']||'')}</textarea>`,'Сохранить',async d=>{await api('save',d);await refresh();});}
function draftModal(text=''){modal('Вставить главу',`<p>Вставь ответ из другого чата. Проверь факты и затем обнови краткое сохранение. Текст не выполняется как HTML.</p><label>Название главы</label><input name="title" placeholder="Название сцены"><label>Текст главы</label><textarea name="text" required>${esc(text)}</textarea><label>Твой предшествующий выбор</label><input name="action">`,'Добавить главу',async d=>{await api('chapter',d);page='game';chapterIndex=null;await refresh();});}
async function contextModal(){const result=await api('context',{action:$('#action')?.value||''});modal('Пакет для продолжения',`<p>Этот пакет содержит материалы текущего прохождения. Отправь его в выбранный чат, добавь своё действие, а ответ верни через «Вставить главу». Ключи в пакет не включены.</p><textarea name="packet" readonly aria-label="Пакет контекста">${esc(result.context)}</textarea>`,'Скачать .txt',async d=>download('hogwarts-context.txt',d.packet,'text/plain'));}
function fileModal(name){modal('Редактировать материал',`<p>${esc(name)}</p><textarea name="content" data-source aria-label="Текст материала">${esc(state.files[name]||'')}</textarea>`,'Сохранить',async d=>{await api('save',{files:{...state.files,[name]:d.content}});await refresh();});}
function chooseFiles(accept,multiple,fn){const input=document.createElement('input');input.type='file';input.accept=accept;input.multiple=multiple;input.onchange=()=>run(()=>fn([...input.files]));input.click();}
async function importSave(){chooseFiles('.json',false,async files=>{const incoming=JSON.parse(await files[0].text());modal('Заменить текущее прохождение?',`<p>Импорт: ${esc(incoming.hero||'Без имени')}, глав: ${incoming.chapters?.length??'неизвестно'}. Текущее прохождение будет заменено; резервная копия останется на компьютере.</p>`,'Импортировать',async()=>{await api('import',{state:incoming});chapterIndex=null;page='game';await refresh();});});}
function importFiles(){chooseFiles('.md,.txt,.json',true,async files=>{const next={...state.files};for(const f of files){if(f.size>2000000)throw Error('Файл больше 2 МБ: '+f.name);const bytes=await f.arrayBuffer();try{next[f.name]=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch(e){next[f.name]=new TextDecoder('windows-1251',{fatal:true}).decode(bytes);}}await api('save',{files:next});await refresh();toast('Материалы добавлены. Проверь их в разделе «Репозиторий».');});}
function confirmAction(title,text,button,fn){modal(title,`<p>${esc(text)}</p>`,button,fn);}
document.addEventListener('click',e=>{
  const el=e.target.closest('button,[data-profile]');if(!el)return;
  if(el.dataset.page){page=el.dataset.page;render();return;}
  if(el.dataset.file){const name=el.dataset.file;if(name.startsWith('gm_')){confirmAction('Материал ведущего: спойлеры','Этот файл содержит будущие события и тайны мира. Открыть его вне роли персонажа?','Открыть материал',async()=>{page='file:'+name;render();});}else{page='file:'+name;render();}return;}
  if(el.dataset.edit){fileModal(el.dataset.edit);return;}
  if(el.dataset.delete){run(async()=>{await api('delete-profile',{id:el.dataset.delete});await refresh();});return;}
  if(el.dataset.models){run(()=>modelModal(el.dataset.models));return;}
  if(el.dataset.login){signInModal(el.dataset.login);return;}
  if(el.dataset.logout){confirmAction('Выйти из ChatGPT?','Сессия будет отозвана, локальные токены удалены. Регистрация и история игры сохранятся.','Выйти',async()=>{const r=await api('chatgpt-logout',{profile:el.dataset.logout});await refresh();toast(r.message);});return;}
  if(el.dataset.profile){selected=el.dataset.profile;sessionStorage.setItem('profile',selected);renderProfiles();return;}
  if(el.dataset.provider){provider=el.dataset.provider;$$('[data-provider]').forEach(x=>x.classList.toggle('selected',x===el));renderProfiles();return;}
  if(el.dataset.choice){$('#action').value=el.dataset.choice;$$('.choice').forEach(x=>x.classList.toggle('chosen',x===el));$('#action').focus();return;}
  if(el.dataset.chapter!==undefined){chapterIndex=Number(el.dataset.chapter);page='game';render();return;}
  const id=el.id;
  if(id==='models-toggle')setModelsPanel(!$('#models-panel').classList.contains('panel-open'));
  if(id==='close-models'||id==='models-scrim')setModelsPanel(false);
  if(id==='jump-actions')($('.choice-grid')||$('#continue-form'))?.scrollIntoView({behavior:'smooth',block:'center'});
  if(id==='new-world')confirmAction('Начать новое прохождение?','Текущая новая игра будет сохранена в резервной копии. Герой и язык сохранятся, события начнутся заново. Личное прохождение не изменится.','Начать заново',async()=>{await api('new-game');chapterIndex=null;page='game';await refresh();});
  if(id==='chatgpt-signin')signInModal();
  if(id==='begin-chatgpt-login')run(()=>beginSignIn(el.dataset.account||null));
  if(id==='add-profile'||id==='add-profile-bottom')profileModal();
  if(id==='connect-repo'){if(github){page='repository';render();}else githubModal();}
  if(id==='github-dialog')githubModal();
  if(id==='context')run(contextModal);
  if(id==='edit-memory'||id==='edit-memory-inline')memoryModal();
  if(id==='close-modal')$('#modal').close();
  if(id==='export')download('hogwarts-'+mode+'-'+new Date().toISOString().slice(0,10)+'.json',JSON.stringify(state,null,2));
  if(id==='import-chapter')draftModal();
  if(id==='import-save')importSave();
  if(id==='import-files')importFiles();
  if(id==='latest'){chapterIndex=null;render();}
  if(id==='fork')confirmAction('Создать альтернативную ветку?','Последующие главы останутся в резервной копии. Экспортируй исходное прохождение, чтобы легко вернуться к нему. Краткое сохранение будет восстановлено на момент выбранной главы.','Создать ветку',async()=>{await api('fork',{index:Number(el.dataset.index)});chapterIndex=null;await refresh();});
  if(id==='github-push')confirmAction('Сохранить в GitHub?','Материалы и история текущего режима будут записаны в выбранный репозиторий. Проверь, что он приватный, если это личная история.','Отправить',async()=>{await api('github-push');toast('Сохранение отправлено в GitHub.');});
  if(id==='github-pull')run(repositoryFilesModal);
  if(id==='github-restore')confirmAction('Восстановить из GitHub?','Локальная история будет заменена сохранением текущего режима из GitHub. Перед заменой создаётся резервная копия.','Восстановить',async()=>{await api('github-restore');chapterIndex=null;await refresh();});
  if(id==='quit')confirmAction('Завершить приложение?','Глава и сохранение останутся на компьютере. Ключи будут удалены из памяти при закрытии процесса.','Завершить',async()=>{await api('quit');$('#save-status').textContent='Приложение остановлено';});
  if(id==='settings')modal('Настройки прохождения',`<label>Имя героя</label><input name="hero" required maxlength="80" value="${esc(state.hero)}"><label>Язык новых глав</label><select name="story_language">${languageOptions(state.story_language||'ru')}</select><p>Язык интерфейса не меняет исходные файлы и уже написанные главы.</p><p>Имя и язык применяются к новым главам. Написанные главы сохраняются без изменений. Личное и новое прохождения сохраняются отдельно.</p><button type="button" id="quit" class="ghost">Завершить приложение</button>`,'Сохранить',async d=>{await api('save',d);await refresh();});
});
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-profile]')){e.preventDefault();e.target.click();}});
document.addEventListener('input',e=>{if(e.target.id==='profile-search')renderProfiles();if(e.target.id==='archive-search')renderArchive();});
$('#mode').onchange=()=>run(async()=>{if($('#action'))$('#action').value='';mode=$('#mode').value;history.replaceState(null,'','?mode='+mode);chapterIndex=null;page='game';await refresh();});
$('#modal-form').onsubmit=e=>{e.preventDefault();run(async()=>{const fn=submitModal;await fn(Object.fromEntries(new FormData(e.target)));$('#modal').close();toast('Готово.');});};
document.addEventListener('submit',e=>{
  if(e.target.id==='start-game'){e.preventDefault();run(async()=>{await api('save',{hero:$('#hero').value.trim(),story_language:$('#start-story-language').value});await refresh();if(mode==='personal'){toast('Имя сохранено. Теперь импортируй своё прохождение.');return;}if(!selected){toast('Для первой главы войди через ChatGPT, добавь API-ключ или подготовь пакет для другого чата.');return;}$('#save-status').textContent='Рассказчик готовит первую главу…';await api('generate',{profile:selected,action:'Начать новую игру по стартовому сохранению. Короткая первая сцена, остановка перед выбором героя.'});await refresh();});}
  if(e.target.id==='continue-form'){e.preventDefault();const action=$('#action').value;run(async()=>{$('#save-status').textContent='Рассказчик пишет главу…';await api('generate',{profile:selected,action});if($('#action'))$('#action').value='';chapterIndex=null;await refresh();$('#save-status').textContent='Глава сохранена на компьютере';});}
});
(async()=>{try{const r=await fetch('/api/bootstrap');const data=await r.json();token=data.token;await refresh();}catch(e){$('#page').innerHTML='<h1 class="section-title">Нет соединения</h1><p class="page-note">Запусти приложение через EXE или start.bat и обнови страницу.</p>';}})();

let authPoll=null;
function signInModal(profile=null){
  const name=profiles.find(p=>p.id===profile)?.name;
  modal(name?'Войти снова: '+name:'Вход через ChatGPT',`<p>Вход откроется на официальном сайте OpenAI в системном браузере. Пароль вводится только там. Разреши приложению использовать подписку, если хочешь генерировать главы без API-ключа.</p><p>Запросы используют доступный объём подписки. Дополнительные кредиты и разрешение их расходования управляются в ChatGPT. Для работы только в рамках включённого объёма отключи использование кредитов для приложения.</p><p>Сессия сохраняется локально, зашифрованная для твоего пользователя Windows. Игровые сохранения и GitHub её не содержат.</p><a class="external-link" href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">Настройки использования и кредитов ↗</a><button type="button" id="begin-chatgpt-login" data-account="${esc(profile||'')}" class="chatgpt-signin">Continue with ChatGPT</button>`, 'Закрыть',async()=>{});
}
async function beginSignIn(profile){
  if(authPoll)clearTimeout(authPoll);
  $('#modal-status').textContent='Заверши вход в открывшемся браузере…';
  const result=await api('chatgpt-start',{profile});
  const poll=async()=>{
    try{
      const resultStatus=await api('chatgpt-status',{attempt:result.attempt});
      if(resultStatus.status==='pending'){authPoll=setTimeout(poll,2000);return;}
      if(resultStatus.status==='error')throw Error(resultStatus.message);
      selected=resultStatus.result;sessionStorage.setItem('profile',selected);
      await refresh();
      toast(resultStatus.message);
      const account=profiles.find(p=>p.id===selected);
      if(account?.sharing)await modelModal(selected);
      else {$('#modal').close();toast('Вход выполнен без доступа к подписке. Нажми «Повторить вход» и разреши использование подписки.');}
    }catch(e){if($('#modal').open)$('#modal-status').textContent=e.message;toast(e.message);}
  };
  authPoll=setTimeout(poll,1200);
}
async function modelModal(profile){
  const result=await api('chatgpt-models',{profile});
  await refresh();
  if(!result.models.length)throw Error('Для аккаунта не получено доступных моделей. Проверь доступ к подписке.');
  modal('Модель из твоей подписки',`<p>Список загружен для выбранного аккаунта ChatGPT. Доступность моделей и лимиты определяет OpenAI.</p><label>Модель</label><select name="model">${result.models.map(m=>`<option value="${esc(m.slug)}" ${m.slug===result.selected?'selected':''}>${esc(m.name)}</option>`).join('')}</select><p>Остаток сообщений не рассчитывается из числа запросов: смотри использование в настройках ChatGPT.</p><a class="external-link" href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">Посмотреть лимиты ↗</a>`,'Выбрать',async d=>{await api('chatgpt-model',{profile,model:d.model});selected=profile;sessionStorage.setItem('profile',profile);await refresh();});
}

function languageOptions(current){return [['ru','Русский'],['uk','Українська'],['en','English']].map(([id,name])=>`<option value="${id}" ${id===current?'selected':''}>${name}</option>`).join('');}
let repositorySelection=new Set();
let repositoryIndex=[];
async function repositoryFilesModal(){
  toast('Загружаю список файлов…');
  const result=await api('github-index');repositoryIndex=result.files;repositorySelection=new Set();
  modal('Выбор файлов репозитория',`<p>Выбери нужные исходные материалы. Личные главы, текущие отношения и сохранения не нужны для новой игры. Пути и русские имена сохраняются.</p><input id="repo-file-search" placeholder="Поиск файлов…" aria-label="Поиск файлов…"><div class="repo-selection-actions"><button type="button" id="select-visible-files" class="ghost">Отметить видимые</button><button type="button" id="clear-repo-selection" class="ghost">Снять выбор</button></div><div id="repository-file-list"></div><p id="repository-selection-count">Выбрано файлов: 0</p>`,'Загрузить выбранные',async()=>{
    if(!repositorySelection.size)throw Error('Выбери хотя бы один файл.');
    await api('github-pull',{paths:[...repositorySelection]});await refresh();
  });
  renderRepositoryFiles();
}
function visibleRepositoryFiles(){const q=($('#repo-file-search')?.value||'').toLocaleLowerCase();return repositoryIndex.filter(f=>f.path.toLocaleLowerCase().includes(q));}
function renderRepositoryFiles(){
  $('#repository-file-list').innerHTML=visibleRepositoryFiles().map(f=>`<label class="repo-select-row"><input type="checkbox" data-repo-file="${esc(f.path)}" ${repositorySelection.has(f.path)?'checked':''}><span data-source>${esc(f.path)}</span><small>${Math.ceil(f.size/1024)} KB</small></label>`).join('');
  $('#repository-selection-count').textContent='Выбрано файлов: '+repositorySelection.size;
}
document.addEventListener('input',event=>{if(event.target.id==='repo-file-search')renderRepositoryFiles();});
document.addEventListener('change',event=>{if(event.target.dataset.repoFile){const path=event.target.dataset.repoFile;if(event.target.checked)repositorySelection.add(path);else repositorySelection.delete(path);$('#repository-selection-count').textContent='Выбрано файлов: '+repositorySelection.size;}});
document.addEventListener('click',event=>{const el=event.target.closest('button');if(el?.id==='select-visible-files'){visibleRepositoryFiles().forEach(f=>repositorySelection.add(f.path));renderRepositoryFiles();}if(el?.id==='clear-repo-selection'){repositorySelection.clear();renderRepositoryFiles();}});

function setModelsPanel(open){
  $('#models-panel').classList.toggle('panel-open',open);
  $('#models-scrim').hidden=!open;
  $('#models-toggle').setAttribute('aria-expanded',String(open));
  document.body.classList.toggle('models-open',open);
  if(open)$('#close-models').focus();else $('#models-toggle').focus();
}
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('#modal').open&&$('#models-panel').classList.contains('panel-open'))setModelsPanel(false);});
window.addEventListener('resize',()=>{if(window.innerWidth>1160&&$('#models-panel').classList.contains('panel-open'))setModelsPanel(false);});
