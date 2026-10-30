import assert from 'node:assert/strict';
import proxy from '../netlify/functions/api.mjs';
const originalFetch=globalThis.fetch;
const previous=process.env.MAKS_API_ORIGIN;
process.env.MAKS_API_ORIGIN='https://api.example';
let calls=0;
globalThis.fetch=async(url,options)=>{
  calls++;
  assert.equal(url,'https://api.example/api/login');
  assert.equal(options.headers.get('Origin'),'https://api.example');
  assert.equal(options.headers.get('X-Maks-Request'),'1');
  return Response.json({userId:'fictional'},{headers:{'Set-Cookie':'maks_session=fake; Secure; HttpOnly; Path=/'}});
};
try {
  const request=(origin)=>new Request('https://school.netlify.app/api/login',{method:'POST',headers:{Origin:origin,'X-Maks-Request':'1'},body:'{}'});
  assert.equal((await proxy(request('https://attacker.example'))).status,403);
  assert.equal(calls,0);
  const response=await proxy(request('https://school.netlify.app'));
  assert.equal(response.status,200);assert.equal((await response.json()).userId,'fictional');
  assert.match(response.headers.get('Set-Cookie'),/Secure/);
  assert.equal((await proxy(new Request('https://school.netlify.app/api/shutdown'))).status,404);
  globalThis.fetch=async()=>new Response('<html>unavailable</html>',{status:502,headers:{'Content-Type':'text/html'}});
  assert.equal((await proxy(request('https://school.netlify.app'))).status,503);
  globalThis.fetch=async()=>new Response(null,{status:302,headers:{Location:'https://untrusted.example'}});
  assert.equal((await proxy(request('https://school.netlify.app'))).status,503);
  process.env.MAKS_API_ORIGIN='https://user:password@api.example';
  assert.equal((await proxy(request('https://school.netlify.app'))).status,503);
  console.log('Netlify proxy checks passed: origin, routes, cookies, HTML, redirects, configuration.');
} finally {
  globalThis.fetch=originalFetch;
  if(previous===undefined)delete process.env.MAKS_API_ORIGIN;else process.env.MAKS_API_ORIGIN=previous;
}
