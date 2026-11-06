const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../frontend/max-bridge.js'), 'utf8');

function fixture(hash, saved, blocked = false) {
  const scripts = [], listeners = {}, actions = [];
  let observer;
  const media = {matches: false, addEventListener(type, fn) { this.changed = fn; }};
  const storage = new Map(saved ? [['maks-appearance', saved]] : []);
  const root = {dataset:{}};
  const dialog = { open: false, close() { this.open = false; } };
  const context = {
    location: { hash, pathname: '/', search: '' },
    history: { replaceState(a, b, url) { context.location.hash = url.slice(url.indexOf('#')); } },
    localStorage: {getItem: key => { if (blocked) throw new Error('storage blocked'); return storage.get(key); }, setItem: (key,value) => storage.set(key,value)},
    document: {
      documentElement: root,
      currentScript: { dataset: { app: 'app.js?v=test' } },
      createElement: () => ({}),
      body: { appendChild: script => scripts.push(script) },
      head: { appendChild: script => scripts.push(script) },
      querySelector: () => dialog.open ? dialog : null,
      getElementById: () => dialog,
    },
    setTimeout: fn => { context.timeout = fn; return 1; }, clearTimeout() {},
    MutationObserver: class { constructor(fn) { observer = fn; } observe() {} },
    window: { matchMedia: () => media, addEventListener(type, fn) { listeners[type] = fn; } },
    URLSearchParams,
  };
  vm.runInNewContext(source, context);
  return { context, scripts, dialog, actions, listeners, media, root, changed: () => observer() };
}
const ordinary = fixture('#subjects');
assert.equal(ordinary.scripts.length, 1);
assert.equal(ordinary.scripts[0].src, 'app.js?v=test');
assert.equal(ordinary.context.location.hash, '#subjects');

assert.equal(ordinary.root.dataset.theme, 'light');
ordinary.media.matches = true;
ordinary.media.changed();
assert.equal(ordinary.root.dataset.theme, 'dark');

const savedDark = fixture('#home', 'dark');
assert.equal(savedDark.root.dataset.theme, 'dark');
savedDark.media.changed();
assert.equal(savedDark.root.dataset.theme, 'dark');
assert.equal(fixture('#home', 'unknown').root.dataset.theme, 'light');
assert.equal(fixture('#home', null, true).scripts.length, 1, 'blocked storage cannot prevent startup');

const max = fixture('#WebAppData=signed&WebAppPlatform=ios');
assert.equal(max.scripts[0].src, 'https://st.max.ru/js/max-web-app.js');
assert.match(max.context.location.hash, /WebAppData/);
let back;
max.context.window.WebApp = { BackButton: {
  onClick(fn) { back = fn; }, show() { max.actions.push('show'); }, hide() { max.actions.push('hide'); },
} };
max.scripts[0].onload();
assert.equal(max.context.location.hash, '#home');
max.scripts[1].onload();
max.context.location.hash = '#tasks';
max.listeners.hashchange();
assert.equal(max.actions.at(-1), 'show');
max.dialog.open = true;
max.changed();
back();
assert.equal(max.dialog.open, false);
assert.equal(max.context.location.hash, '#tasks');
back();
assert.equal(max.context.location.hash, '#home');
assert.equal(max.actions.at(-1), 'hide');

for (const failure of ['timeout', 'error']) {
  const fallback = fixture('#WebAppData=test');
  if (failure === 'timeout') fallback.context.timeout();
  else fallback.scripts[0].onerror();
  fallback.scripts[0].onload();
  assert.equal(fallback.scripts.length, 2, 'app must start once');
  assert.equal(fallback.context.location.hash, '#home');
}
console.log('MAX Bridge: ordinary browser, launch fragment, back button and CDN failure passed');
