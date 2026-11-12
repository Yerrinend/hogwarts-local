'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'../web');
const callbacks={};
const ui={nodeValue:'Настройки',parentElement:{closest:()=>null}};
const source={nodeValue:'Драка и Элли: русский исходный текст.',parentElement:{closest:()=>true}};
const placeholder={value:'Действие игрока по-русски',attrs:{placeholder:'Твой ответ или действие…'},closest:()=>false,
 hasAttribute(a){return a in this.attrs;},getAttribute(a){return this.attrs[a];},setAttribute(a,v){this.attrs[a]=v;}};
const context={console,queueMicrotask,NodeFilter:{SHOW_TEXT:4},localStorage:{getItem:()=>null,setItem:()=>{}},
 fetch:async()=>({json:async()=>JSON.parse(fs.readFileSync(path.join(root,'locales.json'),'utf8'))}),
 MutationObserver:class{observe(){}disconnect(){}},window:{},
 document:{readyState:'loading',body:{},documentElement:{},querySelector:()=>null,
 createTreeWalker(){let i=0;const nodes=[ui,source];return{nextNode:()=>nodes[i++]||null};},
 querySelectorAll:()=>[placeholder],addEventListener:(name,fn)=>callbacks[name]=fn}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'i18n.js'),'utf8'),context);
(async()=>{
 await callbacks.DOMContentLoaded();
 callbacks.change({target:{id:'ui-language',value:'en'}});
 assert.equal(ui.nodeValue,'Settings');
 assert.equal(placeholder.attrs.placeholder,'Your reply or action…');
 assert.equal(placeholder.value,'Действие игрока по-русски');
 assert.equal(source.nodeValue,'Драка и Элли: русский исходный текст.');
 callbacks.change({target:{id:'ui-language',value:'uk'}});
 assert.equal(ui.nodeValue,'Налаштування');
 assert.equal(context.window.RPGI18n.translate('Глава 579'),'Розділ 579');
 callbacks.change({target:{id:'ui-language',value:'ru'}});
 assert.equal(ui.nodeValue,'Настройки');
 assert.equal(placeholder.attrs.placeholder,'Твой ответ или действие…');
 console.log('UI languages: RU → EN → UK → RU; source text and draft preserved.');
})().catch(e=>{console.error(e);process.exitCode=1;});
