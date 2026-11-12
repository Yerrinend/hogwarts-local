'use strict';
// Only app-owned UI text is translated. Chapters, source files and input values stay intact.
window.RPGI18n=(()=>{
  let lang=localStorage.getItem('ui_language')||'ru';
  if(!['ru','uk','en'].includes(lang))lang='ru';
  let dictionary={},observer;
  const originals=new WeakMap();
  const excluded='.story,.choice-grid,.file-editor,textarea,pre,code,.archive-item,.chapter-head h2,[data-source]';
  function translate(source){
    const key=source.trim();if(lang==='ru')return source;
    const hit=dictionary[key]?.[lang];
    if(hit)return source.replace(key,hit);
    const decorated=key.match(/^([^\p{L}\p{N}]+)(.+)$/u);
    if(decorated&&dictionary[decorated[2]]?.[lang])return source.replace(key,decorated[1]+dictionary[decorated[2]][lang]);
    const patterns=[
      [/^Глава (\d+)$/,(m,n)=>lang==='en'?`Chapter ${n}`:`Розділ ${n}`],
      [/^Ветка после главы (\d+)$/,(m,n)=>lang==='en'?`Branch after chapter ${n}`:`Гілка після розділу ${n}`],
      [/^Запросов: ([\d\s]+)$/,(m,n)=>lang==='en'?`Requests: ${n}`:`Запитів: ${n}`],
      [/^Токенов: ([\d\s]+)$/,(m,n)=>lang==='en'?`Tokens: ${n}`:`Токенів: ${n}`],
      [/^Герой: (.+)$/,(m,n)=>lang==='en'?`Hero: ${n}`:`Герой: ${n}`],
      [/^Войти снова: (.+)$/,(m,n)=>lang==='en'?`Sign in again: ${n}`:`Увійти знову: ${n}`],
      [/^ChatGPT · подписка · (.+)$/,(m,n)=>lang==='en'?`ChatGPT · plan · ${n}`:`ChatGPT · передплата · ${n}`],
      [/^Файл больше 2 МБ: (.+)$/,(m,n)=>lang==='en'?`File exceeds 2 MB: ${n}`:`Файл більший за 2 МБ: ${n}`],
      [/^Выбрано файлов: (\d+)$/,(m,n)=>lang==='en'?`Selected files: ${n}`:`Вибрано файлів: ${n}`]
    ];
    for(const [pattern,fn] of patterns)if(pattern.test(key))return source.replace(key,key.replace(pattern,fn));
    // App-generated breadcrumbs are translated segment by segment.
    if(key.includes(' / ')&&dictionary[key.split(' / ')[0]])return key.split(' / ').map(x=>dictionary[x]?.[lang]||x).join(' / ');
    return source;
  }
  function apply(){
    if(observer)observer.disconnect();
    document.documentElement.lang=lang;
    document.title=lang==='en'?'Hogwarts Chronicles':lang==='uk'?'Хроніки Гоґвортсу':'Хроники Хогвартса';
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    let node;
    while((node=walker.nextNode())){
      if(!node.parentElement||node.parentElement.closest(excluded)||node.parentElement.closest('script,style'))continue;
      const prior=originals.get(node);
      const source=prior&&node.nodeValue===prior.rendered?prior.source:node.nodeValue;
      const rendered=translate(source);
      originals.set(node,{source,rendered});
      if(node.nodeValue!==rendered)node.nodeValue=rendered;
    }
    document.querySelectorAll('[placeholder],[aria-label],[title]').forEach(el=>{
      if(el.closest('.story,[data-source]'))return;
      let record=originals.get(el)||{};
      for(const attr of ['placeholder','aria-label','title']){
        if(!el.hasAttribute(attr))continue;
        const value=el.getAttribute(attr),prior=record[attr];
        const source=prior&&value===prior.rendered?prior.source:value;
        const rendered=translate(source);record[attr]={source,rendered};
        if(value!==rendered)el.setAttribute(attr,rendered);
      }
      originals.set(el,record);
    });
    const select=document.querySelector('#ui-language');if(select)select.value=lang;
    if(observer)observer.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['placeholder','aria-label','title']});
  }
  let scheduled=false;
  function schedule(){if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;apply();});}
  async function init(){
    try{const response=await fetch('/locales.json');dictionary=await response.json();}
    catch(e){console.warn('UI translations unavailable.');}
    observer=new MutationObserver(schedule);apply();
    document.addEventListener('change',event=>{if(event.target.id==='ui-language'){lang=event.target.value;localStorage.setItem('ui_language',lang);apply();}});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  return {apply,translate,get language(){return lang;}};
})();
