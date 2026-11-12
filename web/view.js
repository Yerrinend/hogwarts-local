'use strict';
// Presentation only: the stored chapter and its four tables are never rewritten.
window.RPGView={
  chapterTitle(title,number){
    const prefix=new RegExp('^(?:Глава|Розділ|Chapter)\\s+'+number+'(?:\\s*[.:—–-]\\s*|\\s+|$)','iu');
    return String(title).replace(prefix,'').trim();
  },
  chapterBody(text,render){
    const html=render(text);
    const firstTable=html.indexOf('<table>');
    if(firstTable<0)return '<article class="story">'+html+'</article>';
    const headings=[...html.matchAll(/<h[1-3]>(.*?)<\/h[1-3]>/g)];
    const start=headings.find(h=>h.index<firstTable && /^(?:отношения|стосунки|відносини|взаємини|relationships|relations|магические навыки|магічні навички|magical skills|характеристики)$/iu.test(h[1].replace(/<[^>]*>/g,'').replace(/^[^\p{L}]+/u,'').trim()));
    if(!start)return '<article class="story">'+html+'</article>';
    const content=html.slice(start.index);
    return '<article class="story">'+html.slice(0,start.index)+'</article><details class="chapter-stats"><summary><span>Характеристики и инвентарь</span><small>Развернуть таблицы</small></summary><div class="story">'+content+'</div></details>';
  }
};
