import test from 'node:test'
import assert from 'node:assert/strict'
import { createWorkspace, applyAction, isArchived, isOverdue } from '../src/state/workspace.ts'
import { createDemoRepository, loadWorkspace, saveWorkspace, resetWorkspace, validateWorkspace, WORKSPACE_KEY } from '../src/api/workspace.ts'
import { parseRoute, routeHref } from '../src/state/navigation.ts'
const now = new Date('2030-01-01T12:00:00Z')
const assignment = { type: 'assign', warningId: 1045, title: 'Проверить канал', assignee: 'Алексей К.', plannedAt: '2030-01-01T13:00:00Z', deadline: '2030-01-01T15:00:00Z' }
const report = { type:'result', checkId:207, outcome:'clear', result:'Осмотр выполнен.', workDescription:'Работы не требовались.' }
const fresh = () => createWorkspace(now)
function storage() { const m=new Map(); return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)} }
test('seed: only three check statuses, consistent references, reports in archive',()=>{
 const w=fresh(); assert.ok(validateWorkspace(w)); assert.equal(w.data.workOrders.length,0)
 for(const c of w.data.checks){assert.ok(['Новая','В работе','Завершена'].includes(c.status)); if(isArchived(c)) assert.ok(c.result && c.outcome && c.completedAt); if(c.warningId && !isArchived(c)) assert.equal(w.data.warnings.find(v=>v.id===c.warningId).status,'На проверке')}
 assert.ok(w.data.checks.some(c=>isOverdue(c,now)))
})
test('assignment → work → report → archive atomically, input immutable',()=>{
 const original=fresh(); let w=applyAction(original,assignment,now); const id=w.data.checks.at(-1).id
 assert.equal(w.data.checks.at(-1).status,'Новая'); assert.equal(original.data.warnings.find(v=>v.id===1045).status,'Новое')
 w=applyAction(w,{type:'advance',checkId:id},now)
 w=applyAction(w,{...report,checkId:id},now)
 assert.ok(isArchived(w.data.checks.at(-1))); assert.ok(!isOverdue(w.data.checks.at(-1),new Date('2040-01-01')))
 assert.equal(w.data.warnings.find(v=>v.id===1045).status,'Ложная тревога')
 assert.equal(w.history.at(-1).checkId,id)
})
test('manual tasks have no warning and can be completed',()=>{
 let w=applyAction(fresh(),{...assignment,warningId:undefined,objectId:16},now); const id=w.data.checks.at(-1).id
 w=applyAction(w,{type:'advance',checkId:id},now); w=applyAction(w,{...report,checkId:id,outcome:'fixed'},now)
 assert.equal(w.data.checks.at(-1).outcome,'fixed')
})
test('work plan changes executor and deadline without adding a status',()=>{
 const w=applyAction(fresh(),{type:'planWork',checkId:207,workDescription:'Заменить датчик',assignee:'Алексей К.',deadline:assignment.deadline},now)
 const c=w.data.checks.find(c=>c.id===207); assert.equal(c.status,'В работе');assert.equal(c.assignee,'Алексей К.');assert.match(w.history.at(-1).action,/Заменить/)
})
test('cannot complete without report, work description, valid result, or start',()=>{
 for(const patch of [{result:' '},{workDescription:''},{outcome:'invalid'},{checkId:208}]) assert.throws(()=>applyAction(fresh(),{...report,...patch},now))
 const w=applyAction(fresh(),{...report,outcome:'unresolved'},now)
 assert.ok(!isArchived(w.data.checks.find(c=>c.id===207)));assert.equal(w.data.warnings.find(v=>v.id===1037).status,'На проверке')
 const completed=applyAction(w,{...report,outcome:'fixed'},now)
 assert.ok(isArchived(completed.data.checks.find(c=>c.id===207)))
 assert.throws(()=>applyAction(completed,report,now))
})
test('bad schedules, repeated assignment and repeat start are rejected',()=>{
 for(const patch of [{title:' '},{assignee:'unknown'},{deadline:'2020-01-01'},{plannedAt:'2031-01-01'},{plannedAt:'2020-01-01'},{plannedAt:'bad'}]) assert.throws(()=>applyAction(fresh(),{...assignment,...patch},now))
 let w=applyAction(fresh(),assignment,now); assert.throws(()=>applyAction(w,assignment,now)); assert.throws(()=>applyAction(w,{type:'advance',checkId:207},now))
})
test('false alarm needs explanation and no active check',()=>{
 assert.throws(()=>applyAction(fresh(),{type:'falseAlarm',warningId:1045,reason:''},now))
 assert.throws(()=>applyAction(fresh(),{type:'falseAlarm',warningId:1042,reason:'test'},now))
 const w=applyAction(fresh(),{type:'falseAlarm',warningId:1045,reason:'Замер в норме'},now);assert.equal(w.data.warnings.find(v=>v.id===1045).status,'Ложная тревога')
})
test('storage roundtrip, filters and history',async()=>{
 const s=storage();const w=fresh();w.preferences.filters.archive={query:'насос',filter:'Все',category:'Все',sort:'newest',period:'unresolved',from:'2029-01-01'}
 const saved=saveWorkspace(w,0,s);assert.deepEqual(await loadWorkspace(s),JSON.parse(JSON.stringify(saved)))
})
test('corrupt data and stale revisions never silently overwrite',async()=>{
 const s=storage();s.setItem(WORKSPACE_KEY,'{bad');await assert.rejects(loadWorkspace(s))
 s.setItem(WORKSPACE_KEY,JSON.stringify({version:99}));await assert.rejects(loadWorkspace(s))
 const first=resetWorkspace(s);resetWorkspace(s);assert.throws(()=>saveWorkspace(first,first.revision,s))
 const invalid=fresh();invalid.data.checks.find(isArchived).result='';assert.equal(validateWorkspace(invalid),false)
 assert.throws(()=>saveWorkspace(fresh(),0,{getItem:()=>null,setItem:()=>{throw Error('quota')}}),/quota/)
})
test('v1 migration preserves decisions/history and converts statuses, original retained',async()=>{
 const s=storage();const old=fresh();old.version=1;old.data.checks[0].status='Принято';old.data.checks[1].status='Новое';delete old.data.checks[1].plannedAt
 old.preferences.filters.objects={query:'test',filter:'Все',category:'Все',sort:'oldest'}
 old.data.workOrders=[{id:'old-1',objectId:16,title:'Старая работа',status:'Завершена',date:'test'}]
 const raw=JSON.stringify(old);s.setItem('astra.demo.workspace.v1',raw)
 const next=await loadWorkspace(s);assert.ok(validateWorkspace(next));assert.equal(next.version,2);assert.equal(next.data.checks[0].status,'В работе');assert.equal(next.data.checks[1].status,'Новая');assert.equal(next.data.checks.at(-1).status,'Новая');assert.equal(s.getItem('astra.demo.workspace.v1'),raw)
 assert.ok(next.history.some(h=>h.action.includes('Старая работа')))
})
test('reset preserves unrelated storage',()=>{const s=storage();s.setItem('other','keep');const w=resetWorkspace(s);assert.ok(validateWorkspace(w));assert.deepEqual(w.preferences.filters,{});assert.equal(s.getItem('other'),'keep')})
test('new routes and legacy warning links, no objects page',()=>{
 assert.equal(routeHref('warnings'),'/home');assert.deepEqual(parseRoute('/archive/207'),{page:'archive',id:'207'});assert.deepEqual(parseRoute('/map/207'),{page:'map',id:'207'});assert.deepEqual(parseRoute('/warnings/1045'),{page:'warnings',id:'1045'});assert.deepEqual(parseRoute('/objects'),{page:'notFound'});assert.deepEqual(parseRoute('/home/%broken'),{page:'notFound'})
})

test('data upload and sensor pages have stable routes without entity ids',()=>{
 assert.equal(routeHref('data'),'/data')
 assert.deepEqual(parseRoute('/data/'),{page:'data',id:undefined})
 assert.deepEqual(parseRoute('/sensors'),{page:'sensors',id:undefined})
 assert.deepEqual(parseRoute('/data/123'),{page:'notFound'})
 assert.deepEqual(parseRoute('/sensors/123'),{page:'notFound'})
})

test('async repository commands return saved snapshots and reject stale clients', async()=>{
 const repo=createDemoRepository(storage());const initial=await repo.load()
 const next=await repo.execute({type:'advance',checkId:208},initial.revision)
 assert.equal(next.data.checks.find(c=>c.id===208).status,'В работе')
 await assert.rejects(repo.execute({type:'advance',checkId:208},initial.revision),/вкладке/)
 assert.deepEqual(await repo.load(),JSON.parse(JSON.stringify(next)))
})

test('existing unresolved archive records reopen once without losing report or history',async()=>{
 const s=storage(),w=fresh(),c=w.data.checks.find(c=>c.id===207)
 c.status='Завершена';c.outcome='unresolved';c.result='Старый отчёт';c.workDescription='Не устранено';c.completedAt=now.toISOString()
 s.setItem(WORKSPACE_KEY,JSON.stringify(w))
 const migrated=await loadWorkspace(s),next=migrated.data.checks.find(c=>c.id===207)
 assert.equal(next.status,'В работе');assert.equal(next.result,'Старый отчёт');assert.equal(next.completedAt,undefined)
 assert.equal(migrated.revision,w.revision+1)
 const again=await loadWorkspace(s);assert.equal(again.history.length,migrated.history.length);assert.equal(again.revision,migrated.revision)
})
