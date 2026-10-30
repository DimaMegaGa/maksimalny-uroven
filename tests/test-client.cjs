const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8').split("$('#logout').onclick = logout;")[0];
function client() {
  const drawing = [];
  const sandbox = {
    window: {MAKS_SITE:'school',scrollTo(){}},
    location: {hostname:'school.example',hash:'#subjects'},
    document: {querySelector(){return {};}, createElement(){return {
      getContext(){return {fillRect(){drawing.push('background');},drawImage(){drawing.push('photo');}};},
      toDataURL(){return 'data:image/jpeg;base64,test';}
    };}},
    URL: {createObjectURL(){return 'blob:test';},revokeObjectURL(){}},
    Image: class {constructor(){this.naturalWidth=100;this.naturalHeight=100;} async decode(){}},
    AbortController, setTimeout, clearTimeout, structuredClone, crypto: require('node:crypto').webcrypto,
    fetch: async()=>({ok:true,json:async()=>({ok:true})})
  };
  vm.createContext(sandbox);vm.runInContext(source,sandbox);
  return {sandbox,drawing,run:code=>vm.runInContext(code,sandbox)};
}
(async()=>{
  const c=client();
  assert.equal((await c.run("api('state')")).ok,true);
  c.sandbox.fetch=async()=>({ok:false,json:async()=>{throw new SyntaxError('Unexpected token <');}});
  await assert.rejects(c.run("api('commit',{})"),e=>e.status===503 && !e.message.includes('Unexpected'));
  c.sandbox.fetch=async()=>({ok:true,json:async()=>{throw new SyntaxError('The string did not match the expected pattern.');}});
  await assert.rejects(c.run("api('commit',{})"),e=>e.status===503 && !e.message.includes('expected pattern'));
  c.sandbox.fetch=async()=>{const e=new Error('aborted');e.name='AbortError';throw e;};
  await assert.rejects(c.run("api('state')"),/не ответил вовремя/);
  c.sandbox.location.hostname='demo.serveousercontent.com';
  c.sandbox.fetch=async(url,options)=>{assert.equal(options.headers['serveo-skip-browser-warning'],'true');return {ok:true,json:async()=>({ok:true})};};
  await c.run("api('state')");
  c.run("search='старый запрос';taskTab='completed';openSubjectTasks('История')");
  assert.equal(c.run('subjectFilter'),'История');assert.equal(c.run('search'),'');assert.equal(c.run('taskTab'),'available');
  assert.equal(c.sandbox.location.hash,'tasks');
  assert.equal(c.run("givenName({name:'Петров Алексей Дмитриевич'})"),'Алексей');
  assert.match(await c.run("imageData({name:'avatar.PNG',type:'',size:12})"),/^data:image\/jpeg/);
  assert.deepEqual(c.drawing,['background','photo']);
  await assert.rejects(c.run("imageData({name:'photo.heic',type:'image/heic',size:12})"),/HEIC/);
  console.log('Client regression checks passed: API errors, timeout, proxy notice, subject filter, avatar MIME and transparency.');
})().catch(error=>{console.error(error);process.exitCode=1;});
