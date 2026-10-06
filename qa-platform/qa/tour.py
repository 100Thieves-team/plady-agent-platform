"""처음 쓰는 사람을 위한 둘러보기 — 게임 튜토리얼처럼 화면 위에 한 곳씩 짚어 가며 알려 준다 (사용자 요청 2026-09-27).

- 화면마다 단계 목록(TOURS). 단계는 {sel, title, body}. sel 은 CSS 선택자, 화면에 없으면 그 단계는 건너뛴다.
  sel 이 없으면 화면 가운데에 띄우는 안내다.
- 처음 들어온 화면에서 한 번 저절로 뜬다. 본 기록은 담당자별로 이 브라우저에만 남는다(localStorage qa_tour:<담당자>:<화면>).
- 왼쪽 메뉴 아래 [둘러보기]로 언제든 다시 본다. ←·→·Esc 로도 움직인다.
"""
from __future__ import annotations

import json

VERSION = "3"

TOURS: dict[str, list[dict]] = {
    "home": [
        {"title": "QA 플랫폼에 오신 걸 환영해요", "body": "dev 서버가 기획(PRD)과 규칙표대로 동작하는지 확인하는 곳이에요. 1분이면 둘러볼 수 있어요. 언제든 왼쪽 아래 [둘러보기]로 다시 볼 수 있어요."},
        {"sel": ".side a.nv[href$='/sanity']", "title": "① Sanity 테스트", "body": "PR 이 dev 에 머지되면 여기서 그 PR 을 골라 [Sanity 시작]을 눌러요. Hermes 가 관련 스펙을 찾아 테스트를 만들고 dev 에서 돌려요. 숫자는 확인할 PR 수예요."},
        {"sel": ".side a.nv[href$='/smoke']", "title": "② 스모크 테스트", "body": "스프린트마다 저장된 스크립트로 핵심 흐름 전체가 돌아가는지 한 번에 확인해요. 숫자는 돌릴 수 있는 스크립트 수예요."},
        {"sel": ".side a.nv[href$='/data']", "title": "③ QA 데이터", "body": "손으로 확인할 룸·신청·계정이 필요하면 여기서 버튼 하나로 만들고, 다 쓰면 지워요."},
        {"sel": "[data-tour=todo]", "title": "지금 할 일", "body": "검증하지 않은 PR, 스펙 확인이 필요한 PR, 이번 스프린트 스모크처럼 지금 챙길 일이 여기에 모여요. 오른쪽 버튼을 누르면 바로 그 일로 가요."},
        {"sel": "[data-tour=features]", "title": "기능별 테스트 준비", "body": "기능마다 케이스가 몇 개고 그중 몇 개를 스크립트로 확인하는지 보여요. 파란색이 늘어날수록 자동으로 확인하는 범위가 넓어요."},
        {"sel": ".side .sub", "title": "관리 화면", "body": "시나리오·스크립트·테스트 조건을 직접 고치거나 API 하나를 불러 볼 때 써요. 처음에는 위의 세 가지 일만 알면 돼요."},
        {"sel": "#hx-btn", "title": "막히면 Hermes 에게", "body": "어느 화면에서나 오른쪽 아래 버튼으로 Hermes 와 이야기할 수 있어요. 지금 보고 있는 화면을 알고 대답해요."},
        {"sel": "main .help", "title": "? 버튼", "body": "기능 옆의 ? 를 누르면 그 기능을 언제, 어떻게 쓰는지 설명이 떠요."},
    ],
    "sanity": [
        {"title": "Sanity 테스트", "body": "머지된 PR 하나가 스펙대로 동작하는지 확인해요. 사람은 PR 을 고르고 [Sanity 시작]만 누르면 돼요. 나머지는 Hermes 와 플랫폼이 해요."},
        {"sel": "[data-tour=prs]", "title": "PR 목록", "body": "dev 로 머지된 PR 이 최신순으로 있어요. API 나 동작 코드를 바꾼 PR 이 위에, 시험·문서·인프라만 바꾼 PR 은 흐리게 아래에 있어요. 응답·요청 DTO 만 바꿔도 API 변경으로 봐요. 오른쪽 표시로 검증했는지 알 수 있어요."},
        {"sel": "[data-tour=tabs]", "title": "거르기", "body": "검증 안 함 · 확인 필요 · 끝남 으로 거를 수 있어요."},
        {"sel": "[data-tour=start]", "title": "시작", "body": "누르면 확인 창이 떠요. 시작하면 관련 스펙 찾기 → 스펙 점검 → 케이스 준비 → 스크립트 만들기 → 실행 순서로 진행해요. 머지만으로는 저절로 시작하지 않아요."},
        {"sel": "[data-tour=steps]", "title": "다섯 단계", "body": "지금 어디까지 왔는지 보여요. 주황색 ! 는 사람이 정해야 해서 멈춘 곳이에요."},
        {"sel": "[data-tour=findings]", "title": "스펙 확인", "body": "스펙과 코드가 다른 곳, 스펙이 모호한 곳을 Hermes 와 플랫폼이 찾아요. [추천대로]나 [다르게]로 하나씩 정하거나, 위의 [이대로 계속]으로 남은 것을 두고 계속해요. 위키를 고쳤으면 [위키 고친 뒤 다시 점검]."},
        {"sel": "[data-tour=cases]", "title": "이번 범위의 케이스", "body": "이 PR 이 닿는 케이스예요. 스크립트가 없는 것은 Hermes 가 만들고, 검증을 통과하면 바로 저장돼요."},
    ],
    "smoke": [
        {"title": "스모크 테스트", "body": "저장된 스크립트로 핵심 흐름 전체가 돌아가는지 한 번에 확인해요. 스프린트마다 한 번, 릴리스 전에 한 번 돌리면 좋아요."},
        {"sel": "[data-tour=scope]", "title": "범위 고르기", "body": "기능별로 묶여 있어요. 줄을 누르면 스크립트가 펼쳐지고, 체크박스로 기능 전체나 스크립트 하나씩 뺄 수 있어요. 지난 결과도 함께 보여요."},
        {"sel": "[data-tour=mode]", "title": "지난번 실패만", "body": "고친 뒤 실패했던 것만 다시 돌릴 때 써요."},
        {"sel": "[data-tour=run]", "title": "실행", "body": "고른 개수와 예상 시간을 보고 [스모크 실행]. 확인 창에서 한 번 더 누르면 dev 에 실행돼요. 끝나면 Slack 으로 알려 주고, 결과 화면은 실패부터 보여 줘요."},
    ],
    "data": [
        {"title": "QA 데이터", "body": "손으로 확인할 테스트 데이터를 dev 에 만들고 지워요. 만든 데이터는 이름이 [QA] 로 시작해서 실제 데이터와 섞이지 않아요."},
        {"sel": "[data-tour=make]", "title": "만들기", "body": "필요한 상태를 고르세요. 모집 중인 룸, 신청이 들어온 룸, 진행 확정된 룸처럼 여러 API 를 순서대로 부르는 일을 버튼 하나로 해요."},
        {"sel": "[data-tour=make] .li", "title": "누르면 오른쪽 패널", "body": "넣을 값만 보여요. 기본값이 있으면 그대로 [만들기](⌘↵). 만든 뒤 roomId 같은 결과값을 복사하거나 바로 지울 수 있어요."},
        {"sel": "[data-tour=left]", "title": "남은 데이터 지우기", "body": "dev 에 남아 있는 [QA] 룸과 회원이에요. 하나씩 지우거나 [QA] 룸 전부 지우기. 테스트 계정 초기화는 그 계정의 룸·신청을 비워요."},
    ],
    "inbox": [
        {"title": "알림함", "body": "플랫폼이 테스트 계정의 웹 푸시 기기와 메일함이 돼요. 백엔드가 실제로 보낸 알림이 몇 초 안에 여기에 나타나요."},
        {"sel": "[data-tour=inbox-who]", "title": "받는 계정", "body": "[웹 푸시 받기]를 누르면 플랫폼이 그 계정의 기기로 등록돼요. 메일은 QA 회원 주소가 플랫폼 메일함 주소일 때 저절로 받아요."},
        {"sel": "[data-tour=inbox-list]", "title": "받은 알림", "body": "웹 푸시는 종 모양, 메일은 봉투 모양이에요. 채널·기간·종류로 걸러 보고, [원본 보기]로 받은 그대로를 봐요. 스크립트의 알림 기다리기 단계가 맞춘 알림은 실행 링크가 붙어요."},
    ],
    "catalog": [
        {"title": "테스트 조건", "body": "무엇을 확인해야 하는지 모은 목록이에요. 규칙표(SSOT)와 API 문서에서 저절로 나오고, 플랫폼은 옮겨 적기만 해요."},
        {"sel": "[data-tour=filters]", "title": "거르기", "body": "도메인 · 종류(비즈니스 규칙, API 계약, 수동 작성) · 자동화 여부로 걸러 봐요. 미자동화는 아직 확인하는 스크립트가 없는 조건이에요."},
        {"sel": "#tc-pick", "title": "고르기", "body": "[전부 선택]·[미자동화만 선택]·[선택 해제] 로 한 번에 골라요. 표 머리의 체크박스도 같아요. Hermes 는 한 번에 10개까지 받아요."},
        {"sel": "[data-tour=write]", "title": "스크립트 만들기", "body": "고른 조건으로 Hermes 가 스크립트를 쓰거나, 폼으로 직접 써요. 검증을 통과하면 바로 저장돼요."},
    ],
}


def tour_for(active: str) -> list[dict]:
    return TOURS.get({"dash": "home", "setup": "data"}.get(active, active), [])


JS = r"""
(function(){
  var T=window.QA_TOUR; if(!T||!T.steps||!T.steps.length) return;
  var OP=(window.QA&&window.QA.operator)||'', KEY='qa_tour:'+OP+':'+T.key+':v'+T.v;
  function seen(){ try{return localStorage.getItem(KEY)==='1'}catch(e){return true} }
  function mark(){ try{localStorage.setItem(KEY,'1')}catch(e){} }
  var css=document.createElement('style'); css.textContent=
   '.tour-shade{position:fixed;inset:0;z-index:90;background:rgba(25,31,40,.5)}'+
   '.tour-hole{position:fixed;z-index:91;border-radius:12px;box-shadow:0 0 0 9999px rgba(25,31,40,.55),0 0 0 3px #3182F6;pointer-events:none}'+
   '.tour-card{position:fixed;z-index:92;width:340px;background:#fff;border-radius:16px;padding:18px 20px 14px;box-shadow:0 16px 48px rgba(0,0,0,.25);font-size:14px;line-height:1.55}'+
   '.tour-card .n{font-size:12px;font-weight:700;color:#3182F6;margin-bottom:4px}.tour-card h4{margin:0 0 6px;font-size:17px}.tour-card p{margin:0;color:#4E5968}'+
   '.tour-card .dots{display:flex;gap:4px;margin:14px 0 12px}.tour-card .dots i{width:6px;height:6px;border-radius:50%;background:#E5E8EB}.tour-card .dots i.on{background:#3182F6;width:16px;border-radius:3px}'+
   '.tour-card .b{display:flex;gap:6px;align-items:center}.tour-card .b .sp{flex:1}.tour-card button{height:34px;padding:0 13px;border:0;border-radius:8px;font:inherit;font-size:13px;font-weight:700;cursor:pointer;background:#F2F4F6;color:#4E5968}'+
   '.tour-card button.go{background:#3182F6;color:#fff}.tour-card button.skip{background:transparent;color:#8B95A1;padding:0 4px}';
  document.head.appendChild(css);
  var steps=[], i=0, shade, hole, card;
  function build(){ steps=T.steps.filter(function(s){ if(!s.sel) return true; var el=document.querySelector(s.sel); return el && el.getClientRects().length; }); }
  function place(){
    var s=steps[i], el=s.sel?document.querySelector(s.sel):null;
    card.innerHTML='<div class="n">'+(i+1)+' / '+steps.length+'</div><h4></h4><p></p><div class="dots">'+steps.map(function(_,k){return '<i class="'+(k===i?'on':'')+'"></i>'}).join('')+'</div>'+
      '<div class="b"><button class="skip" data-t="end">'+(i===steps.length-1?'':'건너뛰기')+'</button><span class="sp"></span>'+(i?'<button data-t="prev">이전</button>':'')+'<button class="go" data-t="next">'+(i===steps.length-1?'시작하기':'다음')+'</button></div>';
    card.querySelector('h4').textContent=s.title; card.querySelector('p').textContent=s.body;
    if(!el){ hole.style.display='none'; shade.style.display='block';
      card.style.left=(innerWidth-340)/2+'px'; card.style.top=Math.max(40,(innerHeight-card.offsetHeight)/2)+'px'; return; }
    shade.style.display='none'; hole.style.display='block';
    var fixed=false; for(var n=el;n&&n!==document.body;n=n.parentElement){ if(getComputedStyle(n).position==='fixed'){ fixed=true; break; } }
    var r0=el.getBoundingClientRect();
    if(!fixed&&(r0.top<12||r0.bottom>innerHeight-12)) el.scrollIntoView({block:r0.height>innerHeight-120?'start':'center',behavior:'instant'});
    var r=el.getBoundingClientRect(), pad=6;
    hole.style.left=(r.left-pad)+'px'; hole.style.top=(r.top-pad)+'px'; hole.style.width=(r.width+pad*2)+'px'; hole.style.height=(r.height+pad*2)+'px';
    var cw=340, ch=card.offsetHeight, gap=14, x, y;
    if(r.right+gap+cw<innerWidth){ x=r.right+gap; y=r.top; }                    // 오른쪽
    else if(r.bottom+gap+ch<innerHeight){ x=r.left; y=r.bottom+gap; }            // 아래
    else if(r.top-gap-ch>0){ x=r.left; y=r.top-gap-ch; }                         // 위
    else { x=r.left-gap-cw; y=r.top; }                                          // 왼쪽
    card.style.left=Math.max(12,Math.min(x,innerWidth-cw-12))+'px'; card.style.top=Math.max(12,Math.min(y,innerHeight-ch-12))+'px';
  }
  function end(){ mark(); [shade,hole,card].forEach(function(x){x&&x.remove()}); shade=hole=card=null; removeEventListener('keydown',key); removeEventListener('resize',place); }
  function go(d){ i+=d; if(i>=steps.length) return end(); if(i<0) i=0; place(); }
  function key(ev){ if(ev.key==='Escape') end(); else if(ev.key==='ArrowRight'||ev.key==='Enter') {ev.preventDefault(); go(1);} else if(ev.key==='ArrowLeft') go(-1); }
  function start(){
    if(card) return; build(); if(!steps.length) return; i=0;
    shade=document.createElement('div'); shade.className='tour-shade'; hole=document.createElement('div'); hole.className='tour-hole';
    card=document.createElement('div'); card.className='tour-card'; card.setAttribute('role','dialog');
    document.body.append(shade,hole,card);
    card.addEventListener('click',function(ev){ var b=ev.target.closest('[data-t]'); if(!b) return; ({next:function(){go(1)},prev:function(){go(-1)},end:end})[b.dataset.t](); });
    addEventListener('keydown',key); addEventListener('resize',place); place();
  }
  window.qaTour=start;
  document.addEventListener('click',function(ev){ if(ev.target.closest('[data-tour-start]')){ ev.preventDefault(); start(); } });
  if(!seen()) setTimeout(start, 400);       // Hermes 버튼 같은 늦게 붙는 요소를 기다린다
})();
"""


def script_tag(active: str) -> str:
    steps = tour_for(active)
    if not steps:
        return ""
    key = {"dash": "home", "setup": "data"}.get(active, active)
    return (f'<script>window.QA_TOUR={json.dumps({"key": key, "v": VERSION, "steps": steps}, ensure_ascii=False).replace("</", "<\\/")}</script>'
            f'<script src="/static/tour.js?v={VERSION}" defer></script>')
