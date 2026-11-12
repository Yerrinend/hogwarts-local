"""Bounded, traceable retrieval from UTF-8 world files; originals are untouched."""
import json
import re

LIMIT = 180000
CORE = ('canon_and_pacing_priority', 'game_rules', 'world', 'character_profiles', 'character_canon',
        'quick_save', 'правила', 'персонаж', 'мир', 'канон')

def words(value):
    return {x.casefold() for x in re.findall(r'[^\W_]+',value, re.UNICODE) if len(x)>2}

def build(s, query=''):
    base={'hero':s['hero'],'branch':s.get('branch'),'story_language':s.get('story_language','ru'),
          'current_memory':s['memory'],'recent_chapters':s['chapters'][-8:],
          'total_chapters':len(s['chapters']), 'source_files':list(s['files'])}
    used=len(json.dumps(base,ensure_ascii=False,indent=2))
    if used>LIMIT-12000:
        raise ValueError('Сохранение и последние главы превышают объём контекста. Сократи краткое сохранение или размер последних сцен; файлы не изменены.')
    budget=LIMIT-used-5000
    query_words=words(query+' '+s['memory'][-10000:]+' '+(s['chapters'][-1]['text'][-8000:] if s['chapters'] else ''))
    candidates=[]
    for path,text in s['files'].items():
        filename=path.rsplit('/',1)[-1].casefold()
        priority=any(x in filename for x in CORE)
        parts=re.split(r'(?=^#{1,3} )',text,flags=re.M)
        for i,part in enumerate(parts):
            if not part.strip():continue
            sections=[part[j:j+14000] for j in range(0,len(part),14000)]
            for j,section in enumerate(sections):
                score=len(query_words & words(section))+len(query_words & words(path))*4+(8 if priority else 0)
                candidates.append((score,path,i,j,section))
    candidates.sort(key=lambda x:(-x[0],x[1],x[2],x[3]))
    selected={};count={}
    for score,path,i,j,section in candidates:
        cost=len(section)+len(path)+150
        # Keep space for varied sources rather than allowing one append-only file to fill everything.
        if cost>budget or count.get(path,0)+len(section)>50000:continue
        selected.setdefault(path,[]).append({'section':i+1,'part':j+1,'text':section})
        count[path]=count.get(path,0)+len(section);budget-=cost
    base['world_excerpts']=selected
    base['retrieval']={'method':'Relevant sections + priority rules; NOT a claim that the model read every source.',
                       'fully_included':[p for p,t in s['files'].items() if count.get(p,0)==len(t)],
                       'partly_included':[p for p in selected if count[p]<len(s['files'][p])],
                       'omitted':[p for p in s['files'] if p not in selected]}
    result=json.dumps(base,ensure_ascii=False,indent=2)
    if len(result)>LIMIT:raise ValueError('Контекст слишком большой. Сократи материалы или сохранение.')
    return result

def decode_text(data):
    if b'\x00' in data:raise ValueError('Файл похож на двоичный. Нужен текст UTF-8 или Windows-1251.')
    try:return data.decode('utf-8-sig'),'UTF-8'
    except UnicodeDecodeError:
        try:return data.decode('cp1251'),'Windows-1251'
        except UnicodeDecodeError:raise ValueError('Не удалось распознать кодировку файла.') from None
