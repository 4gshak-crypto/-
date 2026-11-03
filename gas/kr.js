/* Страница «Капитальный ремонт»: KrView.mount(контейнер, данные, {today, title, actions}).
   Данные — результат tools/kr_parse.py + flood_parse.py (или gas/kr_import.js в браузере). Правится здесь; build.py и tools/build_kr.py вставляют этот файл в страницы. */
var KrView=(function(){
'use strict';
function mount(root,D,opts){
opts=opts||{};
const T=opts.today||D.today,P=D.positions.map(p=>Object.assign({},p));
P.forEach(p=>{if(!p.flood&&D.flood&&D.flood.by)p.flood=D.flood.by[p.hk]||null;});
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const dmy=d=>d?d.split("-").reverse().join("."):"";
const plural=(n,a,b,c)=>{const m=n%10,h=n%100;return m===1&&h!==11?a:m>=2&&m<=4&&(h<12||h>14)?b:c;};
const rub=n=>Math.round(n).toLocaleString("ru-RU")+" ₽";
const mln=n=>(n/1e6).toLocaleString("ru-RU",{maximumFractionDigits:1})+" млн ₽";
const gen=n=>n+" "+(n%10===1&&n%100!==11?"позиции":"позиций"),dat=n=>n+" "+(n%10===1&&n%100!==11?"позиции":"позициям");
const sum=(l,f)=>l.reduce((s,p)=>s+(f(p)||0),0);
const day=iso=>Date.UTC(+iso.slice(0,4),+iso.slice(5,7)-1,+iso.slice(8,10))/864e5;

/* этапы по проценту выполнения: статуса в файле нет */
const ST=[["todo","Процент не указан","нет данных о ходе работ"],["prog","В работе","процент от 1 до 99"],["done","Выполнено","процент 100"],["stop","Встали","в файле отметка «встали»"]];
const SN=Object.fromEntries(ST.map(s=>[s[0],s[1]])),G={todo:"todo",prog:"prog",done:"done",stop:"attn"};
const stageOf=p=>p.state?"stop":p.pct===100?"done":p.pct>0?"prog":"todo";
P.forEach(p=>{p.g=stageOf(p);p.w=(p.kr||0)*(p.pct||0)/100;
  p.elapsed=p.start&&p.end&&p.start<p.end?Math.max(0,Math.min(100,(day(T)-day(p.start))/(day(p.end)-day(p.start))*100)):null;});

/* проблемы: что проверяется и кто решает */
const FL=[
 ["stop","high","Работа встала","Подрядчик и УК: причина простоя и новый срок",p=>!!p.state],
 ["endlate","high","Срок окончания прошёл, а выполнено меньше 100%","Подрядчик: новый срок или закрыть работу",p=>p.end&&p.end<T&&(p.pct||0)<100&&!p.state],
 ["behind","high","Выполнение отстаёт от графика (на 15 пунктов и больше)","Подрядчик: что мешает и как наверстать",p=>p.elapsed!=null&&p.end>=T&&p.pct!=null&&p.elapsed-p.pct>=15&&p.pct<100],
 ["latenopct","high","График начала прошёл, а процента выполнения нет","Исполнитель: начата ли работа и сколько сделано",p=>p.start&&p.start<T&&p.pct==null&&!p.state],
 ["vote","high","Нужно переголосование собственников","УК: провести переголосование",p=>p.vote],
 ["floodrep","high","Повторные подтопления после «устранено»","УК: акт совместного обследования и эскалация в Водоканал",p=>!!(p.flood&&p.flood.repeat)],
 ["nocontract","mid","Работа идёт или закончена, а суммы договора в файле нет","ПТО: оформить договор или внести его сумму",p=>p.pct>0&&!p.contract],
 ["floodwait","mid","Подтопление: претензия ждёт ответа","УК: контролировать срок ответа организации",p=>!!(p.flood&&p.flood.gis_pending>0)],
 ["flood","mid","В доме подтапливало подвал (есть в реестре подтоплений)","УК: учесть при планировании работ, контролировать ответы",p=>!!p.flood],
 ["nopay","mid","Аванс из банка есть, работа идёт, а оплаты подрядчику в файле нет","ПТО: внести оплату («Аванс/расчёт») или пояснить",p=>!!p.bank&&!p.pay&&p.pct>0],
 ["noend","mid","Нет срока окончания","ПТО: внести срок",p=>!p.end],
 ["noexec","mid","Не назначен исполнитель по плану","ПТО: назначить исполнителя",p=>!p.executor],
 ["nocontr","mid","Нет основного подрядчика","ПТО: указать подрядчика",p=>!p.contractor],
 ["nostart","low","Нет графика начала работ","ПТО: внести дату начала",p=>!p.start],
 ["shortc","low","Сумма договора меньше суммы КР","ПТО: сверить договор с суммой КР",p=>p.contract&&p.kr&&p.contract<p.kr*.99],
 ["nokr","low","Нет суммы КР","ПТО: внести сумму",p=>!p.kr]];
const SEV={high:"красное срывает сроки",mid:"жёлтое копится",low:"серое — порядок в данных"};
P.forEach(p=>{p.fl=FL.filter(f=>f[4](p)).map(f=>f[0]);p.bad=p.fl.some(k=>!/^flood/.test(k)&&FL.find(f=>f[0]===k)[1]==="high");});
const FLN=Object.fromEntries(FL.map(f=>[f[0],f]));
const SHORTFL={stop:"встали",endlate:"срок прошёл",behind:"отстаёт",latenopct:"старт прошёл",vote:"переголосование",floodrep:"повторные подтопления",floodwait:"подтопление: ждёт ответа",flood:"подтопления",nocontract:"нет договора",nopay:"нет оплаты",noend:"нет срока",noexec:"нет исполнителя",nocontr:"нет подрядчика",nostart:"нет старта",shortc:"договор < КР",nokr:"нет суммы КР"};

/* состояние отбора */
let V={q:"",stage:"",flag:"",term:"",hk:"",who:"contractor",whoKey:null,open:{}};
const list=()=>P.filter(p=>(!V.stage||p.g===V.stage)&&(!V.hk||p.hk===V.hk)&&(!V.flag||p.fl.includes(V.flag))&&(!V.term||termKey(p)===V.term)&&
  (V.whoKey==null||whoVal(p,V.who)===V.whoKey)&&(!V.q||(p.addr+" "+p.lines.map(l=>l.work).join(" ")+" "+p.contractor+" "+p.executor).toLowerCase().includes(V.q.toLowerCase())));
const termKey=p=>p.end?p.end_txt:"—";
const whoVal=(p,w)=>(w==="executor"?p.executor:p.contractor)||"—";
const stack=(l,w)=>{const t=l.length;if(!t)return'<div class="stk"></div>';
  return'<div class="stk">'+ST.map(s=>{const n=l.filter(p=>p.g===s[0]).length;return n?'<span class="g-'+G[s[0]]+'" style="flex:'+n+'" title="'+esc(s[1])+': '+n+'"></span>':"";}).join("")+'</div>';};
const wavg=l=>{const k=sum(l,p=>p.kr);return k?Math.round(sum(l,p=>p.w)*100/k):0;};

function render(){
  const kpi=(n,t,bad)=>'<div'+(bad?' class="bad"':"")+'><div class="n">'+n+'</div><div class="t">'+t+'</div></div>';
  const NH=new Set(P.map(p=>p.hk)).size,N=P.length,KR=sum(P,p=>p.kr),WP=wavg(P),by=Object.fromEntries(ST.map(s=>[s[0],P.filter(p=>p.g===s[0])]));
  const noPctLate=FL[3][4];
  /* 1. где мы сейчас */
  const card=(k,cls,extra)=>{const l=by[k];return'<button type="button" class="stage g-'+G[k]+' '+cls+'" data-stage="'+k+'"><span class="sh"><i></i>'+esc(SN[k])+'</span><span class="sn">'+l.length+'</span><span class="sp">'+mln(sum(l,p=>p.kr))+' · '+(KR?Math.round(sum(l,p=>p.kr)*100/KR):0)+'% суммы</span>'+extra+'</button>';};
  const sx=(n,bad,ok)=>n?'<span class="sx">'+bad+'</span>':'<span class="sx ok">'+ok+'</span>';
  const pipe='<div class="pipe">'+ST.map((s,i)=>{const v=sum(by[s[0]],p=>p.kr);return v?(s[0]==="stop"&&i?'<span class="gap"></span>':"")+'<span class="g-'+G[s[0]]+'" style="flex:'+v+'" data-tip="'+esc(s[1])+': '+mln(v)+'"></span>':"";}).join("")+'</div>';
  const hero='<section class="card"><h3>Где мы сейчас <span>позиции перечня по проценту выполнения</span></h3><div class="hero-top"><div class="hero-l"><span class="hero-big">'+WP+'%</span>'+
    '<span class="hero-txt">выполнено по сумме КР. Всего '+mln(KR)+': '+NH+' '+plural(NH,"дом","дома","домов")+', '+N+' '+plural(N,"позиция","позиции","позиций")+'. На 100% закрыто '+by.done.length+', в работе '+by.prog.length+', процент не указан у '+gen(by.todo.length)+(by.stop.length?', встали '+by.stop.length:"")+'.</span></div>'+
    '<span class="money">Аванс из банка '+mln(sum(P,p=>p.bank))+' · по договорам '+mln(sum(P,p=>p.contract))+'</span></div>'+pipe+
    '<div class="stages s4">'+
      card("todo","flow arrow",sx(by.todo.filter(noPctLate).length,by.todo.filter(noPctLate).length+" — график начала прошёл","срок начала не наступил или не указан"))+
      card("prog","flow arrow",sx(P.filter(p=>p.fl.includes("behind")||p.fl.includes("endlate")).length,P.filter(p=>p.fl.includes("behind")||p.fl.includes("endlate")).length+" — отстают от графика или срок прошёл","по графику"))+
      card("done","flow",'<span class="sx ok">100% по файлу</span>')+
      card("stop","side",sx(by.stop.length,"причина и срок не указаны","нет"))+
    '</div><p class="note">Этап определён по проценту выполнения: отдельного статуса в файле нет. «Выполнено по сумме КР» — это сумма КР × процент выполнения по каждой позиции. Нажмите на карточку, чтобы открыть список.</p></section>';

  /* подтопления подвалов по домам программы */
  const HK={};P.forEach(p=>{(HK[p.hk]=HK[p.hk]||{hk:p.hk,addr:p.addr,l:[]}).l.push(p);});
  const FH=Object.values(HK).filter(h=>h.l[0].flood).sort((a,b)=>b.l[0].flood.total-a.l[0].flood.total);
  let floodCard="";
  if(D.flood&&FH.length){
    const F=D.flood,fs=FH.map(h=>h.l[0].flood),tot=sum(fs,f=>f.total),gis=sum(fs,f=>f.gis),pend=sum(fs,f=>f.gis_pending),rep=fs.filter(f=>f.repeat).length,
      cat=c=>sum(fs,f=>f.cats[c]),ans=sum(["done","done_blame","refuse","plan","third"].map(c=>({v:cat(c)})),x=>x.v),dd=s=>s.slice(0,5);
    floodCard='<section class="card"><h3>Подтопления подвалов <span>реестр на '+esc(F.updated)+' · с '+esc(dd(F.period_start))+' по '+esc(dd(F.period_end))+'</span></h3>'+
      '<div class="sub">В реестре есть '+FH.length+' из '+NH+' '+plural(NH,"дома","домов","домов")+' программы: '+tot+' '+plural(tot,"заявка","заявки","заявок")+' в АДС — '+Math.round(tot*100/F.register_total)+'% всех заявок реестра ('+F.register_total+' по '+F.register_addresses+' адресам). Нажмите на дом, чтобы открыть его позиции.</div>'+
      '<div class="fkpi">'+kpi(tot,plural(tot,"заявка","заявки","заявок")+" в АДС о подтоплении")+kpi(gis,"обращений УК в ГИС ЖКХ"+(pend?", из них "+pend+" без ответа (в "+fs.filter(f=>f.gis_pending).length+" "+plural(fs.filter(f=>f.gis_pending).length,"доме","домах","домах")+")":", все с ответом"),pend>0)+
      kpi(rep,"дома с повторным подтоплением после «устранено»",rep>0)+kpi(ans,"ответов организаций: устранено "+cat("done")+", вина на УК или жителей "+cat("done_blame")+", отказ "+cat("refuse"))+'</div>'+
      '<div class="tscroll"><table class="wt fh-t" style="min-width:0"><thead><tr><th>Дом</th><th>Заявок в АДС</th><th class="st">Обращений в ГИС ЖКХ</th><th>Без ответа</th><th class="st">Последнее</th><th>Повторы</th><th>Работы КР</th></tr></thead><tbody>'+
      FH.map(h=>{const f=h.l[0].flood;return'<tr data-fh="'+esc(h.hk)+'" tabindex="0"><td>'+esc(h.addr)+'</td><td><b>'+f.total+'</b></td><td class="st">'+f.gis+'</td><td'+(f.gis_pending?' class="bad"':"")+'>'+(f.gis_pending||'<span class="z">0</span>')+'</td><td class="st">'+esc(f.last)+'</td><td'+(f.repeat?' class="bad"':"")+'>'+(f.repeat?f.repeat.cycles+" "+plural(f.repeat.cycles,"раз","раза","раз"):'<span class="z">нет</span>')+'</td><td>'+esc(h.l.map(p=>p.state?p.state:p.pct!=null?p.pct+"%":"нет %").join(" · "))+'</td></tr>';}).join("")+'</tbody></table></div>'+
      '<p class="note">Из реестра взяты только цифры и сроки. Заявки в АДС — это обращения жителей и служб; обращения в ГИС ЖКХ направляет УК в Водоканал, Управление ЖКХ, ГЖИ и другие организации. Подробности по дому — в раскрытой позиции ниже. Дома программы, которых в таблице нет, в реестре подтоплений не значатся (или записаны по-другому).</p></section>';
  }
  /* финансы года: сколько запланировано, сделано и оплачено */
  const Y=+T.slice(0,4),yr=p=>p.end?+p.end.slice(0,4):null,live=p=>(p.pct||0)>0||(p.start&&+p.start.slice(0,4)===Y);
  const FG=[["a","Срок окончания в "+Y+" году",p=>!!p.end&&yr(p)<=Y],["b","Без срока окончания, но идёт в "+Y+" году",p=>!p.end&&!!live(p)],
    ["c","Без срока и без данных о ходе",p=>!p.end&&!live(p)],["d","Срок окончания позже "+Y+" года",p=>!!p.end&&yr(p)>Y]];
  const fg=FG.map(g=>{const l=P.filter(g[2]);return{t:g[1],n:l.length,kr:sum(l,p=>p.kr),w:sum(l,p=>p.w),bank:sum(l,p=>p.bank),pay:sum(l,p=>p.pay),contract:sum(l,p=>p.contract)};});
  const pl=P.filter(p=>FG[0][2](p)||FG[1][2](p)),pk=sum(pl,p=>p.kr),pw=sum(pl,p=>p.w),pbank=sum(pl,p=>p.bank),ppay=sum(pl,p=>p.pay);
  const prc=(a,b)=>b?Math.round(a*100/b):0,m1=n=>(n/1e6).toLocaleString("ru-RU",{maximumFractionDigits:1});
  const frow=(t,g,cls)=>'<tr'+(cls?' class="'+cls+'"':"")+'><td>'+esc(t)+'</td><td class="st">'+g.n+'</td><td>'+m1(g.kr)+'</td><td>'+m1(g.w)+'</td><td><b>'+prc(g.w,g.kr)+'%</b></td><td class="st">'+m1(g.bank)+'</td><td>'+(g.pay?m1(g.pay):'<span class="z">0</span>')+'</td></tr>';
  const sumG=gs=>gs.reduce((a,g)=>({n:a.n+g.n,kr:a.kr+g.kr,w:a.w+g.w,bank:a.bank+g.bank,pay:a.pay+g.pay}),{n:0,kr:0,w:0,bank:0,pay:0});
  const adv=P.filter(p=>p.bank).sort((a,b)=>b.bank-a.bank);
  const finCard='<section class="card" id="fincard"><h3>Финансы '+Y+' года <span>план, выполнено и аванс по перечню</span></h3>'+
    '<div class="sub">«Запланировано» — позиции со сроком окончания в '+Y+' году и позиции без срока окончания, которые уже идут (есть процент выполнения или график начала в '+Y+' году). «Сделано» — сумма КР × процент выполнения по каждой позиции.</div>'+
    '<div class="fkpi">'+kpi(mln(pk),"запланировано на "+Y+" год: "+pl.length+" "+plural(pl.length,"позиция","позиции","позиций"))+kpi(mln(pw),"сделано: "+prc(pw,pk)+"% от плана")+kpi(mln(pk-pw),"осталось сделать")+
      kpi(mln(ppay),"аванс оплачен подрядчикам («Аванс/расчёт»); аванс из банка по плану "+mln(pbank)+(pbank?", оплачено "+prc(ppay,pbank)+"%":""),pbank>0&&ppay<pbank*.5)+'</div>'+
    '<div class="pipe" title="сделано и осталось"><span class="g-done" style="flex:'+Math.max(pw,1)+'" data-tip="Сделано: '+mln(pw)+'"></span><span class="g-todo" style="flex:'+Math.max(pk-pw,1)+'" data-tip="Осталось: '+mln(pk-pw)+'"></span></div>'+
    '<div class="legend"><span><i class="g-done" style="background:var(--c)"></i>Сделано '+mln(pw)+'</span><span><i class="g-todo" style="background:var(--c)"></i>Осталось '+mln(pk-pw)+'</span></div>'+
    '<div class="tscroll" style="margin-top:12px"><table class="wt fh-t fin-t" style="min-width:0"><thead><tr><th>Позиции по сроку</th><th class="st">Позиций</th><th>Сумма КР, млн ₽</th><th>Сделано, млн ₽</th><th>%</th><th class="st">Аванс из банка, млн ₽</th><th>Оплачено, млн ₽</th></tr></thead><tbody>'+
    frow(fg[0].t,fg[0])+frow(fg[1].t,fg[1])+frow("Итого запланировано на "+Y+" год",sumG([fg[0],fg[1]]),"bold")+frow(fg[2].t,fg[2])+frow(fg[3].t,fg[3])+frow("Вся программа",sumG(fg),"bold")+'</tbody></table></div>'+
    (adv.length?'<h4 style="margin:16px 0 4px;font-size:13px">Аванс по домам</h4><div class="sub" style="margin-bottom:8px">Аванс из банка по перечню и то, что отражено как оплаченное подрядчику. Красным — работа идёт, а оплаты в файле нет.</div>'+
      '<div class="tscroll"><table class="wt fh-t fin-t" style="min-width:0"><thead><tr><th>Позиция</th><th>Аванс из банка, млн ₽</th><th>Оплачено, млн ₽</th><th>Выполнено</th></tr></thead><tbody>'+
      adv.map(p=>{const bad=!p.pay&&p.pct>0;return'<tr data-fp="'+p.id+'" tabindex="0"><td>'+esc(p.addr)+'</td><td>'+m1(p.bank)+'</td><td'+(bad?' class="bad"':"")+'>'+(p.pay?m1(p.pay):'<span class="z">0</span>')+'</td><td>'+esc(p.state?p.state:p.pct!=null?p.pct+"%":"нет %")+'</td></tr>';}).join("")+
      '<tr class="bold"><td>Итого</td><td>'+m1(sum(adv,p=>p.bank))+'</td><td>'+m1(sum(adv,p=>p.pay))+'</td><td></td></tr></tbody></table></div>':"")+
    '<p class="note">Данные из перечня работ; оплата — только то, что внесено в колонку «Аванс/расчёт». Если оплата проведена, но в файле её нет, цифры занижены. Позиции без срока и без данных о ходе ('+fg[2].n+') и со сроком позже '+Y+' года ('+fg[3].n+') в план '+Y+' года не входят.</p></section>';

  /* 2. где проблемы */
  const rows=FL.map(f=>{const l=P.filter(p=>p.fl.includes(f[0]));return l.length?'<li class="sev-'+f[1]+'" data-flag="'+f[0]+'" tabindex="0" role="button"><span class="sv"></span><span class="pn">'+l.length+'</span><span class="pt"><b>'+esc(f[2])+'</b><span>'+esc(f[3])+(sum(l,p=>p.kr)?' · КР '+mln(sum(l,p=>p.kr)):"")+'</span></span><span class="pa">Показать →</span></li>':"";}).join("");
  const probs='<section class="card"><h3>Где проблемы <span>по важности</span></h3><div class="sub">'+SEV.high+', '+SEV.mid+', '+SEV.low+'. Нажмите на строку, чтобы открыть эти позиции.</div><ul class="plist">'+rows+'</ul></section>';

  /* 3. по срокам окончания */
  const gt={};P.forEach(p=>{const k=termKey(p);(gt[k]=gt[k]||{k,end:p.end,l:[]}).l.push(p);});
  const terms=Object.values(gt).sort((a,b)=>(a.end||"9999")<(b.end||"9999")?-1:1);
  const trows=terms.map(g=>{const badge=!g.end?'<em class="mb next">срок не указан</em>':g.end<T?(g.l.some(p=>p.pct!==100)?'<em class="mb late">срок прошёл</em>':'<em class="mb ok">закрыт</em>'):g.l.length&&/кв/.test(g.k)&&gQuarterNow(g.k)?'<em class="mb now">идёт сейчас</em>':'<em class="mb next">впереди</em>';
    return'<button type="button" class="krow" data-term="'+esc(g.k)+'"><span class="ml">'+esc(g.k==="—"?"Без срока":g.k)+badge+'</span>'+stack(g.l)+'<span class="mv"><b>'+wavg(g.l)+'%</b><span> · '+g.l.length+' поз. · '+mln(sum(g.l,p=>p.kr))+'</span></span></button>';}).join("");
  const legend='<div class="legend">'+ST.map(s=>'<span><i class="g-'+G[s[0]]+'" style="background:var(--c)"></i>'+esc(s[1])+'</span>').join("")+'</div>';
  const termCard='<section class="card"><h3>По срокам окончания <span>% выполнено · позиций · сумма КР</span></h3><div class="sub">«Срок прошёл» — срок окончания позади, а выполнено меньше 100%. Процент — по сумме КР в группе.</div>'+trows+legend+'</section>';

  /* 4. деньги */
  const bars=[["Сумма КР по перечню",KR,"todo",""],["Аванс из банка",sum(P,p=>p.bank),"prog",KR?Math.round(sum(P,p=>p.bank)*100/KR)+"% суммы КР":""],
    ["Сумма договоров с подрядчиками",sum(P,p=>p.contract),"noact",KR?Math.round(sum(P,p=>p.contract)*100/KR)+"% суммы КР":""],
    ["Выполнено по проценту (КР × %)",sum(P,p=>p.w),"done",WP+"% суммы КР"],
    ["Оплачено («Аванс/расчёт»)",sum(P,p=>p.pay),"winter",KR?(sum(P,p=>p.pay)*100/KR).toLocaleString("ru-RU",{maximumFractionDigits:1})+"% суммы КР":""]];
  const money='<section class="card"><h3>Деньги <span>вся программа, все годы</span></h3><div class="sub">Сколько заложено, сколько под договором и сколько сделано.</div>'+
    bars.map(b=>'<div class="mny g-'+b[2]+'"><span>'+esc(b[0])+'</span><span class="tr"><i style="width:'+(KR?Math.max(.5,b[1]*100/KR):0)+'%"></i></span><span class="v">'+mln(b[1])+(b[3]?'<br><small>'+b[3]+'</small>':"")+'</span></div>').join("")+'</section>';

  /* 5. кто выполняет */
  const gw={};P.forEach(p=>{const k=whoVal(p,V.who);(gw[k]=gw[k]||{k,l:[]}).l.push(p);});
  const wrows=Object.values(gw).sort((a,b)=>b.l.filter(p=>p.bad).length-a.l.filter(p=>p.bad).length||sum(b.l,p=>p.kr)-sum(a.l,p=>p.kr));
  const who='<section class="card"><div class="hrow"><h3>Кто выполняет</h3><div class="seg" role="group" aria-label="Разрез"><button type="button" data-who="contractor" aria-pressed="'+(V.who==="contractor")+'">Основной подрядчик</button><button type="button" data-who="executor" aria-pressed="'+(V.who==="executor")+'">Исполнитель по плану</button></div></div>'+
    '<div class="sub">Сначала — у кого больше позиций с серьёзными проблемами. Нажмите на строку, чтобы открыть позиции.</div><div class="tscroll"><table class="wt" style="min-width:0"><thead><tr><th>'+(V.who==="executor"?"Исполнитель":"Подрядчик")+'</th><th>Позиций</th><th>Сумма КР</th><th>Этапы</th><th>С проблемами</th><th>% выполнено</th></tr></thead><tbody>'+
    wrows.map(g=>{const pc=wavg(g.l),bad=g.l.filter(p=>p.bad).length;return'<tr data-whokey="'+esc(g.k)+'" tabindex="0"><td>'+esc(g.k==="—"?"Не указан":g.k)+'</td><td>'+g.l.length+'</td><td>'+mln(sum(g.l,p=>p.kr))+'</td><td style="min-width:120px">'+stack(g.l)+'</td><td'+(bad?' class="bad"':"")+'>'+(bad||'<span class="z">0</span>')+'</td><td><span class="pbar"><i><b style="width:'+pc+'%"></b></i>'+pc+'%</span></td></tr>';}).join("")+'</tbody></table></div></section>';

  /* 6. позиции */
  const L=list(),act=[V.stage&&["stage","этап: "+SN[V.stage]],V.flag&&["flag","проблема: "+FLN[V.flag][2]],V.term&&["term","срок: "+(V.term==="—"?"не указан":V.term)],V.hk&&["hk","дом: "+(P.find(p=>p.hk===V.hk)||{}).addr],V.whoKey!=null&&["whoKey",(V.who==="executor"?"исполнитель: ":"подрядчик: ")+(V.whoKey==="—"?"не указан":V.whoKey)]].filter(Boolean);
  const chips=['<button type="button" class="chip" data-stg="" aria-pressed="'+(!V.stage)+'">Все <b>'+N+'</b></button>'].concat(ST.map(s=>'<button type="button" class="chip" data-stg="'+s[0]+'" aria-pressed="'+(V.stage===s[0])+'"><i class="g-'+G[s[0]]+'"></i>'+esc(s[1])+' <b>'+by[s[0]].length+'</b></button>')).join("");
  const item=p=>{const o=V.open[p.id];
    return'<div><button type="button" class="pos g-'+G[p.g]+'" data-pos="'+p.id+'" aria-expanded="'+!!o+'"><span class="sev"></span><span><span class="a">'+esc(p.addr)+'</span><span class="w" style="display:block">'+esc(p.lines.filter(l=>!l.cancelled).map(l=>l.work).join(" · ")||"—")+'</span>'+
      (p.fl.length?'<span class="fl">'+p.fl.map(k=>'<span class="chkpill'+(FLN[k][1]==="high"?" bad":"")+'">'+(k==="flood"?"подтопления: "+p.flood.total:SHORTFL[k])+'</span>').join("")+'</span>':"")+'</span>'+
      '<span class="r"><span class="pill dot">'+(p.state?esc(p.state):p.pct!=null?p.pct+"%":"процент не указан")+'</span><span class="num">'+(p.kr?mln(p.kr):"нет суммы")+'</span><span class="faint">'+esc(p.contractor||"—")+'</span></span></button>'+(o?detail(p):"")+'</div>';};
  const pos='<section class="card" id="poslist"><h3>Позиции <span>'+L.length+' '+plural(L.length,"позиция","позиции","позиций")+'</span></h3>'+
    '<div class="kfilters"><input class="ctl" id="kq" type="search" placeholder="Адрес, работа, подрядчик" value="'+esc(V.q)+'" aria-label="Поиск"></div><div class="chips" role="group" aria-label="Этап">'+chips+'</div>'+
    (act.length?'<div class="fpills">'+act.map(a=>'<span class="fpill">'+esc(a[1])+'<button type="button" data-clr="'+a[0]+'" aria-label="Убрать отбор">×</button></span>').join("")+'</div>':"")+
    '<div style="margin-top:8px">'+(L.length?L.map(item).join(""):'<div class="empty">Ничего не найдено</div>')+'</div></section>';

  /* 7. что уточнить */
  const cnt=a=>a.length+" "+plural(a.length,"позиция","позиции","позиций");
  const q=[];
  const red=P.filter(p=>p.fill==="FF0000"),green=P.filter(p=>p.fill==="008000");
  q.push("<b>Цвета заливки в файле не расшифрованы.</b> Красная у адреса: "+cnt(red)+(red.length?" ("+red.map(p=>esc(p.addr)+(p.pct!=null?", "+p.pct+"%":", процента нет")).join("; ")+")":"")+"; зелёная: "+cnt(green)+". Если это статусы, подскажите, что означает каждый цвет, и страница это покажет.");
  const nop=by.todo;q.push("<b>Процент выполнения не указан</b> у "+gen(nop.length)+" на "+mln(sum(nop,p=>p.kr))+". Проставьте процент (0% — тоже ответ) или дату начала работ, иначе по таким позициям нельзя понять, начаты ли они.");
  const pay=P.filter(p=>p.pay);q.push("<b>Колонка «Аванс/расчёт»:</b> заполнена у "+gen(pay.length)+" на "+mln(sum(pay,p=>p.pay))+", тогда как аванс из банка — "+mln(sum(P,p=>p.bank))+" по "+dat(P.filter(p=>p.bank).length)+". Это выплаты подрядчикам? Остальные выплаты в файле не отражены.");
  const odd=[];P.forEach(p=>p.lines.forEach(l=>{if(l.sum&&l.contract&&l.contract>5*l.sum)odd.push(esc(p.addr)+", «"+esc(l.work)+"»: договор "+rub(l.contract)+" при сумме раздела "+rub(l.sum));}));
  if(odd.length)q.push("<b>Возможная опечатка в сумме договора:</b> "+odd.join("; ")+".");
  const canc=[];P.forEach(p=>p.lines.filter(l=>l.cancelled).forEach(l=>canc.push(esc(p.addr)+", «"+esc(l.work)+"»")));
  if(canc.length)q.push("<b>Строки с пометкой «отмена»</b> (сумма 0): "+canc.join("; ")+". Исключить из перечня?");
  const bad=P.filter(p=>/\?/.test(p.addr));if(bad.length)q.push("<b>В адресе вопросительные знаки:</b> "+bad.map(p=>esc(p.addr)).join("; ")+". Уточнить адрес, сумму и подрядчика.");
  const nok=P.filter(p=>!p.kr);if(nok.length)q.push("<b>Нет суммы КР:</b> "+nok.map(p=>esc(p.addr)).join("; ")+".");
  const stp=P.filter(p=>p.state);if(stp.length)q.push("<b>Отметка «"+esc(stp[0].state)+"»:</b> "+stp.map(p=>esc(p.addr)).join("; ")+". Причина и новый срок не указаны.");
  const vt=P.filter(p=>p.vote);if(vt.length)q.push("<b>«Переголосовывать»:</b> "+vt.map(p=>esc(p.addr)).join("; ")+". Когда и кто проводит переголосование?");
  const quest='<section class="card"><h3>Что уточнить по файлу <span>без этого страница показывает не всё</span></h3><ol class="qlist">'+q.map(x=>"<li>"+x+"</li>").join("")+'</ol></section>';

  root.innerHTML='<div class="kr-head"><h2>'+esc(opts.title||"Сводка")+'</h2>'+(opts.actions?'<span class="kacts-h">'+opts.actions+'</span>':"")+'<span class="faint" style="font-size:12px">по перечню работ, сохранённому '+esc(dmy(D.saved))+' · сроки посчитаны на '+esc(dmy(T))+'</span></div>'+hero+finCard+floodCard+'<div class="grid2">'+probs+'<div style="display:flex;flex-direction:column;gap:12px;min-width:0">'+termCard+money+'</div></div>'+who+pos+quest;
  bind();
}
function gQuarterNow(k){const m=/(\d) кв\. (\d{4})/.exec(k);if(!m)return false;const q=+m[1],y=+m[2],s=y+"-"+String(q*3-2).padStart(2,"0")+"-01",e=new Date(Date.UTC(y,q*3,0)).toISOString().slice(0,10);return s<=T&&T<=e;}
function detail(p){
  const mon=n=>n?rub(n):"—",pc=p.pct==null?"не указан":p.pct+"%";
  const kv=[["Основной подрядчик",p.contractor||"не указан"],["Исполнитель по плану",p.executor||"не указан"],["График начала",p.start_txt||"не указан"],["Срок окончания",p.end_txt||"не указан"],
    ["Процент выполнения",{html:p.state?esc(p.state):'<span class="pbar2 g-'+G[p.g]+'"><i><b style="width:'+(p.pct||0)+'%"></b></i>'+pc+'</span>'+(p.elapsed!=null?' <span class="faint">· по времени прошло '+Math.round(p.elapsed)+'%</span>':"")}],
    ["Сумма КР",mon(p.kr)],["Аванс из банка",mon(p.bank)],["Сумма договора",mon(p.contract)],["Аванс/расчёт",mon(p.pay)],["Выполнено по проценту",mon(p.w)]];
  const lines='<table class="lt"><thead><tr><th>Работа (решение собственников)</th><th class="n">Сумма по разделу</th><th class="n">Договор по строке</th></tr></thead><tbody>'+
    p.lines.map(l=>'<tr><td'+(l.cancelled?' class="x"':"")+'>'+esc(l.work)+(l.cancelled?" — отмена":"")+'</td><td class="n">'+(l.sum?rub(l.sum):l.sum_txt?esc(l.sum_txt):"—")+'</td><td class="n">'+(l.contract?rub(l.contract):"—")+'</td></tr>').join("")+'</tbody></table>';
  let fb="";
  if(p.flood&&D.flood){
    const f=p.flood,CN=D.flood.cats||{},ct=Object.keys(f.cats).map(c=>(CN[c]||c)+": "+f.cats[c]).join("; "),
      kv2=[["Заявок в АДС",f.total],["Обращений УК в ГИС ЖКХ",f.gis],["Период",f.first+" – "+f.last],
        ["Претензии",f.orgs.length?f.orgs.map(o=>o.name+": "+o.sent+(o.pending?" (ждут ответа "+o.pending+")":"")+(o.withdrawn?", отозвано "+o.withdrawn:"")).join("; "):"в ГИС ЖКХ не направлялись"],
        ["Ответы организаций",ct||"ответов пока нет"],
        ["Повторное подтопление",f.repeat?"после «устранено» от "+f.repeat.fix_date+" (повтор через "+f.repeat.days+" дн., циклов: "+f.repeat.cycles+")"+(f.repeat.last_signal?", последний сигнал "+f.repeat.last_signal.date:""):"нет"]];
    fb='<div class="pdf"><h4>Подтопления подвала <span class="faint" style="font-weight:400">· реестр на '+esc(D.flood.updated)+'</span></h4><dl class="kv">'+kv2.map(x=>'<dt>'+esc(x[0])+'</dt><dd>'+esc(x[1])+'</dd>').join("")+'</dl>'+
      (f.actions.length?'<div style="font-size:13px"><b>Что предлагает реестр:</b><ul class="kacts" style="margin:4px 0 0;padding-left:18px">'+f.actions.slice(0,3).map(a=>'<li><span class="faint">'+esc(a.group)+':</span> '+esc(a.text)+'</li>').join("")+'</ul></div>':"")+'</div>';
  }
  return'<div class="pd"><dl class="kv">'+kv.map(x=>'<dt>'+esc(x[0])+'</dt><dd>'+(x[1]&&x[1].html!=null?x[1].html:esc(x[1]))+'</dd>').join("")+'</dl>'+lines+fb+
    (p.fl.length?'<div style="font-size:13px"><b>Что не так:</b> '+p.fl.map(k=>esc(FLN[k][2])).join("; ")+'</div>':"")+(p.notes.length?'<div class="faint" style="font-size:12px">'+p.notes.map(esc).join("; ")+'</div>':"")+'<div class="faint" style="font-size:12px">Строка '+p.row+' в файле</div></div>';
}
function bind(){
  const go=()=>{render();const el=root.querySelector("#poslist");if(el)el.scrollIntoView({behavior:"smooth",block:"start"});};
  root.querySelectorAll("[data-stage]").forEach(b=>b.onclick=()=>{V=Object.assign(V,{stage:b.dataset.stage,flag:"",term:"",whoKey:null,q:"",hk:""});go();});
  root.querySelectorAll("[data-flag]").forEach(b=>{const f=()=>{V=Object.assign(V,{flag:b.dataset.flag,stage:"",term:"",whoKey:null,q:"",hk:""});go();};b.onclick=f;b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f();}};});
  root.querySelectorAll("[data-term]").forEach(b=>b.onclick=()=>{V=Object.assign(V,{term:b.dataset.term,stage:"",flag:"",whoKey:null,q:"",hk:""});go();});
  root.querySelectorAll("[data-fh]").forEach(b=>{const f=()=>{V=Object.assign(V,{hk:b.dataset.fh,stage:"",flag:"",term:"",whoKey:null,q:""});go();};b.onclick=f;b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f();}};});
  root.querySelectorAll("[data-fp]").forEach(b=>{const f=()=>{const id=+b.dataset.fp,p=P.find(x=>x.id===id);if(!p)return;V=Object.assign(V,{hk:p.hk,stage:"",flag:"",term:"",whoKey:null,q:""});V.open[id]=true;go();};b.onclick=f;b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f();}};});
  root.querySelectorAll("[data-whokey]").forEach(b=>{const f=()=>{V=Object.assign(V,{whoKey:b.dataset.whokey,stage:"",flag:"",term:"",q:"",hk:""});go();};b.onclick=f;b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f();}};});
  root.querySelectorAll("[data-who]").forEach(b=>b.onclick=()=>{V.who=b.dataset.who;V.whoKey=null;render();});
  root.querySelectorAll("[data-stg]").forEach(b=>b.onclick=()=>{V.stage=b.dataset.stg;render();});
  root.querySelectorAll("[data-clr]").forEach(b=>b.onclick=()=>{const k=b.dataset.clr;if(k==="whoKey")V.whoKey=null;else V[k]="";render();});
  root.querySelectorAll("[data-pos]").forEach(b=>b.onclick=()=>{const id=b.dataset.pos;V.open[id]=!V.open[id];const y=window.scrollY;render();window.scrollTo(0,y);});
  const q=root.querySelector("#kq");if(q){let t;q.oninput=()=>{clearTimeout(t);t=setTimeout(()=>{V.q=q.value.trim();render();const n=root.querySelector("#kq");n.focus();n.setSelectionRange(n.value.length,n.value.length);},200);};}
}
render();
if(opts.onMount)opts.onMount(root);
}
return{mount:mount};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=KrView;
