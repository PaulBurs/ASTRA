import test from 'node:test'
import assert from 'node:assert/strict'
import { createDemoAuth, demoUsers, SESSION_KEY } from '../src/api/auth.ts'
import { createDemoRepository } from '../src/api/workspace.ts'
import { createDraftRepository } from '../src/api/drafts.ts'
const storage=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)}}
test('ID login, whitespace, restore, invalid ID, logout',async()=>{
 const s=storage(),auth=createDemoAuth(s)
 assert.equal(await auth.current(),null)
 assert.equal((await auth.signIn(' 2001 ')).role,'technician')
 assert.equal((await createDemoAuth(s).current()).id,'2001')
 await assert.rejects(auth.signIn('9999'),/не найден/)
 await auth.signOut();assert.equal(await auth.current(),null)
 s.setItem(SESSION_KEY,'bad');assert.equal(await auth.current(),null)
})
test('unavailable session storage does not report successful login',async()=>{
 const auth=createDemoAuth({getItem:()=>null,setItem:()=>{throw Error('denied')},removeItem:()=>{}})
 await assert.rejects(auth.signIn('1001'),/сохранить вход/)
})
test('technician receives only owned checks and cannot execute dispatcher commands',async()=>{
 const s=storage(),tech=createDemoRepository(s,demoUsers[1]),dispatcher=createDemoRepository(s,demoUsers[0])
 const scoped=await tech.load(),full=await dispatcher.load()
 assert.ok(scoped.data.checks.length<full.data.checks.length)
 assert.ok(scoped.data.checks.every(c=>c.assigneeId==='2001'))
 assert.ok(!scoped.data.checks.some(c=>c.id===207))
 await assert.rejects(tech.execute({type:'advance',checkId:207},scoped.revision),/не назначена/)
 await assert.rejects(tech.execute({type:'falseAlarm',warningId:1045,reason:'test'},scoped.revision),/диспетчеру/)
 await assert.rejects(tech.reset(),/диспетчеру/)
})
test('shared workflow: technician finishes own assignment, dispatcher sees result and actual author',async()=>{
 const s=storage(),dispatcher=createDemoRepository(s,demoUsers[0]),tech=createDemoRepository(s,demoUsers[1])
 let w=await tech.load();w=await tech.execute({type:'advance',checkId:208},w.revision)
 w=await tech.execute({type:'result',checkId:208,outcome:'fixed',result:'Вентилятор проверен',workDescription:'Соединение заменено'},w.revision)
 const full=await dispatcher.load(),c=full.data.checks.find(c=>c.id===208)
 assert.equal(c.status,'Завершена');assert.equal(c.outcome,'fixed');assert.equal(full.history.at(-1).actor,'Алексей К.')
 assert.ok(full.data.checks.some(c=>c.id===207))
})
test('dispatcher cannot execute checks, submit reports, plan work or create standalone tasks',async()=>{
 const s=storage(),dispatcher=createDemoRepository(s,demoUsers[0]); const w=await dispatcher.load()
 for (const action of [
  {type:'advance',checkId:208},
  {type:'result',checkId:207,outcome:'fixed',result:'test',workDescription:'test'},
  {type:'planWork',checkId:207,assignee:'Алексей К.',deadline:new Date(Date.now()+86400000).toISOString(),workDescription:'test'},
  {type:'assign',objectId:1,title:'test',assignee:'Алексей К.',plannedAt:new Date(Date.now()+3600000).toISOString(),deadline:new Date(Date.now()+7200000).toISOString()}
 ]) await assert.rejects(dispatcher.execute(action,w.revision))
 assert.equal((await dispatcher.load()).revision,w.revision)
 const assigned=await dispatcher.execute({type:'assign',warningId:1045,title:'Проверить связь',assignee:'Алексей К.',plannedAt:new Date(Date.now()+3600000).toISOString(),deadline:new Date(Date.now()+7200000).toISOString()},w.revision)
 assert.equal(assigned.data.checks.at(-1).status,'Новая')
})
test('filters are per employee; dispatcher data remain intact',async()=>{
 const s=storage(),a=createDemoRepository(s,demoUsers[1]),b=createDemoRepository(s,demoUsers[2]);const initial=await a.load()
 await a.preferences({mode:'demo',filters:{checks:{query:'насос',filter:'Все',category:'Все',sort:'newest'}}},initial.revision)
 assert.equal((await a.load()).preferences.filters.checks.query,'насос');assert.deepEqual((await b.load()).preferences.filters,{})
})
test('report drafts restore, separate employees/check generations, remove only own draft',async()=>{
 const s=storage(),drafts=createDraftRepository(s),value={outcome:'clear',result:'Черновик',work:'Осмотр'}
 await drafts.save('2001.208.date1',value)
 assert.deepEqual(await drafts.load('2001.208.date1'),value)
 assert.equal(await drafts.load('2002.208.date1'),null);assert.equal(await drafts.load('2001.208.date2'),null)
 await drafts.remove('2001.208.date1');assert.equal(await drafts.load('2001.208.date1'),null)
})

test('unresolved report stays active, successful followup archives without dispatcher approval',async()=>{
 const s=storage(),tech=createDemoRepository(s,demoUsers[2]),dispatcher=createDemoRepository(s,demoUsers[0])
 let w=await tech.load()
 w=await tech.execute({type:'result',checkId:207,outcome:'unresolved',result:'Неисправность обнаружена',workDescription:'Требуется замена'},w.revision)
 let c=(await dispatcher.load()).data.checks.find(c=>c.id===207)
 assert.equal(c.status,'В работе');assert.equal(c.completedAt,undefined);assert.equal(c.result,'Неисправность обнаружена')
 w=await tech.execute({type:'result',checkId:207,outcome:'fixed',result:'Контрольный тест пройден',workDescription:'Датчик заменён'},w.revision)
 c=(await dispatcher.load()).data.checks.find(c=>c.id===207)
 assert.equal(c.status,'Завершена');assert.ok(c.completedAt)
 assert.ok(w.history.some(h=>h.action.includes('Неисправность обнаружена')))
})
