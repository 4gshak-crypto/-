"""Страница «Капитальный ремонт» из перечня работ (.xls): один HTML-файл, вход не нужен.

  python3 tools/build_kr.py <перечень .xls> [--today ГГГГ-ММ-ДД] [--saved ГГГГ-ММ-ДД]

Пишет reports/Капитальный ремонт <дата>.html (для скачивания) и capital/kr.html (для публикации).
Оформление берётся из gas/Index.html, чтобы страница выглядела так же, как «Текущий ремонт». Этапы определяются по проценту выполнения:
статуса в файле нет."""
import argparse, datetime, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kr_parse, flood_parse
from srcnorm import addr_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument('xls')
ap.add_argument('--today', default=datetime.date.today().isoformat(), help='на какую дату считать сроки')
ap.add_argument('--saved', help='дата сохранения файла (по умолчанию — из его свойств)')
ap.add_argument('--flood', help='страница «Реестр подтоплений» (HTML): добавляет на страницу сведения о подтоплениях по домам')
A = ap.parse_args()

pos, total, col = kr_parse.read(A.xls)
saved = A.saved
if not saved:
    import subprocess
    out = subprocess.run(['file', A.xls], capture_output=True, text=True).stdout   # дата сохранения лежит в свойствах документа
    m = re.search(r'Last Saved Time/Date: \w+ (\w+)\s+(\d+) [\d:]+ (\d{4})', out)
    saved = datetime.datetime.strptime('%s %s %s' % (m.group(1), m.group(2), m.group(3)), '%b %d %Y').date().isoformat() if m else A.today

mask = lambda t: re.sub(r'\(?\s*(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\s*\)?', '(тел. скрыт)', t) if isinstance(t, str) else t
iso = lambda d: d.isoformat() if d else None
fmeta, fby = flood_parse.read(A.flood) if A.flood else (None, {})
data = dict(today=A.today, saved=saved, total=total, houses=len({addr_key(p['addr']) for p in pos}), legend=dict(), flood=fmeta, positions=[])
legend = {}
for i, p in enumerate(pos):
    names = ['адрес', 'решение собственников', 'сумма КР', 'аванс из банка', 'график начала', 'срок окончания']
    for n, f in zip(names, p['fills']):
        if f and f != 'FFFFFF':
            legend.setdefault(f, {}).setdefault(n, []).append(i)
    data['positions'].append(dict(
        id=i, row=p['row'], addr=mask(p['addr']), kr=p['kr'], bank=p['bank'], contractor=p['contractor'], executor=p['executor'], pay=p['pay'], contract=p['contract'],
        pct=p['pct'], state=p['state'], start=iso(p['start']), start_txt=p['start_txt'], end=iso(p['end']), end_txt=p['end_txt'], vote=p['vote'], notes=p['notes'],
        fill=p['fills'][0] if p['fills'] else None, hk=flood_parse.key(p['addr']), flood=fby.get(flood_parse.key(p['addr'])),
        lines=[dict(row=l['row'], work=mask(l['work']), sum=l['sum'], sum_txt=l['sum_txt'], contract=l['contract'], cancelled=l['cancelled']) for l in p['lines']]))
data['legend'] = legend

# оформление — из страницы «Текущий ремонт»
idx = (ROOT / 'gas' / 'Index.html').read_text(encoding='utf-8')
style = idx[idx.index('<style>'):idx.index('</style>') + 8]
dark = re.search(r"@media \(prefers-color-scheme:dark\)\{:root\{(.*?)\}\}", style, re.S)
style = style.replace(dark.group(0), '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){' + dark.group(1) + '}}\n:root[data-theme="dark"]{' + dark.group(1) + '}')
fonts = re.search(r'<link rel="stylesheet"[^>]+>', idx).group(0)

CSS = r'''
<style>
.kr-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 16px;margin-bottom:16px}
.kr-head h2{font-family:var(--f-display);font-weight:500;font-size:20px;margin:0}
@media (max-width:720px){.kr-bar-in .brand{display:block}}
.kr-bar-in{max-width:1200px;margin:0 auto;padding:0 16px;display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:56px}
.stages.s4{grid-template-columns:repeat(3,minmax(0,1fr)) minmax(0,.85fr)}
@media (max-width:900px){.stages.s4{grid-template-columns:repeat(2,minmax(0,1fr))}}
.fkpi{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0 14px}
.fkpi>div{border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-width:0}
.fkpi .n{font-family:var(--f-display);font-size:22px;font-weight:500;font-variant-numeric:tabular-nums;line-height:1.2}
.fkpi .t{font-size:12px;color:var(--muted)}
.fkpi .bad .n{color:var(--attn-ink)}
@media (max-width:760px){.fkpi{grid-template-columns:repeat(2,minmax(0,1fr))}}
.wt tr[data-fh]{cursor:pointer}
@media (max-width:640px){.fh-t th,.fh-t td{padding:8px 4px;font-size:12px}.fh-t th:last-child,.fh-t td:last-child{white-space:normal;text-align:right}.fh-t th{white-space:normal}}
.pdf{border-top:1px dashed var(--line);padding-top:12px;display:flex;flex-direction:column;gap:8px}
.pdf h4{margin:0;font-size:13px}
.acts li{margin:2px 0}
.mny{display:grid;grid-template-columns:minmax(0,230px) minmax(0,1fr) 150px;gap:10px;align-items:center;padding:6px 0;font-size:13px}
.mny .tr{height:14px;background:var(--surface-2);border-radius:7px;overflow:hidden}
.mny .tr i{display:block;height:100%;background:var(--c);border-radius:7px;min-width:3px}
.mny .v{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.mny .v small{color:var(--muted);font-size:12px}
@media (max-width:640px){.mny{grid-template-columns:minmax(0,1fr) 110px}.mny .tr{grid-column:1/-1;order:3}}
.krow{display:grid;grid-template-columns:150px minmax(0,1fr) 200px;gap:10px;align-items:center;padding:6px 4px;cursor:pointer;border-radius:6px;width:100%;border:0;background:none;text-align:left}
.krow:hover{background:var(--surface-2)}
.krow .ml{font-size:13px;display:flex;align-items:center;gap:6px;white-space:nowrap;min-width:0}
.krow .mv{font-size:12px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.krow .mv b{color:var(--fg)}
@media (max-width:560px){.krow{grid-template-columns:104px minmax(0,1fr) 44px}.krow .mv span{display:none}}
.stk{display:flex;gap:2px;height:16px}
.stk span{min-width:4px;background:var(--c)}
.stk span:first-child{border-radius:4px 0 0 4px} .stk span:last-child{border-radius:0 4px 4px 0}
.pos{display:grid;grid-template-columns:4px minmax(0,1fr) auto;gap:12px;align-items:center;width:100%;text-align:left;border:0;border-top:1px solid var(--line);background:none;padding:10px 10px 10px 0;cursor:pointer}
.pos:hover{background:var(--surface-2)}
.pos .sev{align-self:stretch;border-radius:2px;background:var(--c)}
.pos .a{font-weight:600}
.pos .w{font-size:13px;color:var(--muted);overflow-wrap:anywhere}
.pos .r{display:flex;flex-direction:column;align-items:flex-end;gap:4px;font-size:12px;white-space:nowrap}
.pos .fl{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.pd{padding:6px 0 16px 16px;border-top:1px dashed var(--line);display:flex;flex-direction:column;gap:12px}
.kv{display:grid;grid-template-columns:170px minmax(0,1fr);gap:4px 12px;margin:0;font-size:13px}
.kv dt{color:var(--muted)} .kv dd{margin:0;overflow-wrap:anywhere}
@media (max-width:560px){.kv{grid-template-columns:120px minmax(0,1fr)}}
.pbar2{display:inline-flex;align-items:center;gap:8px}
.pbar2 i{display:inline-block;width:120px;height:8px;border-radius:4px;background:var(--surface-2);overflow:hidden}
.pbar2 i b{display:block;height:100%;background:var(--c)}
.lt{width:100%;border-collapse:collapse;font-size:13px}
.lt th{font-size:11px;font-weight:600;color:var(--muted);text-align:left;padding:4px 8px;border-bottom:1px solid var(--line)}
.lt td{padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.lt td.n,.lt th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.lt .x{color:var(--faint);text-decoration:line-through}
.kfilters{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.kfilters .ctl{flex:1 1 200px}
.qlist{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:8px;font-size:13px}
.qlist b{font-weight:600}
@media print{.bar{position:static}}
</style>'''

BODY = r'''
<header class="bar"><div class="kr-bar-in"><span class="brand">Капитальный ремонт</span><span class="faint" id="kr-when" style="font-size:12px"></span></div></header>
<main id="kr"></main>
<script>
window.KR=__DATA__;
(function(){
"use strict";
const D=window.KR,P=D.positions,T=D.today,$=id=>document.getElementById(id);
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
 ["noend","mid","Нет срока окончания","ПТО: внести срок",p=>!p.end],
 ["noexec","mid","Не назначен исполнитель по плану","ПТО: назначить исполнителя",p=>!p.executor],
 ["nocontr","mid","Нет основного подрядчика","ПТО: указать подрядчика",p=>!p.contractor],
 ["nostart","low","Нет графика начала работ","ПТО: внести дату начала",p=>!p.start],
 ["shortc","low","Сумма договора меньше суммы КР","ПТО: сверить договор с суммой КР",p=>p.contract&&p.kr&&p.contract<p.kr*.99],
 ["nokr","low","Нет суммы КР","ПТО: внести сумму",p=>!p.kr]];
const SEV={high:"красное срывает сроки",mid:"жёлтое копится",low:"серое — порядок в данных"};
P.forEach(p=>{p.fl=FL.filter(f=>f[4](p)).map(f=>f[0]);p.bad=p.fl.some(k=>!/^flood/.test(k)&&FL.find(f=>f[0]===k)[1]==="high");});
const FLN=Object.fromEntries(FL.map(f=>[f[0],f]));
const SHORTFL={stop:"встали",endlate:"срок прошёл",behind:"отстаёт",latenopct:"старт прошёл",vote:"переголосование",floodrep:"повторные подтопления",floodwait:"подтопление: ждёт ответа",flood:"подтопления",nocontract:"нет договора",noend:"нет срока",noexec:"нет исполнителя",nocontr:"нет подрядчика",nostart:"нет старта",shortc:"договор < КР",nokr:"нет суммы КР"};

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
  const N=P.length,KR=sum(P,p=>p.kr),WP=wavg(P),by=Object.fromEntries(ST.map(s=>[s[0],P.filter(p=>p.g===s[0])]));
  $("kr-when").textContent="сроки посчитаны на "+dmy(T);
  const noPctLate=FL[3][4];
  /* 1. где мы сейчас */
  const card=(k,cls,extra)=>{const l=by[k];return'<button type="button" class="stage g-'+G[k]+' '+cls+'" data-stage="'+k+'"><span class="sh"><i></i>'+esc(SN[k])+'</span><span class="sn">'+l.length+'</span><span class="sp">'+mln(sum(l,p=>p.kr))+' · '+(KR?Math.round(sum(l,p=>p.kr)*100/KR):0)+'% суммы</span>'+extra+'</button>';};
  const sx=(n,bad,ok)=>n?'<span class="sx">'+bad+'</span>':'<span class="sx ok">'+ok+'</span>';
  const pipe='<div class="pipe">'+ST.map((s,i)=>{const v=sum(by[s[0]],p=>p.kr);return v?(s[0]==="stop"&&i?'<span class="gap"></span>':"")+'<span class="g-'+G[s[0]]+'" style="flex:'+v+'" data-tip="'+esc(s[1])+': '+mln(v)+'"></span>':"";}).join("")+'</div>';
  const hero='<section class="card"><h3>Где мы сейчас <span>позиции перечня по проценту выполнения</span></h3><div class="hero-top"><div class="hero-l"><span class="hero-big">'+WP+'%</span>'+
    '<span class="hero-txt">выполнено по сумме КР. Всего '+mln(KR)+': '+D.houses+' '+plural(D.houses,"дом","дома","домов")+', '+N+' '+plural(N,"позиция","позиции","позиций")+'. На 100% закрыто '+by.done.length+', в работе '+by.prog.length+', процент не указан у '+gen(by.todo.length)+(by.stop.length?', встали '+by.stop.length:"")+'.</span></div>'+
    '<span class="money">Аванс из банка '+mln(sum(P,p=>p.bank))+' · по договорам '+mln(sum(P,p=>p.contract))+'</span></div>'+pipe+
    '<div class="stages s4">'+
      card("todo","flow arrow",sx(by.todo.filter(noPctLate).length,by.todo.filter(noPctLate).length+" — график начала прошёл","срок начала не наступил или не указан"))+
      card("prog","flow arrow",sx(P.filter(p=>p.fl.includes("behind")||p.fl.includes("endlate")).length,P.filter(p=>p.fl.includes("behind")||p.fl.includes("endlate")).length+" — отстают от графика или срок прошёл","по графику"))+
      card("done","flow",'<span class="sx ok">100% по файлу</span>')+
      card("stop","side",sx(by.stop.length,"причина и срок не указаны","нет"))+
    '</div><p class="note">Этап определён по проценту выполнения: отдельного статуса в файле нет. «Выполнено по сумме КР» — это сумма КР × процент выполнения по каждой позиции. Нажмите на карточку, чтобы открыть список.</p></section>';

  /* подтопления подвалов по домам программы */
  const HK={};P.forEach(p=>{(HK[p.hk]=HK[p.hk]||{hk:p.hk,addr:p.addr,l:[]}).l.push(p);});
  const FH=Object.values(HK).filter(h=>h.l[0].flood).sort((a,b)=>b.l[0].flood.total-a.l[0].flood.total),NH=Object.keys(HK).length;
  let floodCard="";
  if(D.flood&&FH.length){
    const F=D.flood,fs=FH.map(h=>h.l[0].flood),tot=sum(fs,f=>f.total),gis=sum(fs,f=>f.gis),pend=sum(fs,f=>f.gis_pending),rep=fs.filter(f=>f.repeat).length,
      cat=c=>sum(fs,f=>f.cats[c]),ans=sum(["done","done_blame","refuse","plan","third"].map(c=>({v:cat(c)})),x=>x.v),dd=s=>s.slice(0,5);
    const kpi=(n,t,bad)=>'<div'+(bad?' class="bad"':"")+'><div class="n">'+n+'</div><div class="t">'+t+'</div></div>';
    floodCard='<section class="card"><h3>Подтопления подвалов <span>реестр на '+esc(F.updated)+' · с '+esc(dd(F.period_start))+' по '+esc(dd(F.period_end))+'</span></h3>'+
      '<div class="sub">В реестре есть '+FH.length+' из '+NH+' '+plural(NH,"дома","домов","домов")+' программы: '+tot+' '+plural(tot,"заявка","заявки","заявок")+' в АДС — '+Math.round(tot*100/F.register_total)+'% всех заявок реестра ('+F.register_total+' по '+F.register_addresses+' адресам). Нажмите на дом, чтобы открыть его позиции.</div>'+
      '<div class="fkpi">'+kpi(tot,plural(tot,"заявка","заявки","заявок")+" в АДС о подтоплении")+kpi(gis,"обращений УК в ГИС ЖКХ"+(pend?", из них "+pend+" без ответа (в "+fs.filter(f=>f.gis_pending).length+" "+plural(fs.filter(f=>f.gis_pending).length,"доме","домах","домах")+")":", все с ответом"),pend>0)+
      kpi(rep,"дома с повторным подтоплением после «устранено»",rep>0)+kpi(ans,"ответов организаций: устранено "+cat("done")+", вина на УК или жителей "+cat("done_blame")+", отказ "+cat("refuse"))+'</div>'+
      '<div class="tscroll"><table class="wt fh-t" style="min-width:0"><thead><tr><th>Дом</th><th>Заявок в АДС</th><th class="st">Обращений в ГИС ЖКХ</th><th>Без ответа</th><th class="st">Последнее</th><th>Повторы</th><th>Работы КР</th></tr></thead><tbody>'+
      FH.map(h=>{const f=h.l[0].flood;return'<tr data-fh="'+esc(h.hk)+'" tabindex="0"><td>'+esc(h.addr)+'</td><td><b>'+f.total+'</b></td><td class="st">'+f.gis+'</td><td'+(f.gis_pending?' class="bad"':"")+'>'+(f.gis_pending||'<span class="z">0</span>')+'</td><td class="st">'+esc(f.last)+'</td><td'+(f.repeat?' class="bad"':"")+'>'+(f.repeat?f.repeat.cycles+" "+plural(f.repeat.cycles,"раз","раза","раз"):'<span class="z">нет</span>')+'</td><td>'+esc(h.l.map(p=>p.state?p.state:p.pct!=null?p.pct+"%":"нет %").join(" · "))+'</td></tr>';}).join("")+'</tbody></table></div>'+
      '<p class="note">Из реестра взяты только цифры и сроки. Заявки в АДС — это обращения жителей и служб; обращения в ГИС ЖКХ направляет УК в Водоканал, Управление ЖКХ, ГЖИ и другие организации. Подробности по дому — в раскрытой позиции ниже. Дома программы, которых в таблице нет, в реестре подтоплений не значатся (или записаны по-другому).</p></section>';
  }
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
  const money='<section class="card"><h3>Деньги <span>по данным перечня</span></h3><div class="sub">Сколько заложено, сколько под договором и сколько сделано.</div>'+
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

  $("kr").innerHTML='<div class="kr-head"><h2>Сводка</h2><span class="faint" style="font-size:12px">по перечню работ, сохранённому '+esc(dmy(D.saved))+'</span></div>'+hero+floodCard+'<div class="grid2">'+probs+'<div style="display:flex;flex-direction:column;gap:12px;min-width:0">'+termCard+money+'</div></div>'+who+pos+quest;
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
      (f.actions.length?'<div style="font-size:13px"><b>Что предлагает реестр:</b><ul class="acts" style="margin:4px 0 0;padding-left:18px">'+f.actions.slice(0,3).map(a=>'<li><span class="faint">'+esc(a.group)+':</span> '+esc(a.text)+'</li>').join("")+'</ul></div>':"")+'</div>';
  }
  return'<div class="pd"><dl class="kv">'+kv.map(x=>'<dt>'+esc(x[0])+'</dt><dd>'+(x[1]&&x[1].html!=null?x[1].html:esc(x[1]))+'</dd>').join("")+'</dl>'+lines+fb+
    (p.fl.length?'<div style="font-size:13px"><b>Что не так:</b> '+p.fl.map(k=>esc(FLN[k][2])).join("; ")+'</div>':"")+(p.notes.length?'<div class="faint" style="font-size:12px">'+p.notes.map(esc).join("; ")+'</div>':"")+'<div class="faint" style="font-size:12px">Строка '+p.row+' в файле</div></div>';
}
function bind(){
  const go=()=>{render();const el=$("poslist");if(el)el.scrollIntoView({behavior:"smooth",block:"start"});};
  document.querySelectorAll("[data-stage]").forEach(b=>b.onclick=()=>{V=Object.assign(V,{stage:b.dataset.stage,flag:"",term:"",whoKey:null,q:"",hk:""});go();});
  document.querySelectorAll("[data-flag]").forEach(b=>{const f=()=>{V=Object.assign(V,{flag:b.dataset.flag,stage:"",term:"",whoKey:null,q:"",hk:""});go();};b.onclick=f;b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f();}};});
  document.querySelectorAll("[data-term]").forEach(b=>b.onclick=()=>{V=Object.assign(V,{term:b.dataset.term,stage:"",flag:"",whoKey:null,q:"",hk:""});go();});
  document.querySelectorAll("[data-fh]").forEach(b=>{const f=()=>{V=Object.assign(V,{hk:b.dataset.fh,stage:"",flag:"",term:"",whoKey:null,q:""});go();};b.onclick=f;b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f();}};});
  document.querySelectorAll("[data-whokey]").forEach(b=>{const f=()=>{V=Object.assign(V,{whoKey:b.dataset.whokey,stage:"",flag:"",term:"",q:"",hk:""});go();};b.onclick=f;b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();f();}};});
  document.querySelectorAll("[data-who]").forEach(b=>b.onclick=()=>{V.who=b.dataset.who;V.whoKey=null;render();});
  document.querySelectorAll("[data-stg]").forEach(b=>b.onclick=()=>{V.stage=b.dataset.stg;render();});
  document.querySelectorAll("[data-clr]").forEach(b=>b.onclick=()=>{const k=b.dataset.clr;if(k==="whoKey")V.whoKey=null;else V[k]="";render();});
  document.querySelectorAll("[data-pos]").forEach(b=>b.onclick=()=>{const id=b.dataset.pos;V.open[id]=!V.open[id];const y=window.scrollY;render();window.scrollTo(0,y);});
  const q=$("kq");if(q){let t;q.oninput=()=>{clearTimeout(t);t=setTimeout(()=>{V.q=q.value.trim();render();const n=$("kq");n.focus();n.setSelectionRange(n.value.length,n.value.length);},200);};}
}
render();
})();
</script>'''


def page(doc):
    body = BODY.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
    head = '<title>Капитальный ремонт</title>\n' + fonts + '\n' + style + CSS
    if doc:
        return '<!DOCTYPE html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n' + head + '\n</head>\n<body>\n' + body + '\n</body>\n</html>\n'
    return head + '\n' + body


d = A.today.split('-')
out = ROOT / 'reports' / ('Капитальный ремонт %s.%s.%s.html' % (d[2], d[1], d[0]))
out.parent.mkdir(exist_ok=True)
out.write_text(page(True), encoding='utf-8')
(ROOT / 'capital').mkdir(exist_ok=True)
(ROOT / 'capital' / 'kr.html').write_text(page(False), encoding='utf-8')
(ROOT / 'capital' / 'kr.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
print(out.name, round(out.stat().st_size / 1024), 'КБ;', len(pos), 'позиций;', data['houses'], 'домов', ('; в реестре подтоплений: %d позиций' % sum(1 for p in data['positions'] if p['flood'])) if A.flood else '')
