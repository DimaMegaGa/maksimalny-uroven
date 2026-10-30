const routes = new Set(['/api/health','/api/state','/api/login','/api/logout','/api/commit',
  '/api/ministry/preview','/api/ministry/import','/api/ministry/reissue',
  '/api/packages/open','/api/packages/send','/api/packages/distribute']);
const json = (error, status) => Response.json({error}, {status, headers:{'Cache-Control':'no-store'}});

export default async function proxy(request) {
  const current = new URL(request.url);
  if (!routes.has(current.pathname)) return json('Маршрут не найден', 404);
  if (!['GET','POST'].includes(request.method)) return json('Метод не поддерживается', 405);
  const readOnly = ['/api/health','/api/state'].includes(current.pathname);
  if ((request.method === 'GET') !== readOnly) return json('Метод не поддерживается', 405);
  if (request.method === 'POST' && (request.headers.get('Origin') !== current.origin || request.headers.get('X-Maks-Request') !== '1')) {
    return json('Недопустимый источник запроса', 403);
  }
  let upstream;
  try {
    upstream = new URL(process.env.MAKS_API_ORIGIN);
    if (upstream.protocol !== 'https:' || upstream.username || upstream.password || upstream.search || upstream.hash ||
        upstream.pathname !== '/' || upstream.hostname === current.hostname || ['localhost','127.0.0.1','[::1]'].includes(upstream.hostname)) throw new Error();
  } catch { return json('Сервер платформы ещё не настроен', 503); }
  const headers = new Headers({'Accept':'application/json','X-Maks-Request':'1','serveo-skip-browser-warning':'true'});
  if (request.headers.has('Cookie')) headers.set('Cookie', request.headers.get('Cookie'));
  if (request.method === 'POST') {
    headers.set('Origin',upstream.origin);
    headers.set('Content-Type','application/json');
  }
  const declared = Number(request.headers.get('Content-Length') || 0);
  if (declared > 5500000) return json('Слишком большой запрос. Уменьшите фотографии.',413);
  const body = request.method === 'POST' ? await request.arrayBuffer() : undefined;
  if (body && body.byteLength > 5500000) return json('Слишком большой запрос. Уменьшите фотографии.',413);
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),20000);
  try {
    const response = await fetch(upstream.origin + current.pathname + current.search,
      {method:request.method,headers,body,redirect:'manual',signal:controller.signal});
    if (response.status >= 300 && response.status < 400) return json('Сервер платформы изменил адрес. Требуется настройка подключения.',503);
    if (!response.headers.get('Content-Type')?.includes('application/json')) return json('Сервер платформы временно недоступен',503);
    const output = new Headers({'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
    const cookie = response.headers.get('Set-Cookie');
    if (cookie) output.set('Set-Cookie',cookie);
    return new Response(await response.arrayBuffer(),{status:response.status,headers:output});
  } catch { return json('Нет связи с сервером платформы. Изменения не подтверждены.',503); }
  finally { clearTimeout(timer); }
}

export const config = {path:'/api/*'};
