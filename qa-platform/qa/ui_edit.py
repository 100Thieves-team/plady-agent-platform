"""폼 편집(스크립트·수동 작성 테스트 조건)과 Hermes 작업 진행 화면. docs/qa-platform-editor.md · docs/qa-platform-progress.md.

ui.py 가 맨 끝에서 이 모듈의 이름을 다시 내보낸다(app 은 ui.editor_page 처럼 쓴다). 공통 도우미는 ui 에서 가져온다.
"""
from __future__ import annotations

import json

from .ui import badge, e, h, kst

EDITOR_JS_VERSION = "7"
JOBS_JS_VERSION = "1"

EDIT_CSS = """
.g2{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 14px}@media(max-width:700px){.g2,.g3{grid-template-columns:1fr}}
.step h4{font-size:13px;margin:14px 0 6px;color:var(--gray)}.step .callhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.chip{background:var(--graybg);border-radius:999px;padding:2px 10px}.chip a{color:var(--mut);margin-left:4px}
.rows td{padding:3px 4px;border:0}.rows input{width:100%}.bf td{padding:4px 6px;vertical-align:top}.bf input,.bf select{width:100%}.bf .nm{white-space:nowrap}
.stages{list-style:none;padding:0;margin:8px 0}.stages li{padding:3px 0}.stages li.cur{font-weight:600}
pre.jobtext{max-height:420px;white-space:pre-wrap;word-break:break-word}
"""


# ---------------------------------------------------------------------------------------------
# 스크립트 폼
# ---------------------------------------------------------------------------------------------
def editor_page(st: dict, *, mode: str, original_id: str | None, draft_id: str | None, errors: list | None = None,
                warnings: list | None = None, operator: str = "", operators: list | None = None) -> str:
    title = {"new": "새 스크립트", "edit": f"스크립트 고치기 — {original_id}", "draft": f"폼으로 담은 것 저장하기 — {draft_id}"}.get(mode, "스크립트 폼")
    msgs = "".join(f'<li style="color:var(--bad)">{e(x)}</li>' for x in errors or []) + "".join(f'<li style="color:var(--warn)">{e(x)}</li>' for x in warnings or [])
    back = (f'<a href="/cases/{e(original_id)}">스크립트로 돌아가기</a>' if mode == "edit" else
            (f'<a href="/drafts/{e(draft_id)}">변경 기록으로</a>' if mode == "draft" else '<a href="/cases">스크립트 목록</a>'))
    ed = {"mode": mode, "original_id": original_id, "draft_id": draft_id}
    return (f'<style>{EDIT_CSS}</style>'
            f'<h1>{e(title)}{h("editor.form")} <span class="small mut">저장하면 검사를 거쳐 main 에 바로 커밋되고 실행 스위트에 들어간다</span></h1>'
            f'{("<div class=\"card\"><b>저장하지 않았다</b><ul style=\"margin:6px 0 0\">" + msgs + "</ul></div>") if msgs else ""}'
            f'<form id="ed" method="post" action="/editor/save">'
            f'<input type="hidden" name="operator" value="{e(operator)}"><input type="hidden" name="mode" value="{e(mode)}">'
            f'<input type="hidden" name="original_id" value="{e(original_id or "")}"><input type="hidden" name="draft_id" value="{e(draft_id or "")}">'
            f'<input type="hidden" name="state" id="ed-state-in">'
            f'<div id="ed-root"><div class="card mut">폼을 불러오는 중… (JavaScript 가 필요하다)</div></div>'
            f'<div class="actions"><button type="button" id="ed-add">+ 단계 추가</button></div>'
            f'<div class="card"><h3 style="margin-top:0">검사와 YAML 미리보기{h("editor.preview")}</h3>'
            f'<p class="small mut" style="margin-top:0">저장 전에 서버가 하는 검사(형식·테스트 조건 대조·테스트 계정·픽스처·본문 스키마)를 미리 돌리고, 저장될 YAML 을 보여 준다.</p>'
            f'<button type="button" id="ed-preview">검사하고 YAML 보기</button><ul id="ed-msgs" class="small"></ul><pre id="ed-yaml" style="display:none"></pre></div>'
            f'<div class="actions"><button class="primary" {"" if operator else "disabled title=\"담당자를 먼저 고르세요\""}>저장</button>'
            f'<button type="button" id="ed-try" {"" if operator else "disabled title=\"담당자를 먼저 고르세요\""}>저장 전에 한 번 실행해 보기 (dev)</button>{h("editor.try")} {back}</div>'
            f'<p id="ed-try-msg" class="small mut"></p></form>'
            f'<datalist id="dl-ops"></datalist><datalist id="dl-tcs"></datalist><datalist id="dl-vars"></datalist><datalist id="dl-variants"></datalist>'
            f'<script id="ed-state" type="application/json">{json.dumps(st, ensure_ascii=False).replace("</", "<\\/")}</script>'
            f'<script>window.ED={json.dumps(ed, ensure_ascii=False)}</script><script src="/static/editor.js?v={EDITOR_JS_VERSION}" defer></script>')


EDITOR_JS = r"""
(function(){
  var el=document.getElementById('ed-state'); if(!el) return;
  var S=JSON.parse(el.textContent), ED=window.ED||{}, CTX={ops:[],tcs:[],actors:[],fixtures:[],setups:[],variants:[]}, OPINFO={}, VIEW={};
  var root=document.getElementById('ed-root');
  S.steps=S.steps&&S.steps.length?S.steps:[blankStep()];
  S.uses=S.uses||{setup:'',with:{}};S.uses.with=S.uses.with||{};
  function blankStep(){return {name:'',actor:'',covers:[],method:'GET',path:'',query:[],body:'',expect:{status:'',result:'',error_code:'',json:[],exists:[]},save:[]}}
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  function getP(p){var o=S;p.split('.').forEach(function(k){o=(o==null)?undefined:o[k]});return o}
  function setP(p,v){var ks=p.split('.'),o=S;for(var i=0;i<ks.length-1;i++){o=o[ks[i]]}o[ks[ks.length-1]]=v}
  function help(k){return '<button type="button" class="help" data-help="'+k+'">?</button>'}
  function inp(p,ph,extra){return '<input data-k="'+p+'" value="'+esc(getP(p))+'" placeholder="'+esc(ph||'')+'" '+(extra||'')+'>'}
  function fld(label,html,hint,req){return '<div class="field"><label'+(req?' class="req"':'')+'>'+label+'</label>'+html+(hint?'<p class="hint">'+hint+'</p>':'')+'</div>'}
  function sel(p,opts,blank){var v=getP(p)||'';return '<select data-k="'+p+'">'+(blank!=null?'<option value="">'+esc(blank)+'</option>':'')+opts.map(function(o){var a=typeof o==='string'?[o,o]:o;return '<option value="'+esc(a[0])+'"'+(a[0]===v?' selected':'')+'>'+esc(a[1])+'</option>'}).join('')+'</select>'}
  function lst(p,ph){return '<input data-list="'+p+'" value="'+esc((getP(p)||[]).join(', '))+'" placeholder="'+esc(ph||'')+'">'}
  function chips(p){var a=getP(p)||[];return '<div class="chips">'+a.map(function(t,i){return '<span class="chip mono">'+esc(t)+'<a href="#" data-rmchip="'+p+'" data-i="'+i+'">×</a></span>'}).join('')+'<input list="dl-tcs" data-chip="'+p+'" placeholder="테스트 조건 id 나 제목으로 검색해 추가" style="min-width:260px"></div>'}
  function rows(p,cols){var a=getP(p)||[];var h='<table class="rows">'+a.map(function(r,j){return '<tr>'+cols.map(function(c){
      if(c[2]==='chk') return '<td style="width:60px"><label class="small"><input type="checkbox" data-k="'+p+'.'+j+'.'+c[0]+'"'+(r[c[0]]?' checked':'')+'> '+c[1]+'</label></td>';
      return '<td><input data-k="'+p+'.'+j+'.'+c[0]+'" value="'+esc(r[c[0]])+'" placeholder="'+esc(c[1])+'" list="'+(c[2]||'')+'"></td>'}).join('')+'<td style="width:30px"><button type="button" data-rmrow="'+p+'" data-i="'+j+'">×</button></td></tr>'}).join('')+'</table>';
    return h+'<button type="button" class="small" data-addrow="'+p+'" data-cols="'+cols.map(function(c){return c[0]}).join(',')+'">+ 추가</button>'}
  function segs(t){return t.split('/').filter(Boolean)}
  function matchPath(tpl,path){var a=segs(tpl.split('?')[0]),b=segs((path||'').split('?')[0]);if(a.length!==b.length)return false;for(var i=0;i<a.length;i++){if(a[i].charAt(0)==='{'&&a[i].slice(-1)==='}'){if(!b[i])return false;continue}if(b[i].indexOf('{{')===0)return false;if(a[i]!==b[i])return false}return true}
  function opOf(s){for(var i=0;i<CTX.ops.length;i++){var o=CTX.ops[i];if(o.method===s.method&&s.path&&matchPath(o.path,s.path))return o.id}return ''}
  function vars(){var v=[];(CTX.fixtures||[]).forEach(function(k){v.push('{{fixture.'+k+'}}')});(CTX.actors||[]).forEach(function(a){v.push('{{actor.'+a+'.memberId}}')});
    usedOuts().forEach(function(n){v.push('{{'+n+'}}')});
    S.steps.forEach(function(s){(s.save||[]).forEach(function(r){if(r.name)v.push('{{'+r.name+'}}')})});(S.inputs||[]).forEach(function(r){if(r.name)v.push('{{input.'+r.name+'}}')});
    return v.concat(['{{date:+7}}','{{rand}}','{{uuid}}'])}
  function card(id){for(var i=0;i<(CTX.setups||[]).length;i++){if(CTX.setups[i].id===id)return CTX.setups[i]}return null}
  function usedOuts(){var c=card(S.uses.setup);return c?c.outputs:[]}
  function usesHtml(){var c=card(S.uses.setup),opts=(CTX.setups||[]).filter(function(x){return x.id!==S.id}).map(function(x){return [x.id,x.id+' — '+x.title]});
    var h=fld('테스트 데이터 만들기 카드'+help('editor.uses'),sel('uses.setup',opts,'없음 (처음부터 단계를 적는다)'),c?'이 카드의 단계 '+c.steps+'개를 먼저 돈다. 결과값 '+c.outputs.map(function(n){return '{{'+n+'}}'}).join(' ')+' 을 아래 단계에서 쓴다. 전제 단계가 실패하면 판정은 오류다':'룸 만들기·신청 같은 준비 단계를 테스트 데이터 만들기 카드로 대신한다');
    if(S.uses.setup&&!c)h+='<p class="hint bad">카드 '+esc(S.uses.setup)+' 가 지금 목록에 없다</p>';
    if(c&&c.inputs.length)h+='<table class="bf">'+c.inputs.map(function(f){return '<tr><td class="nm'+(f.required&&(f['default']==null||f['default']==='')?' req':'')+'">'+esc(f.label)+' <span class="mono small mut">'+esc(f.name)+'</span></td><td><input data-k="uses.with.'+esc(f.name)+'" value="'+esc(S.uses.with[f.name]==null?'':S.uses.with[f.name])+'" list="dl-vars" placeholder="'+esc(f['default']==null?'':'기본값 '+f['default'])+'">'+(f.hint?'<div class="hint">'+esc(f.hint)+'</div>':'')+'</td></tr>'}).join('')+'</table>';
    return h}
  function variantHint(){var v=null;(CTX.variants||[]).forEach(function(x){if(x.id===S.variant)v=x});
    if(!S.variant)return '시나리오 화면의 케이스 하나. 비우면 시나리오에 연결되지 않은 스크립트가 된다';if(!v)return '<span class="bad">시나리오 파일에 없는 케이스다</span>';
    return esc(v.title)+(v.checks.length?' · 확인할 테스트 조건 '+v.checks.map(esc).join(' '):'')}
  function refreshVars(){document.getElementById('dl-vars').innerHTML=vars().map(function(x){return '<option value="'+esc(x)+'">'}).join('')}
  function parseBody(s){var t=(s.body||'').trim();if(!t)return {};try{var o=JSON.parse(t);return (o&&typeof o==='object'&&!Array.isArray(o))?o:null}catch(e){return null}}
  function getIn(o,name){return name.split('.').reduce(function(a,k){return a==null?undefined:a[k]},o)}
  function setIn(o,name,v){var ks=name.split('.'),c=o;for(var i=0;i<ks.length-1;i++){if(c[ks[i]]==null||typeof c[ks[i]]!=='object')c[ks[i]]={};c=c[ks[i]]}
    if(v===undefined){delete c[ks[ks.length-1]];if(ks.length>1&&!Object.keys(c).length)setIn(o,ks.slice(0,-1).join('.'),undefined)}else c[ks[ks.length-1]]=v}
  function conv(v,t){if(v==='')return undefined;if(v.indexOf('{{')===0)return v;if(t==='number'||t==='integer')return /^-?\d+(\.\d+)?$/.test(v)?Number(v):v;
    if(t==='boolean')return v==='true'?true:(v==='false'?false:v);if(t==='array'||t==='object'){try{return JSON.parse(v)}catch(e){return v}}return v}
  function show(v){return v===undefined?'':(typeof v==='object'?JSON.stringify(v):String(v))}
  var WHEN=/\b([A-Z][A-Z0-9_]+)\s*일 때/;
  function bfRows(i,fields,o,prefix){return fields.map(function(f){var name=prefix+f.name;
      if(f.fields&&f.fields.length)return '<tr><td class="nm mono'+(f.required?' req':'')+'" colspan="2">'+esc(name)+' <span class="small mut">'+esc(f.description||'')+'</span></td></tr>'+bfRows(i,f.fields,o,name+'.');
      var v=getIn(o,name),ctl,attrs=' data-bf="'+i+'" data-name="'+esc(name)+'" data-type="'+esc(f.type)+'"';
      if(f.enum&&f.enum.length)ctl='<select'+attrs+'><option value="">(보내지 않음)</option>'+f.enum.map(function(x){return '<option'+(show(v)===x?' selected':'')+'>'+esc(x)+'</option>'}).join('')+'</select>';
      else if(f.type==='boolean')ctl='<select'+attrs+'><option value="">(보내지 않음)</option><option'+(v===true?' selected':'')+'>true</option><option'+(v===false?' selected':'')+'>false</option></select>';
      else ctl='<input'+attrs+' value="'+esc(show(v))+'" list="dl-vars" placeholder="'+(f.required?'필수':'비우면 보내지 않음')+'">';
      var m=WHEN.exec(f.description||''),warn='';
      if(m&&v!==undefined&&JSON.stringify(o).indexOf('"'+m[1]+'"')<0)warn='<div class="hint bad">'+m[1]+' 일 때만 쓰는 필드인데 본문에 '+m[1]+' 가 없다</div>';
      return '<tr><td class="nm mono'+(f.required?' req':'')+'">'+esc(name)+'</td><td>'+ctl+'<div class="hint">'+esc(f.type)+(f.description?' · '+esc(f.description):'')+'</div>'+warn+'</td></tr>'}).join('')}
  function bodyHtml(s,i,info){var hasF=info&&info.body_fields&&info.body_fields.length;var view=VIEW[i]||(hasF?'fields':'json');
    var h='<h4>본문'+help('editor.body')+' <span class="seg">'+(hasF?'<button type="button" data-bv="'+i+'" data-v="fields" class="'+(view==='fields'?'on':'')+'">필드</button>':'')+'<button type="button" data-bv="'+i+'" data-v="json" class="'+(view==='json'?'on':'')+'">JSON</button></span>'
      +(hasF?' <button type="button" class="small" data-fillreq="'+i+'">필수 필드만 채우기</button>':'')+'</h4>';
    if(view==='json'||!hasF)return h+'<textarea data-k="steps.'+i+'.body" rows="12" class="mono" placeholder="{ } — 비우면 본문 없이 보낸다">'+esc(s.body)+'</textarea>';
    var o=parseBody(s);if(o===null)return h+'<p class="hint bad">본문이 JSON 객체가 아니라 필드로 볼 수 없다 — JSON 보기에서 고친다</p>';
    var known={};(function walk(fs,p){fs.forEach(function(f){known[p+f.name]=1;if(f.fields)walk(f.fields,p+f.name+'.')})})(info.body_fields,'');
    var extra=Object.keys(o).filter(function(k){return !known[k]&&!(o[k]&&typeof o[k]==='object')});
    return h+'<p class="small mut" style="margin:0 0 6px">필수 필드는 빨간 점. 비워 둔 칸은 본문에서 빠진다. 설명은 OpenAPI 스키마 그대로다.</p><table class="bf">'+bfRows(i,info.body_fields,o,'')+'</table>'
      +(extra.length?'<p class="hint bad">스키마에 없는 필드: '+esc(extra.join(', '))+' — JSON 보기에서 지운다</p>':'')}
  function tryUrl(s){var q=new URLSearchParams();var op=opOf(s);if(op)q.set('op',op);if(s.actor||S.actor)q.set('actor',s.actor||S.actor);if(s.body)q.set('body',s.body);return '/explorer?'+q.toString()}
  function stepHtml(s,i){var info=OPINFO[opOf(s)]||null,n=S.steps.length;
    var h='<div class="card step"><div class="callhead"><b>단계 '+(i+1)+(s.name?' — '+esc(s.name):'')+'</b><span>'
      +(i>0?'<button type="button" data-act="up" data-i="'+i+'">↑</button> ':'')+(i<n-1?'<button type="button" data-act="down" data-i="'+i+'">↓</button> ':'')
      +'<button type="button" data-act="dup" data-i="'+i+'">복제</button> '+(n>1?'<button type="button" class="danger" data-act="del" data-i="'+i+'">삭제</button>':'')+'</span></div>';
    h+='<div class="g2">'+fld('이름',inp('steps.'+i+'.name','예: 룸 생성'))+fld('테스트 계정',sel('steps.'+i+'.actor',CTX.actors,'기본 계정'+(S.actor?' ('+S.actor+')':' (없음)')),'비우면 위의 기본 테스트 계정으로 부른다')+'</div>';
    h+=fld('API'+help('editor.api'),'<input list="dl-ops" data-op="'+i+'" placeholder="operationId 나 경로로 검색" value="'+esc(opOf(s))+'">',info?esc(info.method+' '+info.path+' — '+(info.summary||'')):'고르면 메서드·경로·본문 필드가 채워진다');
    h+='<div class="g2">'+fld('메서드',sel('steps.'+i+'.method',['GET','POST','PUT','PATCH','DELETE']))+fld('경로',inp('steps.'+i+'.path','/v1/rooms/{{roomId}}','class="mono" list="dl-vars"'),'앞 단계에서 저장한 값은 {{이름}} 으로 쓴다',true)+'</div>';
    h+='<h4>쿼리</h4>'+rows('steps.'+i+'.query',[['k','이름'],['v','값','dl-vars']]);
    if(s.method!=='GET'||s.body)h+=bodyHtml(s,i,info);
    h+='<h4>기대 결과'+help('editor.expect')+'</h4><div class="g3">'+fld('상태 코드',inp('steps.'+i+'.expect.status','200','list="dl-st-'+i+'"'))
      +fld('result',sel('steps.'+i+'.expect.result',['SUCCESS','ERROR'],'검사 안 함'))+fld('오류 코드',inp('steps.'+i+'.expect.error_code','E1402','list="dl-er-'+i+'"'),info&&info.errors.length?'스펙에 나온 코드: '+info.errors.map(function(x){return x.code}).join(' '):'')+'</div>'
      +'<datalist id="dl-st-'+i+'">'+(info?info.statuses:[]).map(function(x){return '<option value="'+esc(x)+'">'}).join('')+'</datalist>'
      +'<datalist id="dl-er-'+i+'">'+(info?info.errors:[]).map(function(x){return '<option value="'+esc(x.code)+'">'+esc(x.status+' '+(x.message||''))+'</option>'}).join('')+'</datalist>'
      +'<div class="small mut">응답 값 검사 — 경로(data.status)와 기대값. 문자열은 그대로, 숫자·true·null 은 그 값으로 읽는다</div>'+rows('steps.'+i+'.expect.json',[['path','경로'],['value','기대값','dl-vars']])
      +fld('존재 검사',lst('steps.'+i+'.expect.exists','data.rooms, data.totalCount'),'쉼표로 여러 개 — 값이 있기만 하면 통과');
    h+='<h4>저장할 값'+help('editor.save')+'</h4>'+rows('steps.'+i+'.save',[['name','변수 이름 (roomId)'],['path','응답 경로 (data.roomId)']]);
    if(S.suite!=='setup')h+='<h4>이 단계가 검증하는 테스트 조건'+help('editor.covers')+'</h4>'+chips('steps.'+i+'.covers');
    return h+'<p class="small" style="margin:10px 0 0"><a href="'+esc(tryUrl(s))+'" target="_blank">이 단계만 API 호출 화면에서 보내 보기 ↗</a> <span class="mut">앞 단계 변수는 치환되지 않으니 값을 직접 넣는다</span></p></div>'}
  function basicHtml(){var edit=ED.mode==='edit';
    var h='<div class="card"><h3 style="margin-top:0">기본 정보'+help('editor.basic')+'</h3><div class="g2">'
      +fld('스위트'+help('cases.suite'),sel('suite',[['smoke','smoke — 읽기만'],['sanity','sanity — 쓰기 흐름, 만든 것은 정리'],['manual','manual — 손으로만 실행'],['setup','setup — 테스트 데이터 만들기 카드']]),'',true)
      +fld('id',inp('id','room.create','class="mono"'+(edit?' readonly':''))+(edit?'':' <button type="button" data-act="suggest" class="small">제안</button>'),edit?'고칠 때는 id 를 바꿀 수 없다':'도메인.영문-이름 (소문자·숫자·점·하이픈)',true)+'</div>'
      +fld('제목',inp('title','방장이 룸을 만들고 취소하면 CANCELED 가 된다'),'한국어 한 문장',true)
      +(S.suite==='setup'?'':fld('구현하는 케이스'+help('cases.variant'),inp('variant','룸-생성/S1/happy','class="mono" list="dl-variants"'),variantHint()))
      +fld('설명','<textarea data-k="description" rows="2">'+esc(S.description)+'</textarea>')
      +'<div class="g2">'+fld('도메인',lst('domains','room'),'API 를 고르면 자동으로 채워진다. 쉼표로 여러 개')+fld('기본 테스트 계정',sel('actor',CTX.actors,'없음 (로그인 안 함)'),'단계마다 따로 정할 수도 있다')+'</div>'
      +fld('출처',lst('source','PRD/룸 생성 §4.8'),'근거 문서. 쉼표로 여러 개')+usesHtml();
    if(S.suite!=='setup')h+=fld('검증하는 테스트 조건 (covers)'+help('editor.covers'),chips('covers'),'스크립트 전체가 검증하는 테스트 조건. 단계별 covers 는 각 단계 카드에서 — 둘을 합친 것이 이 스크립트의 covers 다',S.suite==='smoke'||S.suite==='sanity');
    return h+'</div>'}
  function setupHtml(){if(S.suite!=='setup')return '';var saved=usedOuts().slice();S.steps.forEach(function(s){(s.save||[]).forEach(function(r){if(r.name&&saved.indexOf(r.name)<0)saved.push(r.name)})});
    return '<div class="card"><h3 style="margin-top:0">테스트 데이터 만들기 카드'+help('editor.setup')+'</h3><div class="small mut">화면 입력칸 — 단계에서 {{input.이름}} 으로 쓴다</div>'
      +rows('inputs',[['name','이름 (title)'],['label','라벨'],['default','기본값'],['hint','도움말'],['required','필수','chk']])
      +'<div class="field" style="margin-top:10px"><label>끝나면 보여 줄 값 (outputs)</label>'+(saved.length?saved.map(function(n){return '<label class="radio"><input type="checkbox" data-out="'+esc(n)+'"'+((S.outputs||[]).indexOf(n)>=0?' checked':'')+'>'+esc(n)+'</label>'}).join(''):'<p class="hint">단계의 "저장할 값" 에 이름을 적으면 여기서 고를 수 있다</p>')+'</div></div>'}
  var KEYS=['k','bf','name','op','list','chip'];
  function render(){var a=document.activeElement,sel=null,pos=null;
    if(a&&root.contains(a)){sel=KEYS.filter(function(k){return a.dataset[k]!=null}).map(function(k){return '[data-'+k+'="'+String(a.dataset[k]).replace(/"/g,'\\"')+'"]'}).join('');try{pos=a.selectionStart}catch(e){}}
    root.innerHTML=basicHtml()+S.steps.map(stepHtml).join('')+setupHtml();refreshVars();
    if(sel){var b=root.querySelector(sel);if(b){b.focus();try{if(pos!=null)b.setSelectionRange(pos,pos)}catch(e){}}}}
  function loadOp(id){if(!id||OPINFO[id])return Promise.resolve(OPINFO[id]);return fetch('/api/editor/op/'+encodeURIComponent(id),{headers:{Accept:'application/json'}}).then(function(r){return r.ok?r.json():null}).then(function(j){if(j)OPINFO[id]=j;return j})}
  function fillRequired(i){var info=OPINFO[opOf(S.steps[i])];if(!info)return;var ex=info.example||{},o=parseBody(S.steps[i])||{};
    (function walk(fs,p,exo){fs.forEach(function(f){var nm=p+f.name;if(!f.required)return;if(f.fields){walk(f.fields,nm+'.',exo&&exo[f.name]);return}
      // 선택지가 있는 필드는 첫 선택지(ONLINE 등 기본형). 예시 값을 따르면 OFFLINE 처럼 다른 조건부 필드가 필요한 값이 들어온다
      if(getIn(o,nm)===undefined)setIn(o,nm,f.enum?f.enum[0]:(exo&&exo[f.name]!==undefined?exo[f.name]:(f.type==='boolean'?false:'')))})})(info.body_fields,'',ex);
    S.steps[i].body=JSON.stringify(o,null,2)}
  root.addEventListener('input',function(ev){var t=ev.target;
    if(t.dataset.k){setP(t.dataset.k,t.type==='checkbox'?t.checked:t.value);if(/\.(name)$/.test(t.dataset.k))refreshVars();return}
    if(t.dataset.list){setP(t.dataset.list,t.value.split(',').map(function(x){return x.trim()}).filter(Boolean));return}
    if(t.dataset.bf!=null){var i=+t.dataset.bf,o=parseBody(S.steps[i]);if(o===null)return;setIn(o,t.dataset.name,conv(t.value,t.dataset.type));S.steps[i].body=Object.keys(o).length?JSON.stringify(o,null,2):'';return}});
  root.addEventListener('change',function(ev){var t=ev.target;
    if(t.dataset.k==='uses.setup'){S.uses.with={};render();return}
    if(t.dataset.k==='variant'){render();return}
    if(t.dataset.k==='suite'||t.dataset.k==='actor'||/\.method$/.test(t.dataset.k||'')){render();return}
    if(t.dataset.bf!=null){var i=+t.dataset.bf,o=parseBody(S.steps[i]);if(o!==null){setIn(o,t.dataset.name,conv(t.value,t.dataset.type));S.steps[i].body=Object.keys(o).length?JSON.stringify(o,null,2):''}
      setTimeout(render,0);return}      // 다음 칸으로 포커스가 옮겨 간 뒤 다시 그린다 — 조건부 필드 경고를 갱신하고 커서는 지킨다
    if(t.dataset.out!=null){var a=S.outputs=S.outputs||[],n=t.dataset.out,k=a.indexOf(n);if(t.checked&&k<0)a.push(n);if(!t.checked&&k>=0)a.splice(k,1);return}
    if(t.dataset.chip){var v=t.value.trim();if(v){var a2=getP(t.dataset.chip)||[];if(a2.indexOf(v)<0)a2.push(v);setP(t.dataset.chip,a2)}render();return}
    if(t.dataset.op!=null){var i=+t.dataset.op,id=t.value.trim(),o=null;CTX.ops.forEach(function(x){if(x.id===id)o=x});if(!o)return;var s=S.steps[i];
      s.method=o.method;s.path=o.path.replace(/\{([^}]+)\}/g,'{{$1}}');if(!s.name)s.name=o.summary||o.id;
      loadOp(o.id).then(function(info){if(info&&(!S.domains||!S.domains.length)&&info.domain)S.domains=[info.domain];if(info&&s.method!=='GET'&&!(s.body||'').trim()&&info.body_fields.length)fillRequired(i);render()})}});
  root.addEventListener('click',function(ev){var t=ev.target.closest('button,a');if(!t||!root.contains(t))return;var d=t.dataset;
    if(d.rmchip){ev.preventDefault();var a=getP(d.rmchip);a.splice(+d.i,1);render();return}
    if(d.rmrow){getP(d.rmrow).splice(+d.i,1);render();return}
    if(d.addrow){var a3=getP(d.addrow);if(!a3){setP(d.addrow,[]);a3=getP(d.addrow)}var r={};d.cols.split(',').forEach(function(c){r[c]=''});a3.push(r);render();return}
    if(d.bv!=null){VIEW[+d.bv]=d.v;render();return}
    if(d.fillreq!=null){fillRequired(+d.fillreq);render();return}
    if(d.act){var i=+d.i,st=S.steps;
      if(d.act==='up'){st.splice(i-1,0,st.splice(i,1)[0])}else if(d.act==='down'){st.splice(i+1,0,st.splice(i,1)[0])}
      else if(d.act==='dup'){st.splice(i+1,0,JSON.parse(JSON.stringify(st[i])))}else if(d.act==='del'){if(confirm('단계 '+(i+1)+' 을 지울까요?'))st.splice(i,1)}
      else if(d.act==='suggest'){var op=opOf(st[0]||{})||'new';S.id=((S.domains&&S.domains[0])||'misc')+'.'+op.replace(/([a-z0-9])([A-Z])/g,'$1-$2').toLowerCase().replace(/[^a-z0-9]+/g,'-')}
      render();return}});
  document.getElementById('ed-add').addEventListener('click',function(){S.steps.push(blankStep());render();window.scrollTo(0,document.body.scrollHeight)});
  document.getElementById('ed-preview').addEventListener('click',function(){var b=this;b.disabled=true;
    fetch('/api/editor/preview',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({state:S,mode:ED.mode,original_id:ED.original_id,draft_id:ED.draft_id})})
    .then(function(r){return r.json()}).then(function(j){var m=document.getElementById('ed-msgs'),y=document.getElementById('ed-yaml');
      m.innerHTML=(j.errors||[]).map(function(x){return '<li style="color:var(--bad)">'+esc(x)+'</li>'}).join('')+(j.warnings||[]).map(function(x){return '<li style="color:var(--warn)">'+esc(x)+'</li>'}).join('')+(j.ok&&!(j.warnings||[]).length?'<li style="color:var(--ok)">검사 통과</li>':'');
      y.style.display=j.yaml?'block':'none';y.textContent=j.yaml||''}).catch(function(e){alert('검사 실패: '+e)}).then(function(){b.disabled=false})});
  document.getElementById('ed').addEventListener('submit',function(){document.getElementById('ed-state-in').value=JSON.stringify(S)});
  var tryB=document.getElementById('ed-try');
  if(tryB) tryB.addEventListener('click',function(){var b=this,msg=document.getElementById('ed-try-msg');b.disabled=true;msg.textContent='dev 에 보내는 중…';
    var w=window.open('about:blank','_blank');
    fetch('/editor/try',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({state:S,mode:ED.mode,original_id:ED.original_id,draft_id:ED.draft_id,operator:document.querySelector('#ed input[name=operator]').value})})
    .then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||j.message||('HTTP '+r.status));return j})})
    .then(function(j){msg.innerHTML='실행 기록 <a href="'+esc(j.url)+'" target="_blank">'+esc(j.run_id)+'</a> — 저장하지 않았다';if(w)w.location=j.url})
    .catch(function(e){if(w)w.close();msg.textContent='실행하지 못했다: '+e.message}).then(function(){b.disabled=false})});
  render();
  fetch('/api/editor/context',{headers:{Accept:'application/json'}}).then(function(r){return r.json()}).then(function(c){CTX=c;
    document.getElementById('dl-ops').innerHTML=c.ops.map(function(o){return '<option value="'+esc(o.id)+'">'+esc(o.method+' '+o.path+' — '+(o.summary||''))+'</option>'}).join('');
    document.getElementById('dl-variants').innerHTML=(c.variants||[]).map(function(v){return '<option value="'+esc(v.id)+'">'+esc(v.title)+'</option>'}).join('');
    document.getElementById('dl-tcs').innerHTML=c.tcs.map(function(t){return '<option value="'+esc(t.id)+'">'+esc('['+t.layer+'] '+t.title)+'</option>'}).join('');
    return Promise.all(S.steps.map(function(s){return loadOp(opOf(s))}))}).then(render);
})();
"""


# ---------------------------------------------------------------------------------------------
# 수동 작성 TC 폼
# ---------------------------------------------------------------------------------------------
def manual_tc_form(rec: dict | None, *, docs: list, domains: list, ops: list, prefill: dict, operator: str) -> str:
    edit = rec is not None
    r = rec or {}
    v = lambda k: r.get(k) if edit else (prefill.get(k) or "")  # noqa: E731
    dl_docs = "".join(f'<option value="{e(d)}">' for d in docs)
    dl_ops = "".join(f'<option value="{e(o["id"])}">{e(o["method"] + " " + o["path"])}</option>' for o in ops)
    doms = "".join(f'<option value="{e(d)}" {"selected" if d == v("domain") else ""}>{e(d)}</option>' for d in sorted(set(domains) | {"other"}))
    dis = "" if operator else 'disabled title="담당자를 먼저 고르세요"'
    if edit:
        where = (f'<div class="kv"><div>id</div><div class="mono">{e(r["id"])}</div>'
                 + (f'<div>PRD</div><div>{e(r.get("doc"))} §{e(r.get("section"))}</div>' if r.get("doc") else "") + '</div>'
                 f'<input type="hidden" name="id" value="{e(r["id"])}"><input type="hidden" name="doc" value="{e(r.get("doc") or "")}">'
                 f'<input type="hidden" name="section" value="{e(r.get("section") or "")}">')
    else:
        where = (f'<div class="field"><label>어디서 온 확인 항목인가</label>'
                 f'<label class="radio"><input type="radio" name="tc_kind" value="prd" checked onchange="document.getElementById(\'k-prd\').style.display=\'\';document.getElementById(\'k-ops\').style.display=\'none\'">PRD 절</label>'
                 f'<label class="radio"><input type="radio" name="tc_kind" value="ops" onchange="document.getElementById(\'k-prd\').style.display=\'none\';document.getElementById(\'k-ops\').style.display=\'\'">운영 기준 (기획 문서 밖)</label></div>'
                 f'<div id="k-prd" class="g2"><div class="field"><label class="req">PRD 문서</label><input name="doc" list="dl-docs" value="{e(v("doc"))}" placeholder="룸 생성"></div>'
                 f'<div class="field"><label class="req">절 번호</label><input name="section" value="{e(v("section"))}" placeholder="4.2"></div></div>'
                 f'<div id="k-ops" style="display:none"><div class="field"><label class="req">id 앞부분</label><input name="ops_id" placeholder="OPS.platform.health" class="mono"><p class="hint">OPS.영역.이름 — 번호(#n)는 저장 때 붙는다</p></div>'
                 f'<div class="field"><label>근거</label><input name="source" placeholder="운영 기준이 적힌 곳 (예: 릴리스 체크리스트)"></div></div>'
                 f'<p class="hint">id 는 PRD.문서.절#번호 로 저장 때 자동으로 붙는다. 같은 절의 다음 번호다.</p>')
    delete = ""
    if edit:
        delete = (f'<form method="post" action="/catalog/tc/delete" class="card" onsubmit="return confirm(\'{e(r["id"])} 를 지운다. manual-tc.yaml 에서 바로 빠진다.\')">'
                  f'<h3 style="margin-top:0">이 테스트 조건 지우기{h("tc.delete")}</h3>'
                  f'<input type="hidden" name="id" value="{e(r["id"])}"><input type="hidden" name="operator" value="{e(operator)}">'
                  f'<p class="small mut">누르면 manual-tc.yaml 에서 바로 빠진다. 이 테스트 조건을 검증하는 스크립트가 있으면 막힌다.</p>'
                  f'<input name="reason" placeholder="사유 (선택, 커밋 메시지에 남는다)" style="width:60%"> <button class="danger" {dis}>지우기</button></form>')
    return (f'<style>{EDIT_CSS}</style><h1>{"수동 작성 테스트 조건 고치기" if edit else "수동 작성 테스트 조건 추가"}{h("tc.manual_form")}</h1>'
            f'<p class="small mut">SSOT 로 형식화되지 않은 PRD 요구나 운영 기준을 사람이 테스트 조건으로 적는다. 저장하면 <span class="mono">catalog/manual-tc.yaml</span> 에 바로 커밋된다.</p>'
            f'<form method="post" action="/catalog/manual/save" class="card"><input type="hidden" name="operator" value="{e(operator)}">{where}'
            f'<div class="g2"><div class="field"><label class="req">도메인</label><select name="domain">{doms}</select></div>'
            f'<div class="field"><label>관련 API</label><input name="operations" list="dl-ops2" value="{e(", ".join(r.get("operations") or []))}" placeholder="operationId, 쉼표로" class="mono"></div></div>'
            f'<div class="field"><label class="req">제목</label><input name="title" value="{e(v("title"))}" placeholder="~할 수 있다 / ~이다 꼴 한 문장" required></div>'
            f'<div class="field"><label>given (전제)</label><textarea name="given" rows="2">{e(v("given"))}</textarea></div>'
            f'<div class="field"><label class="req">when (요청이나 행동)</label><textarea name="when" rows="2" required>{e(v("when"))}</textarea></div>'
            f'<div class="field"><label class="req">then (기대 결과)</label><textarea name="then" rows="2" required>{e(v("then"))}</textarea></div>'
            f'<div class="actions"><button class="primary" {dis}>저장</button> <a href="/catalog">테스트 조건 목록</a></div></form>{delete}'
            f'<datalist id="dl-docs">{dl_docs}</datalist><datalist id="dl-ops2">{dl_ops}</datalist>')


# ---------------------------------------------------------------------------------------------
# Hermes 작업 진행
# ---------------------------------------------------------------------------------------------
def job_detail(snap: dict, *, operator: str) -> str:
    terminal = snap["status"] in ("done", "failed", "canceled", "interrupted")
    stages = "".join(f'<li>{"✅" if (snap["status"] == "done" or snap["stages"].index(s) < snap["stages"].index(snap["stage"])) else ("⏳" if s == snap["stage"] else "○")} {e(s)}</li>'
                     for s in snap["stages"]) if snap.get("stage") in snap["stages"] else ""
    links = "".join(f'<li><a href="{e(x["href"])}">{e(x["label"])}</a></li>' for x in (snap.get("result") or {}).get("links") or [])
    static = (f'<div class="card"><div><b>{e(snap["kind_ko"])}</b> · {e(snap.get("label") or "")} · {e(snap["operator"])} · {badge(snap["status_ko"])}</div>'
              f'<ul class="stages">{stages}</ul>'
              f'{("<p>" + e((snap.get("result") or {}).get("summary")) + "</p><ul>" + links + "</ul>") if snap.get("result") else ""}'
              f'{("<div class=\"flash err\">" + e(snap["error"]) + "</div>") if snap.get("error") else ""}'
              f'{("<pre class=\"jobtext\">" + e(snap.get("text")) + "</pre>") if snap.get("text") else ""}</div>')
    back = snap.get("back") or {}
    return (f'<style>{EDIT_CSS}</style><h1>Hermes 작업 <span class="mono">{e(snap["id"])}</span>{h("jobs.progress")}</h1>'
            f'{"" if terminal else "<noscript><meta http-equiv=\"refresh\" content=\"5\"></noscript>"}'
            f'<div data-job-id="{e(snap["id"])}">{static}</div>'
            f'<p class="small">{("<a href=\"" + e(back["href"]) + "\">" + e(back["label"]) + " 로 돌아가기</a> · ") if back.get("href") else ""}<a href="/jobs">Hermes 작업 목록</a></p>')


def jobs_list(rows: list[dict]) -> str:
    from .jobs import KINDS, STATUS_KO
    body = ""
    for r in rows:
        res = r.get("result") or {}
        links = " ".join(f'<a href="{e(x["href"])}">{e(x["label"])}</a>' for x in res.get("links") or [])
        body += (f'<tr><td><a href="/jobs/{e(r["id"])}" class="mono">{e(r["id"])}</a></td><td>{e(KINDS.get(r["kind"], r["kind"]))}</td><td class="small">{e(r.get("label"))}</td>'
                 f'<td>{e(r["operator"])}</td><td>{badge(STATUS_KO.get(r["status"], r["status"]))}</td><td class="small mut">{kst(r["created_at"])}</td>'
                 f'<td class="small">{links or e((r.get("error") or "")[:80])}</td></tr>')
    return (f'<h1>Hermes 작업{h("jobs.list")} <span class="small mut">스크립트 쓰기·테스트 조건 제안·고치기·실패 분석 — 누가 언제 돌렸고 어떻게 끝났나</span></h1>'
            f'<div class="card"><table><tr><th>작업</th><th>종류</th><th>대상</th><th>담당자</th><th>상태</th><th>시작</th><th>결과</th></tr>'
            f'{body or "<tr><td colspan=7 class=mut>아직 없다</td></tr>"}</table></div>')


def active_jobs_line(active: list[dict]) -> str:
    if not active:
        return ""
    items = " · ".join(f'<a href="/jobs/{e(j["id"])}">{e(j["kind_ko"])} {e(j.get("label") or "")}</a> <span class="small mut">{e(j["status_ko"])} · {e(j["stage"])}</span>' for j in active)
    return f'<div class="card" style="background:#fffbeb"><b>진행 중인 Hermes 작업</b>{h("jobs.progress")} {items}</div>'


JOBS_JS = r"""
(function(){
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  var TERM=['done','failed','canceled','interrupted'];
  function fmt(n){return (n||0).toLocaleString()}
  window.qaJob=function(id,root,opts){opts=opts||{};var S=null,text='',at=Date.now(),es=null,pre=null;
    function detail(){var inf=S.info||{},o=[];if(S.stage==='대기')o.push('앞에 '+(inf.queue_ahead||0)+'건');
      if(S.stage==='Hermes 에게 보냄'&&inf.prompt_chars)o.push('프롬프트 '+fmt(inf.prompt_chars)+'자');
      if(S.stage==='Hermes 가 쓰는 중'){o.push(fmt(inf.received_chars)+'자 받음');if(S.since_recv!=null)o.push('마지막 수신 '+(S.since_recv+Math.floor((Date.now()-at)/1000))+'초 전')}
      if(S.stage==='근거 모으기')o.push('테스트 조건·OpenAPI·PRD 절을 모은다');return o.join(' · ')}
    function elapsed(){if(S.elapsed==null)return '';var t=S.elapsed+(TERM.indexOf(S.status)<0&&S.status!=='queued'?Math.floor((Date.now()-at)/1000):0);return Math.floor(t/60)+':'+('0'+t%60).slice(-2)}
    function render(){if(!S)return;var term=TERM.indexOf(S.status)>=0,idx=S.stages.indexOf(S.stage);
      var st=S.stages.map(function(n,i){var ic=(S.status==='done'||i<idx)?'✅':(i===idx?(term?'❌':'⏳'):'○');var d=(i===idx&&!term)?detail():'';
        return '<li class="'+(i===idx&&!term?'cur':'')+'">'+ic+' '+esc(n)+(d?' <span class="small mut" style="font-weight:400">'+esc(d)+'</span>':'')+'</li>'}).join('');
      var tools=(S.info&&S.info.tools||[]).map(function(t){return '<span class="tc">'+esc(t)+'</span>'}).join('');
      var res=S.result||{},links=(res.links||[]).map(function(x){return '<a class="btn" href="'+esc(x.href)+'">'+esc(x.label)+'</a>'}).join(' ');
      root.innerHTML='<div class="card"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b>'+esc(S.kind_ko)+'</b><span>'+esc(S.label||'')+'</span><span class="small mut">'+esc(S.operator)+'</span>'
        +'<span class="b '+(S.status==='done'?'pass':(term?'fail':'running'))+'">'+esc(S.status_ko)+'</span><span class="small mut" data-el>'+elapsed()+(term?'':' / 한도 '+Math.floor(S.timeout/60)+'분')+'</span>'
        +(term?'':'<button type="button" data-cancel style="margin-left:auto">그만두기</button>')+'</div>'
        +'<ul class="stages">'+st+'</ul>'+(tools?'<div class="small mut">Hermes 가 부른 도구 '+tools+'</div>':'')
        +(S.status==='done'?'<p><b>'+esc(res.summary||'끝')+'</b></p><div class="actions">'+links+'</div>':'')
        +(S.error?'<div class="flash err">'+esc(S.error)+'</div>':'')
        +'<div class="small mut" style="margin-top:8px">Hermes 가 쓰는 글'+(term?'':' (받는 대로 보인다 — 검증 전이라 틀린 곳이 있을 수 있다)')+'</div><pre class="jobtext"></pre></div>';
      pre=root.querySelector('pre.jobtext');renderText();
      var cb=root.querySelector('[data-cancel]');if(cb)cb.onclick=function(){cb.disabled=true;fetch('/jobs/'+id+'/cancel',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({operator:(window.QA||{}).operator||''})})}}
    function renderText(){if(!pre)return;var stick=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-20;pre.textContent=text||'(아직 없음)';if(stick)pre.scrollTop=pre.scrollHeight}
    es=new EventSource('/api/jobs/'+id+'/events');
    es.addEventListener('snapshot',function(ev){S=JSON.parse(ev.data);text=S.text||'';at=Date.now();render()});
    es.addEventListener('state',function(ev){S=JSON.parse(ev.data);at=Date.now();render()});
    es.addEventListener('text',function(ev){text+=JSON.parse(ev.data).append;renderText()});
    es.addEventListener('end',function(ev){var s=JSON.parse(ev.data);if(s.text!=null)text=s.text;S=s;at=Date.now();render();es.close();if(opts.onEnd)opts.onEnd(S)});
    es.onerror=function(){if(S&&TERM.indexOf(S.status)>=0)es.close()};
    setInterval(function(){if(!S||TERM.indexOf(S.status)>=0)return;var el=root.querySelector('[data-el]');if(el)el.textContent=elapsed()+' / 한도 '+Math.floor(S.timeout/60)+'분';var c=root.querySelector('li.cur .small');if(c)c.textContent=detail()},1000)};
  function init(){
    document.querySelectorAll('[data-job-id]').forEach(function(el){qaJob(el.getAttribute('data-job-id'),el)});
    document.addEventListener('submit',function(ev){var f=ev.target;if(!f.hasAttribute||!f.hasAttribute('data-job-form'))return;ev.preventDefault();
      var b=f.querySelector('button');if(b)b.disabled=true;var box=document.createElement('div');box.style.marginTop='8px';f.parentNode.insertBefore(box,f.nextSibling);
      fetch(f.action,{method:'POST',headers:{'X-QA-Job':'1',Accept:'application/json','Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(f)).toString()})
      .then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||r.status);return j})})
      .then(function(j){qaJob(j.job,box,{onEnd:function(s){if(s.status==='done')setTimeout(function(){location.reload()},1200);else if(b)b.disabled=false}})})
      .catch(function(e){box.innerHTML='<div class="flash err">'+esc(e.message||e)+'</div>';if(b)b.disabled=false})});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
"""
