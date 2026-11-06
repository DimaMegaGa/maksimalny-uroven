const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source =
  fs.readFileSync(path.join(__dirname, '../frontend/reliability.js'), 'utf8') +
  '\n' +
  fs
    .readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8')
    .split("$('#logout').onclick = logout;")[0];
function client() {
  const drawing = [];
  const storage = new Map();
  const sandbox = {
    window: { MAKS_SITE: 'school', scrollTo() {} },
    location: { hostname: 'school.example', hash: '#subjects' },
    document: {
      querySelector() {
        return {};
      },
      createElement() {
        return {
          getContext() {
            return {
              fillRect() {
                drawing.push('background');
              },
              drawImage() {
                drawing.push('photo');
              },
            };
          },
          toDataURL() {
            return 'data:image/jpeg;base64,test';
          },
        };
      },
    },
    URL: {
      createObjectURL() {
        return 'blob:test';
      },
      revokeObjectURL() {},
    },
    Image: class {
      constructor() {
        this.naturalWidth = 100;
        this.naturalHeight = 100;
      }
      async decode() {}
    },
    localStorage: {
      getItem: (k) => storage.get(k) || null,
      setItem: (k, v) => storage.set(k, v),
      removeItem: (k) => storage.delete(k),
    },
    TypeError,
    TextEncoder,
    AbortController,
    setTimeout,
    clearTimeout,
    structuredClone,
    crypto: require('node:crypto').webcrypto,
    fetch: async () => ({ ok: true, json: async () => ({ ok: true }) }),
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return { sandbox, drawing, run: (code) => vm.runInContext(code, sandbox) };
}
(async () => {
  const c = client();
  assert.equal((await c.run("api('state')")).ok, true);
  c.sandbox.window.self = {};
  c.sandbox.window.top = {};
  c.sandbox.fetch = async (url, options) => {
    assert.equal(options.headers['X-Maks-Embedded'], '1');
    assert.equal(options.credentials, 'same-origin');
    return {ok:true, json:async()=>({revision:1})};
  };
  await c.run("api('revision')");
  c.sandbox.window.top = c.sandbox.window.self;
  c.sandbox.fetch = async (url, options) => {
    assert.equal(options.headers['X-Maks-Embedded'], undefined);
    return {ok:true, json:async()=>({revision:1})};
  };
  await c.run("api('revision')");
  c.sandbox.fetch = async () => ({
    ok: false,
    json: async () => {
      throw new SyntaxError('Unexpected token <');
    },
  });
  await assert.rejects(
    c.run("api('commit',{})"),
    (e) => e.status === 503 && !e.message.includes('Unexpected')
  );
  c.sandbox.fetch = async () => ({
    ok: true,
    json: async () => {
      throw new SyntaxError('The string did not match the expected pattern.');
    },
  });
  await assert.rejects(
    c.run("api('commit',{})"),
    (e) => e.status === 503 && !e.message.includes('expected pattern')
  );
  c.sandbox.fetch = async () => {
    const e = new Error('aborted');
    e.name = 'AbortError';
    throw e;
  };
  await assert.rejects(c.run("api('state')"), /не ответил вовремя/);
  c.sandbox.location.hostname = 'demo.serveousercontent.com';
  c.sandbox.fetch = async (url, options) => {
    assert.equal(options.headers['serveo-skip-browser-warning'], 'true');
    return { ok: true, json: async () => ({ ok: true }) };
  };
  await c.run("api('state')");
  c.run("search='старый запрос';taskTab='completed';openSubjectTasks('История')");
  assert.equal(c.run('subjectFilter'), 'История');
  assert.equal(c.run('search'), '');
  assert.equal(c.run('taskTab'), 'available');
  assert.equal(c.sandbox.location.hash, 'tasks');
  assert.equal(c.run("givenName({name:'Петров Алексей Дмитриевич'})"), 'Алексей');
  c.run(
    "db.tasks=[{id:'task-1',subject:'География'}];db.submissions=[{id:'answer-1',taskId:'task-1'}];db.exchanges=[{id:'exchange-1',subject:'История'}]"
  );
  for (const eventId of [
    'task:task-1',
    'approved:answer-1',
    'submission:answer-1:123',
    'exchange-ready:answer-1',
  ]) {
    assert.match(
      c.run(
        `notificationSymbol(${JSON.stringify({ eventId, type: 'task', title: 'Задание', text: '' })})`
      ),
      /assets\/geography\.png/
    );
  }
  assert.match(
    c.run(
      "notificationSymbol({eventId:'exchange:exchange-1',type:'exchange-request',title:'Запрос',text:''})"
    ),
    /assets\/history\.png/
  );
  const revision = c.run(
    "notificationSymbol({eventId:'revision:answer-1:123',type:'revision',title:'Нужна доработка',text:''})"
  );
  assert.match(revision, /assets\/geography\.png/);
  assert.match(revision, /status-symbol/);
  assert.match(
    c.run("notificationSymbol({eventId:'unknown',type:'task',title:'Новое задание',text:''})"),
    /<svg/
  );
  assert.doesNotMatch(source, /[↗→←↩]/);
  assert.match(await c.run("imageData({name:'avatar.PNG',type:'',size:12})"), /^data:image\/jpeg/);
  assert.deepEqual(c.drawing, ['background', 'photo']);
  await assert.rejects(c.run("imageData({name:'photo.heic',type:'image/heic',size:12})"), /HEIC/);
  c.run('pendingRequestKeys.clear()');
  const requests = [];
  c.sandbox.fetch = async (url, options) => {
    requests.push(JSON.parse(options.body));
    if (requests.length === 1) throw new TypeError('connection lost after write');
    return { ok: true, json: async () => ({ revision: 12 }) };
  };
  assert.equal((await c.run("api('commit',{revision:11,changes:{tasks:[]}})")).revision, 12);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].requestId, requests[1].requestId);
  assert.equal(c.run('pendingRequestKeys.size'), 0);
  c.run(
    "session={userId:'one'};db.users=[{id:'one'},{id:'two'}];localStorage.setItem(draftKey('answer'),JSON.stringify({savedAt:Date.now(),values:{review:'мой текст'}}))"
  );
  assert.equal(c.run("readDraft('answer').review"), 'мой текст');
  c.run("session={userId:'two'}");
  assert.equal(c.run("readDraft('answer')"), null);
  c.run("session={userId:'one'};clearDraft('answer')");
  assert.equal(c.run("readDraft('answer')"), null);
  const calendar = c.run(
    "calendarFile([{id:'calendar-task',deadline:'2026-12-31',subject:'История',title:'Исследование, выводы; источники',description:'Строка 1\\nСтрока 2',instructions:'а'.repeat(100)},{id:'archive',archived:true,deadline:'2026-12-31'}],'Школьные задания')"
  );
  assert.match(calendar, /DTSTART;VALUE=DATE:20261231/);
  assert.match(calendar, /DTEND;VALUE=DATE:20270101/);
  assert.match(calendar.replace(/\r\n /g, ''), /Исследование\\, выводы\\; источники/);
  assert.doesNotMatch(calendar, /UID:archive/);
  assert.ok(calendar.split('\r\n').every((line) => Buffer.byteLength(line) <= 70));
  assert.equal((calendar.match(/BEGIN:VEVENT/g) || []).length, 1);
  console.log(
    'Client regression checks passed: API errors, timeout, proxy notice, subject filter, avatar MIME and transparency.'
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
