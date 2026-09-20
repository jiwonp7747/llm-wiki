import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Button, Callout, Card, HTMLSelect, InputGroup, Spinner, Tag, Switch} from '@blueprintjs/core';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '@blueprintjs/core/lib/css/blueprint.css';
import './style.css';

const labels = {wiki_info:'위키 안내', wiki_list:'문서 목록', wiki_search:'내용 검색', wiki_read:'본문 읽기', wiki_sources:'원본 추적', wiki_usage:'사용 현황'};
const fmt = value => value ? new Date(value).toLocaleString('ko-KR') : '—';
const num = n => Number(n || 0).toLocaleString('ko-KR');
async function api(name, params={}, signal) {
  const query = new URLSearchParams(Object.entries(params).filter(([,v]) => v !== undefined && v !== null));
  const response = await fetch(`/api/${name}?${query}`, {signal});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}
function useData(name, params, tick=0) {
  const [state, set] = useState({loading:true});
  const key = JSON.stringify(params);
  useEffect(() => {
    const controller = new AbortController();
    set({loading:true});
    api(name, JSON.parse(key), controller.signal).then(data => set({data})).catch(error => {
      if (error.name !== 'AbortError') set({error:error.message});
    });
    return () => controller.abort();
  }, [name,key,tick]);
  return state;
}
function Status({state}) {
  if (state.loading) return <div className="loading"><Spinner size={24}/><span>불러오는 중…</span></div>;
  if (state.error) return <Callout intent="danger" title="불러오지 못했습니다">{state.error}</Callout>;
}
function Pager({data, offset, setOffset}) {
  return <div className="pager"><span>총 {num(data.total)}개 · {data.total ? offset+1 : 0}–{Math.min(offset+data.limit,data.total)}</span><div><Button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-data.limit))}>이전</Button><Button disabled={offset+data.limit>=data.total} onClick={()=>setOffset(offset+data.limit)}>다음</Button></div></div>;
}
function DocMarkdown({text, path, open}) {
  const content = text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '').replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_,target,label) => {
    const file = target.split('#')[0];
    return `[${label || target}](/wiki-open?path=${encodeURIComponent('wiki/'+file.replace(/\.md$/, '')+'.md')})`;
  });
  return <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} components={{
    img:({alt})=><span className="muted">[이미지: {alt || '첨부 이미지'}]</span>,
    a:({href,children})=> {
      if (!href) return <span>{children}</span>;
      if (href.startsWith('#')) return <span>{children}</span>;
      if (/^https?:\/\//i.test(href)) return <a href={href} target="_blank" rel="noreferrer">{children} ↗</a>;
      let target;
      try { target = href.startsWith('/wiki-open?') ? new URL(href,'http://wiki').searchParams.get('path') : decodeURIComponent(new URL(href,'http://wiki/'+path).pathname.slice(1)); }
      catch { return <span>{children}</span>; }
      return <button className="text-link" onClick={()=>open(target)}>{children}</button>;
    }
  }}>{content}</Markdown></div>;
}
function Viewer({path, open, back, close}) {
  const [view,setView]=useState('preview'), [doc,setDoc]=useState(), [error,setError]=useState(''), [busy,setBusy]=useState(false), [copy,setCopy]=useState(false);
  const [sourceOffset,setSourceOffset]=useState(0);
  const sources=useData('sources',{path,offset:sourceOffset,limit:10});
  useEffect(()=>{
    setDoc(undefined);setError('');setSourceOffset(0);setCopy(false);
    const controller=new AbortController();
    api('read',{path},controller.signal).then(setDoc).catch(e=>{if(e.name!=='AbortError')setError(e.message)});
    return ()=>controller.abort();
  },[path]);
  async function more() {
    setBusy(true);setError('');
    try {const next=await api('read',{path,...doc.next_cursor,expected_sha256:doc.sha256});setDoc({...next,text:doc.text+next.text});}
    catch(e){setError(e.message)} finally{setBusy(false)}
  }
  async function copyPath(){try{await navigator.clipboard.writeText(path);setCopy(true)}catch{setError('경로를 직접 선택해 복사해 주세요.')}}
  return <aside className="viewer" aria-label="문서 상세">
    <div className="viewer-top"><div><span className="eyebrow">DOCUMENT</span><h2>{path.split('/').pop()}</h2></div><Button aria-label="문서 닫기" onClick={close}>닫기</Button></div>
    <div className="path-box">{path}</div>
    <div className="viewer-actions"><Button disabled={!back} onClick={back}>이전 문서</Button><Button onClick={copyPath}>{copy?'복사됨':'경로 복사'}</Button><div className="spacer"/><Button active={view==='preview'} onClick={()=>setView('preview')}>본문</Button><Button active={view==='raw'} onClick={()=>setView('raw')}>원문</Button></div>
    {error&&<Callout intent="danger">{error}</Callout>}
    {!doc&&!error&&<Status state={{loading:true}}/>}
    {doc&&<><div className="doc-meta">총 {num(doc.total_lines)}행 · SHA-256 <code title={doc.sha256}>{doc.sha256.slice(0,12)}</code></div>
      {view==='raw'?<pre className="raw">{doc.text}</pre>:<DocMarkdown text={doc.text} path={path} open={open}/>}
      {doc.next_cursor&&<Button fill loading={busy} onClick={more}>이어서 읽기 · {doc.next_cursor.start_line}행부터</Button>}
      <section className="sources"><h3>연결된 원본</h3><Status state={sources}/>{sources.data&&<>
        {!sources.data.sources.length&&<p className="muted">연결된 출처가 없습니다.</p>}
        {sources.data.sources.map(s=><Card key={s.source_id} className="source-card"><strong>{s.title || s.source_id}</strong><code>{s.source_id}</code><p>{s.status || '상태 없음'} · {s.verification || '미확인'}</p>
          {s.accessible?<><div className="path-box">{s.stored_path}</div><Button onClick={()=>open(s.stored_path)}>원본 열기</Button></>:<Tag intent="warning">원본을 찾을 수 없음</Tag>}
        </Card>)}
        <div className="pager"><Button disabled={sourceOffset===0} onClick={()=>setSourceOffset(Math.max(0,sourceOffset-10))}>이전 출처</Button><Button disabled={sources.data.next_offset===null} onClick={()=>setSourceOffset(sources.data.next_offset)}>다음 출처</Button></div>
      </>}</section></>}
  </aside>;
}
function Tools({data}) {
  return <><div className="section-heading"><div><h2>도구 사용 현황</h2><p>호출하지 않은 도구도 함께 표시합니다.</p></div><Tag minimal>도구 {data.tools.length}개</Tag></div>
    <div className="tool-grid">{data.tools.map(t=><Card key={t.name} className="tool-card"><div className="tool-title"><span className="tool-icon">{t.name==='wiki_read'?'↗':t.name==='wiki_search'?'⌕':'◇'}</span><div><h3>{labels[t.name]}</h3><code>{t.name}</code></div><strong className="tool-count">{num(t.calls)}<small>회</small></strong></div>
      <div className="tool-stats"><span>성공 <b>{num(t.successes)}</b></span><span>실패 <b className={t.failures?'danger':''}>{num(t.failures)}</b></span></div>
      <p className="last-call">마지막 호출 <span>{fmt(t.last_call)}</span></p>
      <details><summary>도구 설명과 인자</summary><p className="description">{t.description}</p><pre className="raw">{JSON.stringify(t.inputSchema,null,2)}</pre></details>
    </Card>)}</div></>;
}
function Pages({filters,tick,open}) {
  const [query,setQuery]=useState(''),[type,setType]=useState(''),[status,setStatus]=useState('canonical'),[unread,setUnread]=useState(false),[offset,setOffset]=useState(0);
  const state=useData('pages',{...filters,query,page_type:type,status,unread,offset,limit:25},tick);
  useEffect(()=>setOffset(0),[query,type,status,unread,JSON.stringify(filters)]);
  return <><div className="section-heading"><div><h2>정본과 문서</h2><p>더블클릭하거나 제목을 눌러 본문과 출처를 확인하세요.</p></div></div>
    <div className="page-filters"><InputGroup aria-label="문서 검색" placeholder="제목 또는 경로 검색" value={query} onChange={e=>setQuery(e.target.value)}/><HTMLSelect aria-label="문서 상태" value={status} onChange={e=>setStatus(e.target.value)} options={[{label:'정본',value:'canonical'},{label:'모든 상태',value:''},{label:'초안',value:'draft'},{label:'오래된 문서',value:'stale'},{label:'보관',value:'archived'}]}/><HTMLSelect aria-label="문서 종류" value={type} onChange={e=>setType(e.target.value)} options={['', 'component','concept','guide','decision','source-note','question','overview','moc'].map(v=>({label:v||'모든 종류',value:v}))}/><Switch checked={unread} onChange={e=>setUnread(e.target.checked)} label="선택 범위에서 미조회"/></div>
    <Status state={state}/>{state.data&&<><div className="table-wrap"><table className="data-table"><thead><tr><th>문서 / 경로</th><th>종류</th><th>갱신일</th><th>출처</th><th>본문 조회</th><th>마지막 조회</th></tr></thead><tbody>{state.data.items.map(p=><tr key={p.path} onDoubleClick={()=>open(p.path)}><td><button className="text-link title-link" onClick={()=>open(p.path)}>{p.title}</button><code className="table-path">{p.path}</code></td><td><Tag minimal>{p.type}</Tag></td><td>{p.updated}</td><td>{p.source_count}</td><td>{num(p.reads)}<span className="muted"> 회</span><small>검색 노출 {num(p.searches)}</small></td><td>{fmt(p.last_read)}</td></tr>)}</tbody></table></div>{!state.data.total&&<div className="empty">조건에 맞는 문서가 없습니다.</div>}{state.data.skipped_count>0&&<Callout intent="warning">크기·형식·접근 제한으로 {state.data.skipped_count}개 문서를 건너뛰었습니다.</Callout>}<Pager data={state.data} offset={offset} setOffset={setOffset}/></>}
  </>;
}
function Events({filters,tick,open}) {
  const [tool,setTool]=useState(''),[outcome,setOutcome]=useState(''),[offset,setOffset]=useState(0);
  const state=useData('events',{...filters,tool,outcome,offset,limit:25},tick);
  useEffect(()=>setOffset(0),[tool,outcome,JSON.stringify(filters)]);
  return <><div className="section-heading"><div><h2>호출 타임라인</h2><p>최근 호출부터 표시합니다. 펼치면 경로·조회 범위·오류를 확인할 수 있습니다.</p></div></div>
    <div className="page-filters"><HTMLSelect aria-label="타임라인 도구" value={tool} onChange={e=>setTool(e.target.value)} options={[{value:'',label:'모든 도구'},...Object.keys(labels).map(v=>({value:v,label:v}))]}/><HTMLSelect aria-label="호출 결과" value={outcome} onChange={e=>setOutcome(e.target.value)} options={[{value:'',label:'모든 결과'},{value:'success',label:'성공'},{value:'failure',label:'실패'}]}/></div>
    <Status state={state}/>{state.data&&<><div className="timeline">{state.data.items.map(e=><details className="event" key={e.id}><summary><span className={'dot '+(e.success?'ok':'bad')}/><code>{e.tool}</code><Tag minimal intent={e.success?'success':'danger'}>{e.success?'성공':'실패'}</Tag><span className="task-name">{e.task_id||'작업 이름 없음'}</span><time>{fmt(e.time)}</time></summary><div className="event-body"><p className="muted">호출 #{e.id} · 서버 세션 {e.session_id}</p>
      {!e.success&&<Callout intent="danger" title={e.detail.error_type||'호출 실패'}>{e.detail.error_message||'이전 기록에는 오류 종류만 저장되어 있습니다.'}</Callout>}
      {e.truncated===1&&<Tag intent="warning" minimal>결과 잘림 / 다음 페이지 있음</Tag>}
      {e.documents.map((d,i)=><div className="event-doc" key={i}><button className="text-link" onClick={()=>open(d.path)}>{d.path}</button><span>{d.kind}</span>{d.start_line&&<small>{d.start_line}–{d.end_line}행 · {d.sha256?.slice(0,12)}</small>}</div>)}
      {e.document_count>e.documents.length&&<p>전체 {e.document_count}건 중 {e.documents.length}건 표시</p>}
      <details><summary>기록 메타데이터</summary><pre className="raw">{JSON.stringify(e.detail,null,2)}</pre></details>
    </div></details>)}</div>{!state.data.total&&<div className="empty">이 범위에는 호출 기록이 없습니다.</div>}<Pager data={state.data} offset={offset} setOffset={setOffset}/></>}
  </>;
}
function Index({open,tick}) {
  const [raw,setRaw]=useState(false);
  const state=useData('read',{path:'wiki/index.md'},tick);
  return <><div className="section-heading"><div><h2>위키 인덱스</h2><p>위키의 문서 지도 · wiki/index.md</p></div><Button onClick={()=>setRaw(!raw)}>{raw?'본문 보기':'원문 보기'}</Button></div><Status state={state}/>{state.data&&<Card className="index-card">{raw?<pre className="raw">{state.data.text}</pre>:<DocMarkdown text={state.data.text} path="wiki/index.md" open={open}/>} {state.data.next_cursor&&<Button onClick={()=>open('wiki/index.md')}>전체 인덱스 이어 읽기</Button>}</Card>}</>;
}
function App() {
  const [tab,setTab]=useState('tools'),[period,setPeriod]=useState('all'),[task,setTask]=useState(''),[from,setFrom]=useState(''),[until,setUntil]=useState(''),[tick,setTick]=useState(0),[auto,setAuto]=useState(false),[history,setHistory]=useState([]);
  useEffect(()=>{if(auto){const id=setInterval(()=>setTick(t=>t+1),30000);return()=>clearInterval(id)}},[auto]);
  const now=new Date(); let since;
  if(period==='today'){now.setHours(0,0,0,0);since=now.toISOString()}
  if(period==='7'||period==='30'){now.setDate(now.getDate()-Number(period));now.setHours(0,0,0,0);since=now.toISOString()}
  const filters={task_id:task,since:period==='custom'&&from?new Date(from).toISOString():since,until:period==='custom'&&until?new Date(until).toISOString():undefined};
  const overview=useData('overview',filters,tick);
  const open=path=>setHistory(h=>h.at(-1)===path?h:[...h,path]);
  const data=overview.data;
  return <div className="shell"><aside className="sidebar"><div className="brand"><span className="brand-symbol">W</span><div>LLM WIKI<small>KNOWLEDGE OBSERVATORY</small></div></div><div className="nav-label">WORKSPACE</div><nav>{[['tools','도구 사용 현황','◈'],['index','인덱스','☷'],['pages','정본과 문서','▤'],['events','호출 타임라인','◷']].map(([id,title,icon])=><button key={id} aria-current={tab===id?'page':undefined} className={tab===id?'active':''} onClick={()=>setTab(id)}><span>{icon}</span>{title}</button>)}</nav><div className="sidebar-bottom"><span className="live-dot"/> 로컬 · 읽기 전용<p>웹에서의 조회는<br/>MCP 사용량에 포함되지 않습니다.</p><button className="text-link" onClick={()=>open('SCHEMA.md')}>위키 관리 규칙 ↗</button></div></aside>
    <main><header><div><span className="eyebrow">LLM WIKI / OBSERVABILITY</span><h1>지식이 쓰이는 순간을 확인하세요.</h1><p className="root-path">{data?.info.root || '위키 연결 확인 중'}</p></div><Button onClick={()=>setTick(t=>t+1)}>새로고침</Button></header>
      <div className="filter-bar"><label>기간< HTMLSelect aria-label="기간" value={period} onChange={e=>setPeriod(e.target.value)} options={[{value:'all',label:'전체 기간'},{value:'today',label:'오늘'},{value:'7',label:'최근 7일'},{value:'30',label:'최근 30일'},{value:'custom',label:'직접 지정'}]}/></label><label className="task-filter">작업<InputGroup aria-label="작업 이름" list="tasks" placeholder="모든 작업 · task_id 입력" value={task} onChange={e=>setTask(e.target.value)}/><datalist id="tasks">{data?.tasks.map(t=><option key={t} value={t}/>)}</datalist></label><div className="spacer"/><Switch checked={auto} onChange={e=>setAuto(e.target.checked)} label="30초 자동 갱신"/></div>
      {period==='custom'&&<div className="custom-dates"><label>시작 (포함)<input type="datetime-local" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>종료 (미포함)<input type="datetime-local" value={until} onChange={e=>setUntil(e.target.value)}/></label></div>}
      <Status state={overview}/>{data&&<div className="metrics">{[['총 도구 호출',data.totals.calls,'MCP 호출 기준'],['본문 조회',data.totals.body_reads,'반환한 문서 구간'],['고유 조회 문서',data.totals.unique_documents,'중복 경로 제외'],['실패한 호출',data.totals.failures,'서비스 오류 기준']].map(([title,value,hint])=><Card className="metric" key={title}><span>{title}</span><strong>{num(value)}</strong><small>{hint}</small></Card>)}</div>}
      <section className="content">{tab==='tools'&&data&&<Tools data={data}/>} {tab==='pages'&&<Pages filters={filters} tick={tick} open={open}/>} {tab==='events'&&<Events filters={filters} tick={tick} open={open}/>} {tab==='index'&&<Index tick={tick} open={open}/>}</section>
      <footer>기록은 MCP 응답 준비를 나타냅니다. 셸 접근·모델의 이해·답변 반영 여부는 측정하지 않습니다. 시간은 브라우저의 현지 시간대로 표시합니다.</footer>
    </main>{history.length>0&&<Viewer key={history.at(-1)} path={history.at(-1)} open={open} back={history.length>1?()=>setHistory(h=>h.slice(0,-1)):null} close={()=>setHistory([])}/>}</div>;
}
createRoot(document.getElementById('root')).render(<App/>);
