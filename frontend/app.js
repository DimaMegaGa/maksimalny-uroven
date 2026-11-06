'use strict';

const MINISTRY_SITE = window.MAKS_SITE === 'ministry';
document.title = MINISTRY_SITE
  ? 'Министерство образования — портал доступа'
  : 'МАКСимальный Уровень';

const SUBJECTS = [];
const emptyDB = () => ({
  users: [],
  tasks: [],
  submissions: [],
  notifications: [],
  exchanges: [],
  ledger: [],
});
let db = emptyDB(),
  session = null,
  revision = 0,
  admin = null,
  syncing = false,
  committing = false;
let refreshTask = null,
  avatarBusy = false,
  sessionGeneration = 0;
async function api(path, body) {
  const protectedWrite =
    body !== undefined &&
    [
      'commit',
      'tasks/update',
      'ministry/import',
      'ministry/reissue',
      'packages/send',
      'packages/distribute',
    ].includes(path);
  const signature = protectedWrite ? path + ':' + JSON.stringify(body) : '';
  if (protectedWrite) {
    if (!pendingRequestKeys.has(signature)) {
      if (pendingRequestKeys.size >= 20)
        pendingRequestKeys.delete(pendingRequestKeys.keys().next().value);
      pendingRequestKeys.set(signature, crypto.randomUUID());
    }
    body = { ...body, requestId: pendingRequestKeys.get(signature) };
  }
  for (let attempt = 0; attempt < 2; attempt++) {
    const controller = new AbortController(),
      timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch((window.MAKS_API_BASE || '/api/') + path, {
        method: body === undefined ? 'GET' : 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
          'X-Maks-Request': '1',
          ...(window.self !== window.top ? { 'X-Maks-Embedded': '1' } : {}),
          ...(location.hostname.endsWith('.serveousercontent.com')
            ? { 'serveo-skip-browser-warning': 'true' }
            : {}),
        },
        signal: controller.signal,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      let payload;
      try {
        payload = await response.json();
      } catch {
        const error = new Error(
          'Сервер временно недоступен. Изменения не подтверждены. Повторите подключение.'
        );
        error.status = 503;
        throw error;
      }
      if (!payload || typeof payload !== 'object' || Array.isArray(payload))
        throw new Error('Сервер вернул некорректный ответ. Повторите попытку.');
      connectionState(true);
      if (!response.ok) {
        const error = new Error(payload.error || 'Ошибка сервера');
        error.status = response.status;
        throw error;
      }
      if (protectedWrite) pendingRequestKeys.delete(signature);
      return payload;
    } catch (error) {
      const unavailable =
        error.name === 'AbortError' || error instanceof TypeError || error.status >= 500;
      if (unavailable) connectionState(false);
      if (unavailable && attempt === 0 && (body === undefined || protectedWrite)) continue;
      if (error.name === 'AbortError')
        throw new Error(
          'Сервер не ответил вовремя. Результат нужно уточнить после восстановления связи; черновик сохранён.'
        );
      if (error instanceof TypeError)
        throw new Error(
          'Нет связи с сервером. Изменения не подтверждены. Текст черновика сохранён.'
        );
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
}
function acceptState(state) {
  if (state.config?.subjects) SUBJECTS.splice(0, SUBJECTS.length, ...state.config.subjects);
  db = state.db;
  revision = state.revision;
  admin = state.admin || null;
  session = { userId: state.userId };
}
function refreshFromServer(force = false) {
  if (committing || processing || avatarBusy) return Promise.resolve();
  if (refreshTask) return refreshTask;
  const generation = sessionGeneration;
  syncing = true;
  refreshTask = (async () => {
    try {
      if (session && !force) {
        const version = await api('revision');
        if (version.revision === revision) return;
      }
      const state = await api('state');
      if (generation !== sessionGeneration || committing) return;
      if (force || !session || state.revision !== revision) {
        if (!force && (modal.open || ['create', 'ministryUpload'].includes(page()) || photoBusy))
          return;
        acceptState(state);
        render();
      }
    } catch (error) {
      if (error.status === 401) {
        if (session && generation === sessionGeneration) {
          session = null;
          db = emptyDB();
          admin = null;
          closeModal();
          render();
        }
      } else if (force) toast(error.message);
    } finally {
      syncing = false;
      refreshTask = null;
    }
  })();
  return refreshTask;
}
let peopleRole = 'teacher';
let taskTab = 'available',
  ratingScope = 'class',
  search = '',
  subjectFilter = 'Все предметы';
let loginRole = MINISTRY_SITE ? 'ministry' : 'student',
  processing = false,
  rewardOpen = false;

let pendingPhotos = [],
  photoBusy = false;
const app = document.querySelector('#app');
const modal = document.querySelector('#modal');
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  );
const uid = () => crypto.randomUUID();
const currentUser = () => db.users.find((user) => user.id === session?.userId);
const isMinistry = () => currentUser()?.role === 'ministry';
const isDirector = () => currentUser()?.role === 'director';
const isTeacher = () => currentUser()?.role === 'teacher';
const page = () => location.hash.slice(1).split('?')[0] || 'home';
const dateLabel = (value) =>
  new Date(value).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
const today = () => new Date().toLocaleDateString('en-CA');
const classKey = (value) =>
  String(value || '')
    .toLocaleLowerCase('ru-RU')
    .replace(/[\s«»"'-]/g, '');
const schoolKey = (value) =>
  String(value || '')
    .trim()
    .toLocaleLowerCase('ru-RU');
const grade = (value) => String(value || '').match(/^\s*(\d{1,2})/)?.[1] || '';
const sameSchool = (a, b) => schoolKey(a.school) === schoolKey(b.school);
const levelName = (points) => (points >= 120 ? 'Лидер' : points >= 60 ? 'Активный' : 'Новичок');
const givenName = (user) => {
  const parts = (user?.name || '').trim().split(/\s+/);
  return parts[1] || parts[0] || '';
};
const balance = (userId) =>
  db.ledger.filter((row) => row.userId === userId).reduce((sum, row) => sum + row.amount, 0);
const experience = (userId) =>
  db.ledger
    .filter((row) => row.userId === userId && row.amount > 0)
    .reduce((sum, row) => sum + row.amount, 0);
const visibleTo = (task, user) =>
  user?.role === 'student' &&
  sameSchool(task, user) &&
  (task.targetType === 'student'
    ? task.target === user.id
    : task.targetType === 'class'
      ? classKey(task.target) === classKey(user.className)
      : grade(task.target) !== '' && grade(task.target) === grade(user.className));
const myTasks = () =>
  db.tasks.filter((task) =>
    isTeacher() ? task.teacherId === currentUser().id : visibleTo(task, currentUser())
  );
const mySubmission = (taskId) =>
  db.submissions.find((row) => row.taskId === taskId && row.userId === currentUser()?.id);
const taskStatus = (task) => {
  const row = mySubmission(task.id);
  return row?.status === 'rejected' && row.reviewOutcome === 'rejected'
    ? 'declined'
    : row?.status || 'available';
};
const statusText = {
  available: 'Доступно',
  pending: 'На проверке',
  approved: 'Выполнено',
  rejected: 'Нужна доработка',
  declined: 'Отклонено',
  revision: 'На доработке',
};
const students = () =>
  db.users.filter((user) => user.role === 'student' && sameSchool(user, currentUser()));
const myNotifications = () =>
  db.notifications
    .filter((row) => row.userId === currentUser()?.id)
    .sort((a, b) => b.createdAt - a.createdAt);

async function mutate(change) {
  if (refreshTask) await refreshTask;
  if (committing) throw new Error('Дождитесь сохранения предыдущего действия');
  committing = true;
  let before;
  try {
    acceptState(await api('state'));
    before = structuredClone(db);
    const result = change(db);
    const changes = {};
    for (const table of Object.keys(emptyDB())) {
      const originals = new Map(before[table].map((row) => [row.id, JSON.stringify(row)]));
      const rows = db[table].filter((row) => originals.get(row.id) !== JSON.stringify(row));
      if (rows.length) changes[table] = rows;
    }
    acceptState(await api('commit', { revision, changes }));
    return result;
  } catch (error) {
    if (before) db = before;
    if (error.status === 409) {
      try {
        acceptState(await api('state'));
      } catch {}
    }
    throw error;
  } finally {
    committing = false;
  }
}
function notify(userId, type, title, text, target, eventId) {
  if (db.notifications.some((row) => row.userId === userId && row.eventId === eventId)) return;
  db.notifications.push({
    id: uid(),
    userId,
    type,
    title,
    text,
    target,
    eventId,
    createdAt: Date.now(),
    read: false,
    celebrated: false,
  });
}
function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('show'), 3600);
}
function go(target, tab) {
  if (tab) {
    taskTab = tab;
    if (target === 'tasks') {
      search = '';
      subjectFilter = 'Все предметы';
    }
  }
  if (location.hash.slice(1) === target) render();
  else location.hash = target;
  window.scrollTo(0, 0);
}
function openSubjectTasks(subject) {
  taskTab = 'available';
  search = '';
  subjectFilter = subject;
  go('tasks');
}
function empty(title, description = '') {
  return `<div class="empty"><span class="empty-symbol">✧</span><h3>${esc(title)}</h3><p>${esc(description)}</p></div>`;
}
function avatar(user, extra = '') {
  const initials = (user?.name || '')
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] || '')
    .join('');
  const photo = user?.avatar;
  return `<span class="avatar portrait initial-avatar ${extra}">${photo && /^(data:image\/(jpeg|png|webp);base64,|\/api\/media\/avatar\/)/.test(photo) ? `<img src="${photo}" alt="Аватар: ${esc(user.name)}">` : esc(initials) || '♙'}</span>`;
}
function heading(title, subtitle, action = '') {
  return `<div class="heading"><div><h1>${title}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`;
}
function documentSymbol() {
  return '<img class="document-symbol subject-symbol subject-symbol--line" src="/assets/document.png" width="30" height="30" alt="" aria-hidden="true">';
}
function metric(icon, tone, label, value, target = '', tab = '') {
  return `<button class="card metric metric-button" ${target ? `data-go="${target}" data-task-tab="${tab}"` : ''}><span class="tile ${tone}">${icon}</span><span><small>${label}</small><strong>${value}</strong></span>${target ? '<span class="metric-arrow"><svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></span>' : ''}</button>`;
}
const SUBJECT_ICONS = {
  'Математика': ['math', 'line'],
  'Алгебра': ['math', 'line'],
  'Геометрия': ['math', 'line'],
  'Вероятность и статистика': ['math', 'line'],
  'Русский язык': ['russian', 'color'],
  'Родный язык': ['russian', 'color'],
  'Литература': ['literature', 'color'],
  'Родная литература': ['literature', 'color'],
  'География': ['geography', 'color'],
  'История': ['history', 'color'],
  'Информатика': ['informatics', 'color'],
  'Биология': ['biology', 'line'],
  'Физика': ['physics', 'line'],
  'Химия': ['chemistry', 'line'],
  'Иностранный язык': ['languages', 'line'],
  'Второй иностранный язык': ['languages', 'line'],
  'Обществознание': ['social-studies', 'line'],
  'Основы духовно-нравственной культуры народов России': ['culture', 'color'],
  'Труд (технология)': ['technology', 'line'],
  'Музыка': ['music', 'line'],
  'Изобразительное искусство': ['art', 'line'],
  'Физическая культура': ['sports', 'line'],
  'Основы безопасности и защиты Родины': ['safety', 'line'],
};
function subjectSymbol(subject) {
  const icon = SUBJECT_ICONS[subject];
  return icon
    ? `<img class="subject-symbol subject-symbol--${icon[1]}" src="/assets/${icon[0]}.png" width="36" height="36" alt="" aria-hidden="true">`
    : documentSymbol();
}
function revisionSymbol() {
  return '<svg class="status-symbol" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6H7a3 3 0 0 0-3 3v9a3 3 0 0 0 3 3h9a3 3 0 0 0 3-3v-2M13 5l3-3 4 4-3 3-7 7-4 1 1-4Z"/></svg>';
}
function notificationSymbol(row) {
  if (row.type === 'level')
    return '<img class="subject-symbol" src="/assets/hero-medal.png" width="32" height="32" alt="" aria-hidden="true">';
  const [kind, id] = (row.eventId || '').split(':');
  const submission = db.submissions.find((item) => item.id === (row.submissionId || id));
  const task = db.tasks.find((item) => item.id === (kind === 'task' ? id : submission?.taskId));
  const request = db.exchanges.find((item) => item.id === id);
  const subject = task?.subject || request?.subject || (SUBJECT_ICONS[row.text] ? row.text : '');
  if (row.type === 'revision')
    return `${subject ? subjectSymbol(subject) : ''}<span class="notification-status">${row.title.includes('отклон') ? '<svg class="status-symbol" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>' : revisionSymbol()}</span>`;
  if (subject) return subjectSymbol(subject);
  return navIcon(
    row.type.startsWith('exchange') ? 'exchange' : row.type === 'reward' ? 'tasks' : 'reports'
  );
}
function taskRow(task) {
  const status = taskStatus(task);
  const pending = db.submissions.filter(
    (row) => row.taskId === task.id && row.status === 'pending'
  );
  return `<article class="task"><span class="tile">${subjectSymbol(task.subject)}</span><div class="task-body"><h3><button class="link task-name" data-detail="${task.id}">${esc(task.title)}</button></h3><div class="meta"><span class="pill">${esc(task.subject)}</span><span class="points">✦ +${task.points} баллов</span><span>до ${dateLabel(task.deadline)}</span></div></div>${isTeacher() ? `<span class="pill">${task.archived ? 'В архиве' : pending.length ? `${pending.length} на проверке` : 'Опубликовано'}</span>${taskTools(task)}` : `<button class="btn ${status === 'available' || status === 'rejected' ? 'soft' : 'outline'}" data-detail="${task.id}">${status === 'available' ? 'Выполнить <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg>' : statusText[status]}</button>`}</article>`;
}
function closeModal() {
  const clearCode = modal.classList.contains('credential-sheet');
  modal.close();
  if (clearCode) modal.innerHTML = '';
  modal.className = '';
  rewardOpen = false;
}
function showModal(content, className = '') {
  modal.className = className;
  modal.innerHTML = content;
  if (!modal.open) modal.showModal();
  modal.scrollTop = 0;
  $$('[data-close]', modal).forEach((button) => (button.onclick = closeModal));
}

function navIcon(name) {
  name =
    {
      directorInbox: 'reports',
      directorTeachers: 'people',
      directorStudents: 'people',
      ministryUpload: 'subjects',
      ministryPackages: 'reports',
      ministryAccounts: 'people',
    }[name] || name;
  const paths = {
    exchange: '<path d="M20 4v7h-7M4 20v-7h7M5.4 7a8 8 0 0 1 13-2L20 7M4 17l1.6 2a8 8 0 0 0 13-2"/>',
    home: '<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3Z"/>',
    tasks:
      '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6m-9 7 3 3 5-6"/>',
    history: '<circle cx="12" cy="12" r="9"/><path d="M12 6v7l4 2"/>',
    subjects:
      '<rect x="5" y="5" width="14" height="16" rx="2"/><path d="M9 3h6v5H9zM9 12h2m3 0h1m-6 4h6"/>',
    rating: '<path d="M5 20V10M12 20V4M19 20v-7" stroke-width="4"/>',
    stats: '<path d="M4 20h16M6 16V9m6 7V4m6 12v-5"/>',
    reports: '<path d="M6 3h9l4 4v14H6ZM14 3v6h5M9 13h7m-7 4h7"/>',
    people:
      '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 5"/>',
    profile: '<circle cx="12" cy="8" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  };
  return (
    '<svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    (paths[name] || paths.profile) +
    '</svg>'
  );
}

const AWARDS = [
  {
    id: 'first-task',
    kind: 'tasks',
    threshold: 1,
    title: 'Первый шаг',
    description: 'Первое задание подтверждено учителем.',
    icon: '🌱',
  },
  {
    id: 'five-tasks',
    kind: 'tasks',
    threshold: 5,
    title: 'В ритме школы',
    description: 'Выполнено 5 заданий.',
    icon: '✦',
  },
  {
    id: 'ten-tasks',
    kind: 'tasks',
    threshold: 10,
    title: 'Десятка достижений',
    description: 'Выполнено 10 заданий.',
    icon: '🎯',
  },
  {
    id: 'level-active',
    kind: 'level',
    threshold: 60,
    title: 'Активный',
    description: 'Достигнут второй уровень — 60 баллов опыта.',
    icon: '⚡',
  },
  {
    id: 'level-leader',
    kind: 'level',
    threshold: 120,
    title: 'Лидер',
    description: 'Достигнут третий уровень — 120 баллов опыта.',
    icon: '🏆',
  },
];
function earnedAchievements(user) {
  if (user?.role !== 'student') return [];
  const saved = new Map((user.achievements || []).map((award) => [award.id, award]));
  const entries = db.ledger
    .filter((row) => row.userId === user.id && row.amount > 0)
    .sort((a, b) => a.createdAt - b.createdAt);
  const completed = db.submissions
    .filter((row) => row.userId === user.id && row.status === 'approved')
    .sort((a, b) => a.checkedAt - b.checkedAt);
  for (const award of AWARDS) {
    if (saved.has(award.id)) continue;
    let earnedAt = null;
    if (award.kind === 'tasks' && completed.length >= award.threshold)
      earnedAt = completed[award.threshold - 1].checkedAt;
    if (award.kind === 'level') {
      let total = 0;
      for (const entry of entries) {
        total += entry.amount;
        if (total >= award.threshold) {
          earnedAt = entry.createdAt;
          break;
        }
      }
    }
    if (earnedAt) saved.set(award.id, { ...award, earnedAt });
  }
  return [...saved.values()].map((award) => ({
    ...award,
    description: AWARDS.find((item) => item.id === award.id)?.description || award.description,
  }));
}
function recordAchievements(userId, submissionId, checkedAt) {
  const user = db.users.find((row) => row.id === userId);
  const previous = new Set((user.achievements || []).map((award) => award.id));
  const awards = earnedAchievements(user);
  user.achievements = awards;
  const awardedPoints =
    db.ledger.find((row) => row.eventId === `approved:${submissionId}`)?.amount || 0;
  const priorExperience = experience(userId) - awardedPoints;
  for (const award of awards.filter(
    (award) =>
      award.kind === 'level' && !previous.has(award.id) && priorExperience < award.threshold
  )) {
    const eventId = `level:${userId}:${award.id}`;
    notify(
      userId,
      'level',
      'Новый уровень!',
      `Поздравляем! Ты достиг(ла) уровня «${award.title}».`,
      'profile',
      eventId
    );
    const notice = db.notifications.find((row) => row.userId === userId && row.eventId === eventId);
    if (notice)
      Object.assign(notice, {
        levelTitle: award.title,
        levelThreshold: award.threshold,
        submissionId,
        createdAt: checkedAt,
      });
  }
}

function showLogin() {
  document.body.classList.add('signed-out');
  const screen = $('#auth-screen');
  screen.hidden = false;
  if (MINISTRY_SITE) loginRole = 'ministry';
  const ministry = MINISTRY_SITE;
  const director = loginRole === 'director' || ministry;
  const title = ministry
    ? 'Вход в ведомственный портал'
    : director
      ? 'Вход директора'
      : loginRole === 'teacher'
        ? 'Вход учителя'
        : 'Вход ученика';
  document.title = title + ' — МАКСимальный уровень';
  screen.innerHTML = `<div class="auth-layout max-login-layout"><section class="auth-brand-panel"><h1 class="auth-main-title">${ministry ? 'Министерство <span>образования</span>' : 'МАКСимальный <span>уровень</span>'}</h1><p>${ministry ? 'Управление доступом образовательных организаций' : 'Твоё школьное пространство'}</p></section><section class="auth-card max-login-card role-login-card"><div class="auth-roles role-login-tabs" role="group" aria-label="Выбор способа входа">${(ministry
    ? []
    : [
        ['student', 'Ученик'],
        ['teacher', 'Учитель'],
        ['director', 'Директор'],
      ]
  )
    .map(
      ([role, label]) =>
        `<button type="button" data-login-role="${role}" aria-pressed="${loginRole === role}" class="${loginRole === role ? 'selected' : ''}">${label}</button>`
    )
    .join(
      ''
    )}</div><h2>${title}</h2><p class="auth-welcome">${ministry ? 'Подготовьте списки участников и отправьте готовые пакеты директорам.' : director ? 'Получайте и распределяйте доступ к школьному пространству.' : 'Войдите по коду, полученному от директора.'}</p><form id="platform-login-form">${director ? '' : '<label>ФИО<input name="name" maxlength="80" required autocomplete="username" placeholder="Фамилия, имя и отчество"></label>'}<label>${director ? 'Специальный код кабинета' : 'Специальный код'}<div class="auth-password"><input id="access-code" name="code" type="password" minlength="6" maxlength="128" required autocomplete="off" spellcheck="false" autocapitalize="off" placeholder="${director ? 'Введите код руководителя' : 'Введите выданный код'}"><button type="button" id="toggle-code" aria-label="Показать код" aria-pressed="false">${navIcon('eye')}</button></div></label><p class="auth-error" id="login-error" role="alert"></p><button class="btn auth-submit" type="submit">Войти ${director ? 'в кабинет' : 'на платформу'} <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></button></form><p class="auth-demo-note">${director ? 'Используйте персональный код, выданный администратором платформы. Если доступ потерян, обратитесь к ответственному за вашу организацию.' : 'Учётная запись создаётся по спискам министерства. Директор передаёт вам персональный код. Школа и класс уже указаны в профиле.'}</p></section></div><div class="auth-bottom"><span>${ministry ? 'Централизованная выдача доступа к школьной платформе' : 'Учись ✦ Действуй ✦ Развивайся'}</span></div>`;
  $$('[data-login-role]', screen).forEach(
    (button) =>
      (button.onclick = () => {
        loginRole = button.dataset.loginRole;
        showLogin();
      })
  );
  $('#toggle-code').onclick = () => {
    const input = $('#access-code'),
      button = $('#toggle-code');
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.setAttribute('aria-label', visible ? 'Скрыть код' : 'Показать код');
    button.setAttribute('aria-pressed', String(visible));
  };
  $('#platform-login-form').onsubmit = async (event) => {
    event.preventDefault();
    if (processing) return;
    const fields = Object.fromEntries(new FormData(event.target));
    Object.keys(fields).forEach((k) => (fields[k] = fields[k].trim()));
    processing = true;
    const submit = $('button[type="submit"]', event.target);
    submit.disabled = true;
    try {
      const state = await api('login', { ...fields, role: loginRole });
      try {
        await api('revision');
      } catch (error) {
        if (error.status === 401) throw new Error(
          'Браузер не сохранил сеанс входа. Обновите браузер или откройте платформу в отдельной вкладке.'
        );
        throw error;
      }
      sessionGeneration++;
      acceptState(state);
      location.hash = 'home';
      render();
    } catch (error) {
      $('#login-error').textContent =
        error instanceof TypeError
          ? 'Не удалось связаться с платформой. Проверьте подключение и повторите вход.'
          : error.message;
    } finally {
      processing = false;
      submit.disabled = false;
    }
  };
}

async function logout() {
  try {
    await api('logout', {});
  } catch (error) {
    toast(error.message);
    return;
  }
  sessionGeneration++;
  session = null;
  db = emptyDB();
  closeModal();
  loginRole = MINISTRY_SITE ? 'ministry' : 'student';
  admin = null;
  taskTab = 'available';
  subjectFilter = 'Все предметы';
  search = '';
  peopleRole = 'teacher';
  location.hash = 'login';
  render();
}

function home() {
  const user = currentUser();
  if (isTeacher()) return teacherHome();
  const done = db.submissions.filter(
    (row) => row.userId === user.id && row.status === 'approved'
  ).length;
  const points = experience(user.id);
  const rank = ranking('class').findIndex((row) => row.id === user.id) + 1;
  return (
    heading(`Привет, ${esc(givenName(user))}!`, 'Новый день — новые возможности.') +
    `<section class="hero"><div><h2>Маленькие действия.<br>Большие достижения.</h2><p>Выбирай интересное, участвуй в школьной жизни<br>и открывай свой следующий уровень.</p><button class="btn light" data-go="tasks">К заданиям <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></button></div><div class="hero-art"><img class="hero-medal" src="/assets/hero-medal.png" width="112" height="112" alt="Медаль за достижения"></div></section><div class="metrics">${metric('✦', 'gold', 'Текущий баланс', `${balance(user.id)} <span>баллов</span>`, 'exchange')}${metric('✓', 'green', 'Выполненные задания', done, 'tasks', 'completed')}${metric('<svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg>', '', 'Место в классе', points > 0 ? rank : '—', 'rating')}</div><div class="columns"><section class="card"><div class="cardhead"><h2>Твои задания</h2><button class="link" data-go="tasks">Смотреть все <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M4,12H20M14,6L20,12L14,18></path></svg></button></div>${
      myTasks()
        .filter((task) => !task.archived && taskStatus(task) !== 'approved')
        .slice(0, 3)
        .map(taskRow)
        .join('') ||
      empty('Заданий пока нет', 'Они появятся, когда учитель опубликует задание для тебя.')
    }</section><section class="card"><h2>${points >= 120 ? 'Ты достиг уровня «Лидер»' : 'Твой следующий уровень'}</h2><div class="level-head"><span class="tile gold">🏅</span><div><strong>${levelName(points)}</strong><small>${points} баллов опыта</small></div></div><div class="progress-label"><span>${points >= 120 ? 'Цель достигнута — продолжай добрые дела' : points < 60 ? 'До уровня «Активный»' : 'До уровня «Лидер»'}</span><span>${Math.min(100, Math.round((points / (points < 60 ? 60 : 120)) * 100))}%</span></div><div class="progress"><i style="width:${Math.min(100, (points / (points < 60 ? 60 : 120)) * 100)}%"></i></div><p class="level-foot">Опыт начисляется после подтверждения учителем. Обмен баллов не уменьшает твой уровень.</p></section></div>`
  );
}
function teacherHome() {
  const tasks = myTasks();
  const pending = db.submissions.filter(
    (row) => row.status === 'pending' && tasks.some((task) => task.id === row.taskId)
  );
  return (
    heading(
      'Кабинет учителя',
      'Замечайте инициативу. Поддерживайте достижения.',
      '<button class="btn" data-go="create">+ Создать задание</button>'
    ) +
    `<div class="metrics">${metric('♙', 'green', 'Учеников школы', students().length)}${metric(documentSymbol(), '', 'Опубликовано заданий', tasks.length, 'tasks')}${metric('◷', 'gold', 'Ожидают проверки', pending.length, 'tasks', 'pending')}</div><section class="card"><div class="cardhead"><h2>Работы на проверке</h2><button class="link" data-go="tasks" data-task-tab="pending">Все работы <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M4,12H20M14,6L20,12L14,18></path></svg></button></div>${pending.map(reviewRow).join('') || empty('Новых работ пока нет', 'Здесь появятся отзывы и фотографии учеников.')}</section>${exchangeRequests()}`
  );
}
function reviewRow(submission) {
  const task = db.tasks.find((row) => row.id === submission.taskId),
    user = db.users.find((row) => row.id === submission.userId);
  return `<article class="task">${avatar(user)}<div class="task-body"><h3>${esc(task?.title)}</h3><span class="meta">${esc(user?.name)} · ${esc(user?.className)} · ${dateLabel(submission.createdAt)}</span></div><button class="btn soft" data-review="${submission.id}">Проверить</button></article>`;
}
function tasks() {
  const teacher = isTeacher();
  let tasks = myTasks().filter(
    (task) =>
      (subjectFilter === 'Все предметы' || task.subject === subjectFilter) &&
      task.title.toLocaleLowerCase('ru-RU').includes(search.toLocaleLowerCase('ru-RU'))
  );
  const tabs = teacher
    ? [
        ['available', 'Опубликованные'],
        ['pending', 'На проверке'],
        ['revision', 'На доработке'],
        ['declined', 'Отклонённые'],
        ['completed', 'Подтверждённые'],
        ['archived', 'Архив'],
      ]
    : [
        ['available', 'Доступные'],
        ['revision', 'На доработке'],
        ['pending', 'На проверке'],
        ['completed', 'Выполненные задания'],
        ['declined', 'Отклонённые'],
      ];
  tasks = tasks.filter((task) =>
    taskTab === 'archived' ? task.archived : taskTab === 'available' ? !task.archived : true
  );
  if (teacher && (taskClassChoice || taskLearnerChoice))
    tasks = tasks.filter((task) =>
      students().some((user) => visibleTo(task, user) && matchingLearner({ userId: user.id }))
    );
  let content;
  if (teacher && !['available', 'archived'].includes(taskTab)) {
    content = db.submissions
      .filter(
        (row) =>
          tasks.some((task) => task.id === row.taskId) &&
          matchingLearner(row) &&
          (taskTab === 'pending'
            ? row.status === 'pending'
            : taskTab === 'revision'
              ? row.status === 'rejected' && row.reviewOutcome !== 'rejected'
              : taskTab === 'declined'
                ? row.status === 'rejected' && row.reviewOutcome === 'rejected'
                : row.status === 'approved')
      )
      .map((row) =>
        taskTab === 'pending'
          ? reviewRow(row)
          : `<article class="task"><span class="tile green">${subjectSymbol(db.tasks.find((task) => task.id === row.taskId)?.subject)}</span><div class="task-body"><h3>${esc(db.tasks.find((task) => task.id === row.taskId)?.title)}</h3><span class="meta">${esc(db.users.find((user) => user.id === row.userId)?.name)}</span></div><button class="btn outline" data-review="${row.id}">Посмотреть работу</button></article>`
      )
      .join('');
  } else {
    if (!teacher)
      tasks = tasks.filter((task) =>
        taskTab === 'completed'
          ? taskStatus(task) === 'approved'
          : taskTab === 'pending'
            ? taskStatus(task) === 'pending'
            : taskTab === 'declined'
              ? taskStatus(task) === 'declined'
              : taskTab === 'revision'
                ? taskStatus(task) === 'rejected'
                : taskStatus(task) === 'available'
      );
    content = tasks.map(taskRow).join('');
  }
  return (
    heading(
      'Задания',
      teacher
        ? 'Публикуйте задания и проверяйте результаты.'
        : 'От полезного действия к новому достижению.',
      teacher ? '<button class="btn" data-go="create">+ Создать задание</button>' : ''
    ) +
    `<div class="tabs">${tabs.map(([value, label]) => `<button data-tab="${value}" class="${taskTab === value ? 'active' : ''}">${label}</button>`).join('')}</div><div class="filters"><input id="task-search" aria-label="Поиск заданий" placeholder="Найти задание…" value="${esc(search)}"><select id="subject-filter" aria-label="Предмет">${['Все предметы', ...SUBJECTS.map((row) => row[0]), 'Внеурочная деятельность'].map((name) => `<option ${subjectFilter === name ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select></div>${teacherFilters()}<section class="card task-list">${content || empty(taskTab === 'completed' ? 'Выполненных заданий пока нет' : taskTab === 'pending' ? 'Работ на проверке пока нет' : taskTab === 'declined' ? 'Отклонённых заданий пока нет' : 'Заданий пока нет', 'Здесь появятся задания и их результаты.')}</section>`
  );
}
function createTask() {
  return (
    heading('Новое задание', 'Выберите, кому будет доступно задание.') +
    `<section class="card create-card"><form id="create-task-form"><label>Название<input name="title" required maxlength="120" placeholder="Что нужно сделать?"></label><label>Описание<textarea name="description" required maxlength="3000" placeholder="Опишите условия выполнения задания"></textarea></label><label>Как выполнить<textarea name="instructions" maxlength="2000" placeholder="Каждый шаг с новой строки"></textarea></label><div class="formrow"><label>Предмет<select name="subject">${[...(currentUser().subjects || []), 'Внеурочная деятельность'].map((name) => `<option>${esc(name)}</option>`).join('')}</select></label><label>Баллы<input name="points" type="number" min="1" max="100" required placeholder="От 1 до 100"></label></div><label>Срок выполнения<input name="deadline" type="date" min="${today()}" required></label><div class="audience-box"><h3>Кому отправить</h3><label>Доступность<select name="targetType" id="audience-type"><option value="class">Всему классу</option><option value="parallel">Всей параллели</option><option value="student">Конкретному ученику</option></select></label><div id="audience-target"></div><p class="level-foot">Задание доступно только ученикам вашей школы. Уведомление придёт каждому получателю.</p></div><div class="modal-actions"><button type="button" class="btn outline" data-go="tasks">Отмена</button><button type="submit" class="btn">Опубликовать <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></button></div><p class="form-error" role="alert"></p></form></section>`
  );
}
function targetField(type) {
  if (type === 'student')
    return `<label>Ученик<select name="target" required ${students().length ? '' : 'disabled'}><option value="">Выберите ученика</option>${students()
      .map(
        (user) => `<option value="${user.id}">${esc(user.name)} · ${esc(user.className)}</option>`
      )
      .join(
        ''
      )}</select></label>${students().length ? '' : '<p class="notice">В организации пока нет учеников. После выдачи доступа их профили появятся в этом списке.</p>'}`;
  return `<label>${type === 'parallel' ? 'Параллель' : 'Класс'}<input name="target" required maxlength="15" placeholder="${type === 'parallel' ? 'Например, 8' : 'Например, 8А'}" value="${esc(type === 'parallel' ? grade(currentUser().className) : currentUser().className)}"></label>`;
}
function subjects() {
  return (
    heading('Мои предметы', 'Все предметы, по которым можно получить оценку.') +
    `<div class="subject-grid">${SUBJECTS.map(([name, cost], index) => `<section class="card subject-tile"><span class="tile ${['blue', 'gold', ''][index % 3]}">${subjectSymbol(name)}</span><h2>${esc(name)}</h2><p class="subtitle">${cost} баллов для запроса оценки</p><button class="btn soft" data-subject="${esc(name)}">Задания по предмету <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M4,12H20M14,6L20,12L14,18></path></svg></button></section>`).join('')}</div>`
  );
}
function ranking(scope = ratingScope) {
  const user = currentUser();
  return students()
    .filter((student) =>
      scope === 'parallel'
        ? grade(student.className) === grade(user.className)
        : classKey(student.className) === classKey(user.className)
    )
    .sort((a, b) => experience(b.id) - experience(a.id) || a.createdAt - b.createdAt);
}
function rating() {
  const people = ranking();
  const user = currentUser();
  const points = experience(user.id);
  const ownIndex = people.findIndex((person) => person.id === user.id);
  const place = ownIndex >= 0 && points > 0 ? ownIndex + 1 : null;
  const leaders = people.filter((person) => experience(person.id) > 0).slice(0, 3);
  const podium = leaders.length
    ? `
    <div class="new-podium">${[1, 0, 2]
      .filter((index) => leaders[index])
      .map(
        (index) => `
      <article data-profile="${leaders[index].id}" tabindex="0" role="button" aria-label="Открыть профиль ${esc(leaders[index].name)}" class="podium-person place-${index + 1}" style="--order:${index}">
        <div class="podium-portrait">${index === 0 ? '<span class="winner-crown">♛</span>' : ''}${avatar(leaders[index], 'podium-avatar')}<span class="place-medal">${index + 1}</span></div>
        <h3>${esc(leaders[index].name)}</h3><div class="podium-block"><strong>${experience(leaders[index].id)}</strong><small>баллов опыта</small></div>
      </article>`
      )
      .join('')}</div>`
    : empty(
        'Рейтинг ещё не сформирован',
        'Первые подтверждённые задания откроют таблицу достижений.'
      );
  return (
    heading('Рейтинг', 'Реальные достижения участников твоей школы.') +
    `
    <div class="rating-with-position">
      <section class="ranking-card">
        <div class="ranking-top"><h2>Лидеры школьной жизни <span>✧</span></h2><span class="season-chip">${new Date().getFullYear()}</span></div>
        <div class="tabs rating-tabs"><button data-scope="class" class="${ratingScope === 'class' ? 'active' : ''}">Мой класс</button><button data-scope="parallel" class="${ratingScope === 'parallel' ? 'active' : ''}">Параллель</button></div>
        ${podium}
        <div class="ranking-list">${people
          .map(
            (person, index) => `
          <div id="ranking-user-${esc(person.id)}" data-profile="${person.id}" tabindex="0" role="button" aria-label="Открыть профиль ${esc(person.name)}" class="rankrow ranking-row" style="--row:${index}">
            <span class="rank-position">${experience(person.id) > 0 ? index + 1 : '—'}</span>${avatar(person)}
            <div class="rank-name"><strong>${esc(person.name)}</strong><small>${esc(person.className)}${person.id === user.id ? ' · Это ты' : ''}</small></div>
            <strong class="rank-score">${experience(person.id)} <span>✦</span></strong>
          </div>`
          )
          .join('')}</div>
      </section>
      <section class="rating-position-card" aria-label="Твоё место в рейтинге">
        <span class="position-caption">ТВОЁ МЕСТО</span>
        ${avatar(user, 'position-avatar')}
        <h2>${esc(user.name)}</h2>
        <p class="position-scope">${ratingScope === 'class' ? 'В твоём классе' : 'Среди параллели'}</p>
        <div class="position-number">${place ? '#' + place : '—'}</div>
        <span class="position-unit">${place ? 'место в рейтинге' : 'место ещё не присвоено'}</span>
        <div class="position-points"><strong>${points}</strong><span>баллов опыта</span></div>
        <button class="btn light" id="find-my-position" ${ownIndex < 0 ? 'disabled' : ''}>Найти себя в рейтинге ↓</button>
        ${points === 0 ? '<p class="position-hint">Место появится после первого подтверждённого задания.</p>' : ''}
      </section>
    </div>`
  );
}

function findMyPosition() {
  const user = currentUser();
  if (!user) return;
  const row = document.getElementById('ranking-user-' + user.id);
  if (!row) return;
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  row.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'center' });
  row.focus({ preventScroll: true });
  row.classList.remove('is-located');
  void row.offsetWidth;
  row.classList.add('is-located');
  clearTimeout(findMyPosition.timer);
  findMyPosition.timer = setTimeout(() => row.classList.remove('is-located'), 2800);
}

function exchange() {
  if (isTeacher())
    return (
      heading(
        'Запросы на оценку',
        'Проверьте запросы учеников. Баллы списываются после одобрения.'
      ) + exchangeRequests()
    );
  const points = balance(currentUser().id);
  return (
    heading('Баллы превращаются в результат', 'Выбери предмет и отправь запрос своему учителю.') +
    `<div class="exchange-summary"><span>Текущий баланс</span><strong>${points} <small>баллов</small></strong></div><div class="exchange-list">${SUBJECTS.map(
      ([name, cost], index) => {
        const pending = db.exchanges.some(
          (row) =>
            row.userId === currentUser().id && row.subject === name && row.status === 'pending'
        );
        const teachers = db.users.filter(
          (u) => u.role === 'teacher' && (u.subjects || []).includes(name)
        );
        return `<section class="card exchange-row"><span class="exchange-row-icon">${subjectSymbol(name)}</span><div class="exchange-row-body"><h3>${esc(name)}</h3><p>${teachers.length ? 'Учителей по предмету: ' + teachers.length : 'Учитель пока не указал этот предмет'}</p></div><span class="exchange-price">✦ ${cost}<small>баллов</small></span><div class="exchange-row-progress"><div class="progress"><i style="width:${Math.min(100, (points / cost) * 100)}%"></i></div><small>${points >= cost ? 'Баллов достаточно' : 'Ещё ' + (cost - points) + ' баллов'}</small></div><button class="btn ${points < cost ? 'outline' : 'soft'}" data-exchange="${esc(name)}" ${points < cost || pending || !teachers.length ? 'disabled' : ''}>${pending ? 'На рассмотрении' : !teachers.length ? 'Нет учителя' : 'Запросить оценку <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg>'}</button></section>`;
      }
    ).join('')}</div>${exchangeRequests()}`
  );
}
function exchangeRequests() {
  const rows = db.exchanges.filter((row) =>
    isTeacher() ? row.teacherId === currentUser().id : row.userId === currentUser().id
  );
  if (!rows.length) return '';
  return `<section class="card requests-card"><h2>Запросы на обмен</h2>${rows.map((row) => `<article class="task"><div class="task-body"><h3>${esc(row.subject)}</h3><span class="meta">${row.cost} баллов · ${esc(db.users.find((user) => user.id === row.userId)?.name)}</span></div>${isTeacher() && row.status === 'pending' ? `<button class="btn soft" data-exchange-approve="${row.id}">Одобрить</button><button class="link" data-exchange-reject="${row.id}">Отклонить</button>` : `<span class="pill">${{ pending: 'На рассмотрении', approved: 'Одобрено', rejected: 'Отклонено' }[row.status]}</span>`}</article>`).join('')}</section>`;
}
function historyPage() {
  const activities = (db.activities || []).map((event) => {
    const submission = db.submissions.find((row) => row.id === event.submissionId);
    const task = db.tasks.find((row) => row.id === submission?.taskId);
    return { ...event, task, submission, kind: 'submission' };
  });
  const exchanges = db.ledger
    .filter((row) => row.userId === currentUser().id && !row.eventId.startsWith('approved:'))
    .map((row) => ({ ...row, kind: 'exchange' }));
  const rows = [...activities, ...exchanges].sort((a, b) => b.createdAt - a.createdAt);
  const labels = {
    pending: 'Отправлено на проверку',
    approved: 'Выполнено',
    revision: 'На доработке',
    rejected: 'Отклонено',
  };
  return (
    heading('История активности', 'Задания, решения учителей и обмен баллов.') +
    `<section class="card activity-list">${rows.map((row) => (row.kind === 'submission' ? `<button class="activity-row" data-activity="${esc(row.id)}"><span class="tile ${row.status === 'approved' ? 'green' : ''}">${row.status === 'approved' ? '✓' : row.status === 'pending' ? '◷' : row.status === 'revision' ? revisionSymbol() : '×'}</span><span class="activity-body"><strong>${esc(row.task?.title || 'Задание')}</strong><span class="meta"><span class="pill">${esc(row.task?.subject || '')}</span><span>${labels[row.status] || row.status}</span><span>${dateLabel(row.createdAt)}</span></span>${row.teacherComment ? `<span class="activity-comment">Учитель: ${esc(row.teacherComment)}</span>` : ''}</span><span class="activity-result">${row.status === 'approved' ? '+' + row.task?.points + ' ✦' : 'Подробнее <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg>'}</span></button>` : `<article class="activity-row"><span class="tile gold">⇄</span><div class="activity-body"><strong>${esc(row.text)}</strong><span class="meta">${dateLabel(row.createdAt)}</span></div><strong>${row.amount > 0 ? '+' : ''}${row.amount}</strong></article>`)).join('') || empty('История пока пуста', 'Здесь сохранятся отправки работ и решения учителей.')}</section>`
  );
}
function activityDetail(eventId) {
  const event = (db.activities || []).find((row) => row.id === eventId);
  const submission = db.submissions.find((row) => row.id === event?.submissionId);
  if (submission) taskDetail(submission.taskId, event);
}
function profile() {
  const requested = new URLSearchParams(location.hash.split('?')[1] || '').get('id');
  const user = db.users.find((row) => row.id === (requested || currentUser().id));
  if (!user) return heading('Профиль', 'Участник не найден.') + empty('Профиль недоступен');
  const own = user.id === currentUser().id;
  const completed =
    user.completedCount ??
    db.submissions.filter((row) => row.userId === user.id && row.status === 'approved').length;
  const earned = experience(user.id);
  const awards = earnedAchievements(user);
  return (
    heading(
      own ? 'Мой профиль' : 'Профиль участника',
      own ? 'Твоё пространство и участники школы.' : 'Достижения и предметы участника.',
      own
        ? ''
        : '<button class="btn outline" data-go="profile"><svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M20,12H4M10,6L4,12L10,18></path></svg> Мой профиль</button>'
    ) +
    `
    <section class="card public-profile">
      <div class="public-profile-cover"><span>✧</span></div>
      <div class="public-profile-content">
        ${avatar(user, 'public-profile-avatar')}
        <div class="public-profile-title"><h2>${esc(user.name)}</h2><span class="profile-role-pill">${user.role === 'teacher' ? 'Учитель' : levelName(earned)}</span></div>
        <p class="subtitle">${esc(user.school)}${user.className ? ' · ' + esc(user.className) : ''}</p>
        ${own ? `<div class="avatar-upload-actions"><label class="avatar-picker btn soft">Изменить фото<input id="avatar-upload" type="file" accept="image/jpeg,image/png,image/webp"></label>${user.avatar ? '<button id="remove-avatar" class="link">Удалить фото</button>' : ''}</div>` : ''}
        ${
          user.role === 'student'
            ? `<div class="public-profile-stats"><div><span class="tile gold">✦</span><strong>${earned}</strong><small>Всего заработано баллов</small></div><div><span class="tile green">✓</span><strong>${completed}</strong><small>Всего выполнено заданий</small></div><button data-achievements="${user.id}" class="achievement-stat"><span class="tile">🏅</span><strong>${awards.length}</strong><small>Достижения <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></small></button></div><button class="btn achievements-button" data-achievements="${user.id}">Открыть достижения <span>${awards.length}</span> <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></button><div class="profile-awards-preview">${
                awards
                  .slice(-3)
                  .reverse()
                  .map(
                    (award) =>
                      `<div class="mini-award"><span>${award.icon}</span><div><strong>${esc(award.title)}</strong><small>${esc(award.description)}</small><small>${dateLabel(award.earnedAt)}</small></div></div>`
                  )
                  .join('') || '<p class="level-foot">Здесь появятся первые достижения ученика.</p>'
              }</div>`
            : `<section class="teacher-subject-section"><h3>Преподаёт</h3><div class="subject-tags">${(user.subjects || []).map((subject) => `<span class="pill">${esc(subject)}</span>`).join('') || '<p class="level-foot">Предметы пока не указаны</p>'}</div>${own ? '<button class="btn soft" id="edit-teacher-subjects">Выбрать предметы</button>' : ''}</section>`
        }
        ${own ? '<button class="btn outline profile-logout" id="profile-logout">Выйти из аккаунта</button>' : '<p class="public-view-note">Просмотр публичного профиля</p>'}
      </div>
    </section>${own ? people() : ''}`
  );
}

function people() {
  const users = db.users
    .filter((u) => u.role === peopleRole)
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'));
  return `<section class="profile-directory"><div class="directory-heading"><h2>Участники школы</h2><p class="subtitle">Учителя и ученики рядом с тобой</p></div><div class="tabs" role="tablist" aria-label="Участники школы">${[
    ['teacher', 'Учителя'],
    ['student', 'Ученики'],
  ]
    .map(
      ([role, label]) =>
        `<button role="tab" aria-selected="${peopleRole === role}" data-people-role="${role}" class="${peopleRole === role ? 'active' : ''}">${label}<span>${db.users.filter((u) => u.role === role).length}</span></button>`
    )
    .join(
      ''
    )}</div><div class="people-grid" role="tabpanel" aria-label="${peopleRole === 'teacher' ? 'Учителя' : 'Ученики'}">${users.map((user) => `<button class="card person-card" data-profile="${user.id}">${avatar(user)}<span><strong>${esc(user.name)}</strong><small>${user.role === 'teacher' ? esc((user.subjects || []).join(' · ') || 'Предметы пока не указаны') : esc(user.className)} · ${esc(user.school)}</small></span><b><svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></b></button>`).join('') || empty(peopleRole === 'teacher' ? 'Учителей пока нет' : 'Учеников пока нет')}</div></section>`;
}
function editTeacherSubjects() {
  const user = currentUser();
  if (user.role !== 'teacher') return;
  showModal(
    `<div class="sheet-header"><h2>Мои предметы</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><form id="teacher-subject-form"><p class="subtitle">Выбери один или несколько предметов. Ученики увидят их в профиле и смогут отправлять тебе запросы на обмен.</p><div class="teacher-subject-options">${SUBJECTS.map(([subject]) => `<label><input type="checkbox" name="subjects" value="${esc(subject)}" ${(user.subjects || []).includes(subject) ? 'checked' : ''}><span>${esc(subject)}</span></label>`).join('')}</div><button class="btn" type="submit">Сохранить предметы</button><p class="form-error" role="alert"></p></form>`,
    'task-sheet'
  );
  $('#teacher-subject-form').onsubmit = async (event) => {
    event.preventDefault();
    const selected = new FormData(event.target).getAll('subjects');
    try {
      await mutate(() => {
        currentUser().subjects = selected;
      });
      closeModal();
      render();
      toast('Предметы сохранены');
    } catch (error) {
      $('.form-error', modal).textContent = error.message;
    }
  };
}

function achievementDialog(userId) {
  const user = db.users.find((row) => row.id === userId);
  if (!user || user.role !== 'student') return;
  const awards = earnedAchievements(user).sort((a, b) => b.earnedAt - a.earnedAt);
  showModal(
    `<div class="sheet-header"><h2>Достижения</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><div class="achievement-catalog"><div class="achievement-owner">${avatar(user)}<div><strong>${esc(user.name)}</strong><small>Получено за всё время: ${awards.length}</small></div></div>${awards.length ? `<div class="achievement-grid">${awards.map((award) => `<article class="earned-achievement"><span class="achievement-medallion ${award.kind === 'level' ? 'level-medallion' : ''}">${award.icon}</span><h3>${esc(award.title)}</h3><p>${esc(award.description)}</p><time>Получено ${dateLabel(award.earnedAt)}</time></article>`).join('')}</div>` : empty('Достижений пока нет', 'Выполняй задания и открывай новые уровни.')}</div>`,
    'task-sheet achievements-sheet'
  );
}

function stats() {
  return workspaceStats();
}
function reports() {
  return (
    heading(
      'Отчёты',
      'Сводка опубликованных заданий.',
      '<button class="btn" id="export">↓ Скачать CSV</button>'
    ) +
    `<section class="card">${myTasks().map(taskRow).join('') || empty('Заданий пока нет')}</section>${exchangeRequests()}`
  );
}

function taskDetail(taskId, activity = null) {
  const task = myTasks().find((row) => row.id === taskId);
  if (!task) return;
  const submission = mySubmission(task.id);
  const outcome =
    activity?.status ||
    (submission?.status === 'rejected'
      ? submission.reviewOutcome || 'revision'
      : submission?.status);
  const teacherComment = activity ? activity.teacherComment : submission?.teacherComment;
  const steps =
    task.instructions
      ?.split('\n')
      .map((row) => row.trim())
      .filter(Boolean) || [];
  showModal(
    `<div class="sheet-header"><button class="sheet-back" data-close aria-label="Назад"><svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M20,12H4M10,6L4,12L10,18></path></svg></button><h2>Задание</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><section class="detail-surface"><div class="detail-top"><span class="tile detail-icon">${subjectSymbol(task.subject)}</span><div><h2>${esc(task.title)}</h2><div class="meta"><span class="pill">${esc(task.subject)}</span><span class="points">✦ +${task.points} баллов</span></div></div></div><p class="task-description">${esc(task.description)}</p><div class="detail-meta"><span>◷ До ${dateLabel(task.deadline)}</span><span>✓ После подтверждения учителя</span></div><h3>Как выполнить</h3><ol class="instruction-list">${(steps.length ? steps : ['Выполни условия задания.', 'Напиши отзыв и при необходимости добавь фотографии.', 'Отправь результат учителю на проверку.']).map((step) => `<li>${esc(step)}</li>`).join('')}</ol>${teacherComment ? `<section class="teacher-feedback"><h3>Сообщение учителя</h3><p>${esc(teacherComment)}</p></section>` : ''}${outcome === 'revision' ? '<p class="notice">Учитель вернул работу на доработку. Уточни результат и отправь его повторно.</p>' : outcome === 'rejected' ? '<p class="notice">Учитель отклонил работу. Повторная отправка закрыта.</p>' : ''}${activity ? `<p class="activity-event-caption">${esc({ pending: 'Отправлено на проверку', approved: 'Выполнено', revision: 'На доработке', rejected: 'Отклонено' }[outcome])} · ${dateLabel(activity.createdAt)}</p>` : ''}${isTeacher() ? `<p class="notice">Доступ: ${esc(task.targetType === 'student' ? db.users.find((user) => user.id === task.target)?.name : task.targetType === 'parallel' ? task.target + ' классы' : task.target)}</p>` : activity ? '' : submission?.status === 'rejected' && submission.reviewOutcome === 'rejected' ? '' : submission?.status === 'approved' ? '<div class="completed-strip">✓ Задание выполнено · баллы начислены</div>' : submission?.status === 'pending' ? '<div class="notice">Результат отправлен. Ожидай подтверждения учителя.</div>' : task.archived ? '<div class="notice">Задание в архиве. История и результаты сохранены; новые ответы не принимаются.</div>' : `<button class="btn detail-submit" id="start-submit">Отправить на проверку <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></button>`}</section>`,
    'task-sheet'
  );
  $('#start-submit', modal)?.addEventListener('click', () => submissionForm(task.id));
}
function submissionForm(taskId) {
  const task = myTasks().find((row) => row.id === taskId);
  if (!task) return;
  const prior = mySubmission(taskId);
  pendingPhotos = prior?.photos ? [...prior.photos] : [];
  photoBusy = false;
  showModal(
    `<div class="sheet-header"><button class="sheet-back" id="back-detail" aria-label="Назад"><svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M20,12H4M10,6L4,12L10,18></path></svg></button><h2>Результат выполнения</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><section class="detail-surface"><h2>${esc(task.title)}</h2><p class="subtitle">Расскажи, что получилось. Учитель увидит отзыв и фотографии.</p><form id="submission-form"><label>Твой отзыв<textarea name="review" required maxlength="3000" placeholder="Опиши результат выполнения задания">${esc(prior?.review || '')}</textarea></label><div class="photo-field"><label class="photo-picker">＋ Прикрепить фотографии<input id="evidence-files" type="file" accept="image/jpeg,image/png,image/webp" multiple></label><span class="meta">До 3 фото · JPG, PNG, WebP · до 8 МБ каждое</span><div id="photo-previews" class="photo-previews"></div></div><label class="condition-check"><input name="confirmed" type="checkbox" required><span>Я выполнил(а) условия задания и отправляю свой результат на проверку.</span></label><button class="btn detail-submit" type="submit">Отправить учителю <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg></button><p class="form-error" role="alert"></p></form></section>`,
    'task-sheet'
  );
  $('#back-detail').onclick = () => taskDetail(taskId);
  bindDraft($('#submission-form'), 'submission:' + taskId, ['review']);
  renderPhotos();
  $('#evidence-files').onchange = async (event) => {
    const files = [...event.target.files];
    if (pendingPhotos.length + files.length > 3) {
      toast('Можно добавить не более 3 фотографий');
      return;
    }
    photoBusy = true;
    $('#submission-form button[type="submit"]').disabled = true;
    try {
      const converted = await Promise.all(files.map((file) => imageData(file, 1000, 0.76)));
      pendingPhotos.push(...converted);
      renderPhotos();
    } catch (error) {
      toast(error.message);
    } finally {
      photoBusy = false;
      const button = $('#submission-form button[type="submit"]');
      if (button) button.disabled = false;
    }
  };
  $('#submission-form').onsubmit = (event) => {
    event.preventDefault();
    const data = new FormData(event.target);
    sendSubmission(taskId, data.get('review'), data.has('confirmed'));
  };
}
function renderPhotos() {
  const box = $('#photo-previews');
  if (!box) return;
  box.innerHTML = pendingPhotos
    .map(
      (photo, index) =>
        `<div class="photo-thumb"><img src="${photo}" alt="Фото результата ${index + 1}"><button type="button" data-remove-photo="${index}" aria-label="Удалить фото ${index + 1}">×</button></div>`
    )
    .join('');
  $$('[data-remove-photo]', box).forEach(
    (button) =>
      (button.onclick = () => {
        pendingPhotos.splice(+button.dataset.removePhoto, 1);
        renderPhotos();
      })
  );
}
async function imageData(file, size = 1000, quality = 0.78) {
  const type =
    file.type ||
    { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' }[
      file.name?.split('.').pop().toLowerCase()
    ];
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(type))
    throw new Error('Выбери изображение JPG, PNG или WebP. Фото HEIC сначала сохрани как JPG.');
  if (file.size > 8 * 1024 * 1024) throw new Error('Размер одного фото — не более 8 МБ');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const ratio = Math.min(1, size / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(image.naturalWidth * ratio);
    canvas.height = Math.round(image.naturalHeight * ratio);
    const context = canvas.getContext('2d');
    if (!context || !canvas.width || !canvas.height)
      throw new Error('Не удалось обработать изображение. Выберите другое фото.');
    context.fillStyle = '#f4effc';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', quality);
  } finally {
    URL.revokeObjectURL(url);
  }
}
async function changeAvatar(file) {
  if (avatarBusy || processing || !currentUser()) return;
  const userId = currentUser().id;
  avatarBusy = true;
  const input = $('#avatar-upload'),
    remove = $('#remove-avatar');
  if (input) input.disabled = true;
  if (remove) remove.disabled = true;
  toast(file ? 'Загружаем и сохраняем фото…' : 'Удаляем фото…');
  try {
    const photo = file ? await imageData(file, 320) : '';
    await mutate(() => {
      if (currentUser()?.id !== userId)
        throw new Error('Аккаунт изменился. Повторите загрузку в нужном профиле.');
      currentUser().avatar = photo;
    });
    render();
    toast(file ? 'Фото профиля сохранено' : 'Фото профиля удалено');
  } catch (error) {
    toast(error.message);
  } finally {
    avatarBusy = false;
    if (input?.isConnected) {
      input.disabled = false;
      input.value = '';
    }
    if (remove?.isConnected) remove.disabled = false;
  }
}
async function sendSubmission(taskId, review, confirmed) {
  if (processing || photoBusy || !confirmed || !String(review).trim()) return;
  processing = true;
  try {
    await mutate(() => {
      const user = currentUser(),
        task = db.tasks.find((row) => row.id === taskId);
      if (!visibleTo(task || {}, user)) throw new Error('Задание недоступно');
      let row = db.submissions.find((item) => item.taskId === taskId && item.userId === user.id);
      if (row && (['pending', 'approved'].includes(row.status) || row.reviewOutcome === 'rejected'))
        throw new Error('Результат уже отправлен');
      if (!row) {
        row = { id: uid(), taskId, userId: user.id };
        db.submissions.push(row);
      }
      Object.assign(row, {
        review: String(review).trim(),
        photos: [...pendingPhotos],
        status: 'pending',
        createdAt: Date.now(),
      });
      notify(
        task.teacherId,
        'review',
        'Работа на проверке',
        `${user.name}: ${task.title}`,
        'tasks',
        `submission:${row.id}:${row.createdAt}`
      );
    });
    clearDraft('submission:' + taskId);
    closeModal();
    go('tasks', 'pending');
    toast('Результат отправлен учителю');
  } catch (error) {
    const box = $('.form-error', modal);
    if (box)
      box.textContent = error.message.includes('quota')
        ? 'Недостаточно места. Уменьши количество фотографий.'
        : error.message;
  } finally {
    processing = false;
  }
}

function reviewDialog(submissionId, draftComment = '') {
  const submission = db.submissions.find((row) => row.id === submissionId);
  const task = db.tasks.find((row) => row.id === submission?.taskId);
  if (!isTeacher() || task?.teacherId !== currentUser().id || !submission) return;
  const user = db.users.find((row) => row.id === submission.userId);
  showModal(
    `<div class="sheet-header"><h2>Проверка задания</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><section class="detail-surface"><div class="detail-top"><span class="tile detail-icon">${subjectSymbol(task.subject)}</span><div><h2>${esc(task.title)}</h2><div class="meta"><span class="pill">${esc(task.subject)}</span><span class="points">✦ +${task.points} баллов</span></div></div></div><div class="review-author">${avatar(user)}<div><h3>${esc(user.name)}</h3><span>${esc(user.className)} класс</span></div></div><section class="review-evidence"><h3>Отзыв ученика</h3><p>${esc(submission.review)}</p><div class="evidence-gallery">${submission.photos.map((photo, index) => `<button class="evidence-image" data-view-photo="${index}"><img src="${photo}" alt="Фото результата ${index + 1}"></button>`).join('')}</div></section><label class="teacher-comment-label">Сообщение ученику <span class="meta">необязательно</span><textarea id="teacher-comment" maxlength="2000" placeholder="Что получилось и что нужно исправить">${esc(draftComment)}</textarea></label><p class="review-footnote">После подтверждения ученику начислятся баллы, обновятся уровень и рейтинг.</p><div class="review-actions"><button class="btn outline" id="revise-submission">На доработку</button><button class="btn outline" id="reject-submission">Отклонить</button><button class="btn" id="approve-submission">Подтвердить +${task.points}</button></div><p class="form-error" role="alert"></p></section>`,
    'task-sheet review-sheet'
  );
  if (submission.status !== 'pending') {
    $('.teacher-comment-label', modal).innerHTML =
      `<h3>Решение учителя</h3><p>${esc({ approved: 'Подтверждено', revision: 'На доработке', rejected: 'Отклонено' }[submission.reviewOutcome] || statusText[submission.status])}</p><p>${esc(submission.teacherComment || 'Комментарий не добавлен')}</p>`;
    $('.review-actions', modal).remove();
    $('.review-footnote', modal).textContent = 'Работа уже проверена.';
  }
  $('#approve-submission')?.addEventListener('click', () =>
    decideSubmission(submissionId, 'approved')
  );
  $('#revise-submission')?.addEventListener('click', () =>
    decideSubmission(submissionId, 'revision')
  );
  $('#reject-submission')?.addEventListener('click', () =>
    decideSubmission(submissionId, 'rejected')
  );
  $$('[data-view-photo]', modal).forEach(
    (button) =>
      (button.onclick = () => {
        const comment = $('#teacher-comment')?.value || draftComment;
        showModal(
          `<div class="sheet-header"><button class="sheet-back" id="back-review"><svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M20,12H4M10,6L4,12L10,18></path></svg></button><h2>Фото результата</h2><button class="sheet-close" data-close>×</button></div><img class="full-evidence" src="${submission.photos[+button.dataset.viewPhoto]}" alt="Фото результата">`,
          'task-sheet'
        );
        $('#back-review').onclick = () => reviewDialog(submissionId, comment);
      })
  );
}
async function decideSubmission(submissionId, outcome) {
  const approved = outcome === 'approved';
  const comment = $('#teacher-comment')?.value.trim() || '';
  if (processing) return;
  processing = true;
  try {
    await mutate(() => {
      const row = db.submissions.find((item) => item.id === submissionId),
        task = db.tasks.find((item) => item.id === row?.taskId);
      if (!isTeacher() || task?.teacherId !== currentUser().id || row?.status !== 'pending')
        throw new Error('Работа уже проверена или недоступна');
      const previous = balance(row.userId);
      row.status = approved ? 'approved' : 'rejected';
      row.checkedAt = Date.now();
      row.teacherComment = comment;
      row.reviewOutcome = outcome;
      if (approved) {
        if (!db.ledger.some((item) => item.eventId === `approved:${row.id}`))
          db.ledger.push({
            id: uid(),
            eventId: `approved:${row.id}`,
            userId: row.userId,
            amount: task.points,
            text: task.title,
            createdAt: Date.now(),
          });
        recordAchievements(row.userId, row.id, row.checkedAt);
        notify(
          row.userId,
          'reward',
          'Задание выполнено!',
          `+${task.points} баллов за «${task.title}»`,
          'tasks',
          `approved:${row.id}`
        );
        const unlocked = SUBJECTS.filter(
          ([, cost]) => previous < cost && balance(row.userId) >= cost
        ).map(([name]) => name);
        if (unlocked.length)
          notify(
            row.userId,
            'exchange',
            'Баллов достаточно для обмена',
            `Можно запросить оценку: ${unlocked.slice(0, 3).join(', ')}${unlocked.length > 3 ? ` и ещё ${unlocked.length - 3} предметов` : ''}.`,
            'exchange',
            `exchange-ready:${row.id}`
          );
      } else
        notify(
          row.userId,
          'revision',
          outcome === 'rejected' ? 'Работа отклонена' : 'Задание возвращено на доработку',
          task.title,
          'tasks',
          `revision:${row.id}:${row.checkedAt}`
        );
    });
    closeModal();
    render();
    toast(
      approved
        ? 'Работа подтверждена. Баллы начислены ученику.'
        : outcome === 'rejected'
          ? 'Работа отклонена'
          : 'Работа возвращена на доработку'
    );
  } catch (error) {
    const box = $('.form-error', modal);
    if (box) box.textContent = error.message;
    else toast(error.message);
  } finally {
    processing = false;
  }
}

function notificationDialog() {
  const rows = myNotifications();
  showModal(
    `<div class="sheet-header"><h2>Уведомления</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><div class="notification-list">${rows.map((row) => `<button class="notification-item ${row.read ? '' : 'unread'}" data-notification="${row.id}"><span class="tile ${row.type === 'reward' ? 'green' : ''}">${notificationSymbol(row)}</span><span><strong>${esc(row.title)}</strong><small>${esc(row.text)}</small><time>${dateLabel(row.createdAt)}</time></span>${row.read ? '' : '<i></i>'}</button>`).join('') || empty('Уведомлений пока нет', 'Новые задания и достижения появятся здесь.')}</div>`,
    'notifications-sheet'
  );
  $$('[data-notification]', modal).forEach(
    (button) =>
      (button.onclick = async () => {
        const row = rows.find((item) => item.id === button.dataset.notification);
        try {
          await mutate(() => {
            const note = db.notifications.find((item) => item.id === row.id);
            note.read = true;
          });
          closeModal();
          openNotificationTarget(row);
        } catch (error) {
          toast(error.message);
        }
      })
  );
}
function maybeCelebrate() {
  if (currentUser()?.role !== 'student' || modal.open || rewardOpen) return;
  const levelNotice = myNotifications()
    .filter((note) => note.type === 'level' && !note.celebrated)
    .sort((a, b) => (b.levelThreshold || 0) - (a.levelThreshold || 0))[0];
  const row =
    levelNotice || myNotifications().find((note) => note.type === 'reward' && !note.celebrated);
  if (!row) return;
  const isLevel = row.type === 'level';
  const ledger = db.ledger.find((item) => item.eventId === row.eventId);
  const points = experience(currentUser().id);
  const particles = Array.from(
    { length: isLevel ? 16 : 9 },
    (_, index) => '<i class="confetti" style="--n:' + index + '"></i>'
  ).join('');
  showModal(
    `
    <button class="celebrate-close" data-close aria-label="Закрыть">×</button>
    <div class="celebrate-art"><span class="celebrate-ring"></span><span class="celebrate-check">${isLevel ? '🏆' : '✓'}</span>${particles}</div>
    <p class="celebrate-kicker">${isLevel ? 'ТВОЯ НОВАЯ ВЕРШИНА' : 'ТВОЁ ДЕЙСТВИЕ ИМЕЕТ ЗНАЧЕНИЕ'}</p>
    <h2>${isLevel ? 'Новый уровень!' : 'Отличная работа!'}</h2>
    <p class="celebrate-description">${isLevel ? `Поздравляем, ${esc(givenName(currentUser()))}!<br>Ты открыл(а) уровень <strong>«${esc(row.levelTitle)}»</strong>.` : `Учитель подтвердил задание<br><strong>${esc(ledger?.text || '')}</strong>`}</p>
    <div class="celebrate-points">${isLevel ? esc(row.levelTitle) : '+' + (ledger?.amount || 0)}<span>${isLevel ? 'Достижение сохранено в профиле' : 'баллов'}</span></div>
    <div class="celebrate-level">${points} баллов опыта · ${levelName(points)}</div>
    <button class="btn" id="reward-main">${isLevel ? 'Посмотреть достижения 🏅' : 'Открыть баланс <svg class=ui-arrow viewBox=0,0,24,24 width=16 height=16 fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true focusable=false><path d=M5,19L19,5M5,5H19V19></path></svg>'}</button>
    <button class="link" id="reward-completed">${isLevel ? 'Продолжить путь' : 'Выполненные задания'}</button>`,
    'celebration-sheet' + (isLevel ? ' level-victory-sheet' : '')
  );
  rewardOpen = true;
  const acknowledge = async () => {
    try {
      await mutate(() => {
        db.notifications
          .filter(
            (note) =>
              note.userId === currentUser().id &&
              (note.id === row.id ||
                (isLevel &&
                  (note.type === 'level' || note.eventId === 'approved:' + row.submissionId)))
          )
          .forEach((note) => {
            note.celebrated = true;
            note.read = true;
          });
      });
      updateHeader();
      return true;
    } catch (error) {
      toast(error.message);
      return false;
    }
  };
  $$('[data-close]', modal).forEach(
    (button) =>
      (button.onclick = async () => {
        if (await acknowledge()) closeModal();
      })
  );
  $('#reward-main').onclick = async () => {
    if (!(await acknowledge())) return;
    closeModal();
    if (isLevel) achievementDialog(currentUser().id);
    else go('exchange');
  };
  $('#reward-completed').onclick = async () => {
    if (!(await acknowledge())) return;
    closeModal();
    if (isLevel) go('home');
    else go('tasks', 'completed');
  };
  modal.oncancel = (event) => {
    event.preventDefault();
    acknowledge().then((saved) => {
      if (saved) closeModal();
    });
  };
}

function updateHeader() {
  const user = currentUser();
  if (!user) return;
  $('#identity').innerHTML =
    `${esc(user.name)}<small>${isMinistry() ? 'Министерство' : isDirector() ? 'Директор' : isTeacher() ? 'Учитель' : esc(user.className)}</small>`;
  $('.school').innerHTML =
    `<span class="school-name">◈ &nbsp; ${esc(user.school)}</span>${user.className ? `<b>${esc(user.className)}</b>` : ''}`;
  $$('.account-avatar').forEach((element) => (element.innerHTML = avatar(user)));
  const unread = isDirector()
    ? (admin?.packages || []).filter((p) => !p.openedAt).length
    : myNotifications().filter((row) => !row.read).length;
  $('#notification-count').textContent = unread || '';
  $('#notification-count').hidden = !unread;
  $('#notification-bell').setAttribute(
    'aria-label',
    `Уведомления${unread ? ': ' + unread + ' новых' : ''}`
  );
}
function render() {
  if (!currentUser()) {
    showLogin();
    return;
  }
  document.body.classList.remove('signed-out');
  $('#auth-screen').hidden = true;
  const links = isMinistry()
    ? [
        ['home', '⌂', 'Обзор'],
        ['ministryUpload', '▧', 'Загрузить список'],
        ['ministryPackages', '▤', 'Отправления'],
        ['ministryAccounts', '♙', 'Аккаунты'],
      ]
    : isDirector()
      ? [
          ['home', '⌂', 'Обзор'],
          ['directorInbox', '▤', 'Входящие'],
          ['directorTeachers', '♙', 'Учителя'],
          ['directorStudents', '♙', 'Ученики'],
        ]
      : isTeacher()
        ? [
            ['home', '⌂', 'Главная'],
            ['tasks', '▤', 'Задания'],
            ['stats', '▥', 'Статистика'],
            ['reports', '▧', 'Отчёты'],
            ['people', '♙', 'Участники'],
          ]
        : [
            ['home', '⌂', 'Главная'],
            ['tasks', '▤', 'Задания'],
            ['exchange', '⇄', 'Обмен'],
            ['history', '◷', 'История'],
            ['subjects', '▧', 'Мои предметы'],
            ['rating', '▥', 'Рейтинг'],
            ['people', '♙', 'Участники'],
          ];
  $('#nav').innerHTML = links
    .filter(([id]) => id !== 'people')
    .map(
      ([id, icon, name]) =>
        `<a href="#${id}" class="${page() === id ? 'active' : ''}"><span class="navicon">${navIcon(id)}</span><span class="nav-label">${name}</span></a>`
    )
    .join('');
  const pages = {
    home,
    tasks,
    subjects,
    rating,
    exchange,
    history: historyPage,
    profile,
    people: profile,
    create: isTeacher() ? createTask : home,
    stats: isTeacher() ? stats : home,
    reports: isTeacher() ? reports : home,
  };
  const directorPages = {
    home: directorHome,
    profile: administrativeProfile,
    directorInbox: directorInbox,
    directorTeachers: () => directorAccounts('teacher'),
    directorStudents: () => directorAccounts('student'),
  };
  const ministryPages = {
    home: ministryHome,
    profile: administrativeProfile,
    ministryUpload,
    ministryPackages: () => packageListPage(true),
    ministryAccounts,
  };
  app.innerHTML = isMinistry()
    ? (ministryPages[page()] || ministryHome)()
    : isDirector()
      ? (directorPages[page()] || directorHome)()
      : (pages[page()] || home)();
  updateHeader();
  bind();
  bindWorkspaceExtras();
  if (typeof bindAppearance === 'function') bindAppearance();
  if (typeof bindMaxNotifications === 'function') bindMaxNotifications();
  document.title =
    ($('#app h1')?.textContent || (MINISTRY_SITE ? 'Ведомственный портал' : 'Главная')) +
    ' — ' +
    (MINISTRY_SITE ? 'МАКСимальный уровень | Министерство' : 'МАКСимальный уровень');
  queueMicrotask(maybeCelebrate);
}
function bind() {
  if (isDirector() || isMinistry()) bindProvisioning();
  $$('[data-people-role]', app).forEach(
    (button) =>
      (button.onclick = () => {
        peopleRole = button.dataset.peopleRole;
        render();
      })
  );
  $$('[data-activity]', app).forEach(
    (button) => (button.onclick = () => activityDetail(button.dataset.activity))
  );
  $('#edit-teacher-subjects')?.addEventListener('click', editTeacherSubjects);
  $('#find-my-position')?.addEventListener('click', findMyPosition);
  $$('[data-profile]', app).forEach((button) => {
    const open = () => {
      location.hash = 'profile?id=' + encodeURIComponent(button.dataset.profile);
    };
    button.onclick = open;
    if (button.tagName !== 'BUTTON')
      button.onkeydown = (event) => {
        if (['Enter', ' '].includes(event.key)) {
          event.preventDefault();
          open();
        }
      };
  });
  $$('[data-achievements]', app).forEach(
    (button) => (button.onclick = () => achievementDialog(button.dataset.achievements))
  );

  $$('[data-go]', app).forEach(
    (button) => (button.onclick = () => go(button.dataset.go, button.dataset.taskTab || undefined))
  );
  $$('[data-tab]', app).forEach(
    (button) =>
      (button.onclick = () => {
        taskTab = button.dataset.tab;
        render();
      })
  );
  $$('[data-detail]', app).forEach(
    (button) => (button.onclick = () => taskDetail(button.dataset.detail))
  );
  $$('[data-review]', app).forEach(
    (button) => (button.onclick = () => reviewDialog(button.dataset.review))
  );
  $$('[data-scope]', app).forEach(
    (button) =>
      (button.onclick = () => {
        ratingScope = button.dataset.scope;
        render();
      })
  );
  $$('[data-subject]', app).forEach(
    (button) => (button.onclick = () => openSubjectTasks(button.dataset.subject))
  );
  $('#task-search')?.addEventListener('input', (event) => {
    search = event.target.value;
    const position = event.target.selectionStart;
    render();
    $('#task-search').focus();
    $('#task-search').setSelectionRange(position, position);
  });
  $('#subject-filter')?.addEventListener('change', (event) => {
    subjectFilter = event.target.value;
    render();
  });
  $('#profile-logout')?.addEventListener('click', logout);
  $('#avatar-upload')?.addEventListener('change', (event) => {
    const file = event.target.files[0];
    if (file) changeAvatar(file);
  });
  $('#remove-avatar')?.addEventListener('click', () => changeAvatar(null));
  const create = $('#create-task-form');
  if (create) {
    $('#audience-target').innerHTML = targetField('class');
    const savedCreate = readDraft('create-task');
    if (savedCreate?.targetType) $('#audience-type').value = savedCreate.targetType;
    $('#audience-target').innerHTML = targetField($('#audience-type').value);
    bindDraft(create, 'create-task', [
      'title',
      'description',
      'instructions',
      'subject',
      'points',
      'deadline',
      'targetType',
      'target',
    ]);
    $('#audience-type').onchange = (event) =>
      ($('#audience-target').innerHTML = targetField(event.target.value));
    create.onsubmit = async (event) => {
      event.preventDefault();
      if (processing) return;
      processing = true;
      const values = Object.fromEntries(new FormData(event.target));
      try {
        await mutate(() => {
          if (!isTeacher()) throw new Error('Публикация доступна учителю');
          const user = currentUser(),
            points = +values.points;
          if (
            !values.title.trim() ||
            !values.description.trim() ||
            !Number.isInteger(points) ||
            points < 1 ||
            points > 100 ||
            !values.target ||
            (!grade(values.target) && values.targetType !== 'student')
          )
            throw new Error('Проверьте название, баллы и получателей задания');
          if (
            values.targetType === 'student' &&
            !students().some((student) => student.id === values.target)
          )
            throw new Error('Выберите ученика вашей школы');
          const task = {
            ...values,
            title: values.title.trim(),
            description: values.description.trim(),
            points,
            id: uid(),
            teacherId: user.id,
            school: user.school,
            createdAt: Date.now(),
          };
          db.tasks.push(task);
          db.users
            .filter((student) => visibleTo(task, student))
            .forEach((student) =>
              notify(student.id, 'task', 'Новое задание', task.title, 'tasks', `task:${task.id}`)
            );
        });
        clearDraft('create-task');
        taskTab = 'available';
        go('tasks');
        toast('Задание опубликовано. Получателям отправлено уведомление.');
      } catch (error) {
        $('.form-error', create).textContent = error.message;
      } finally {
        processing = false;
      }
    };
  }
  $$('[data-exchange]', app).forEach(
    (button) => (button.onclick = () => exchangeDialog(button.dataset.exchange))
  );
  $$('[data-exchange-approve]', app).forEach(
    (button) => (button.onclick = () => decideExchange(button.dataset.exchangeApprove, true))
  );
  $$('[data-exchange-reject]', app).forEach(
    (button) => (button.onclick = () => decideExchange(button.dataset.exchangeReject, false))
  );
  $('#export')?.addEventListener('click', exportReport);
}
function exchangeDialog(subject) {
  const cost = SUBJECTS.find((row) => row[0] === subject)?.[1];
  const teachers = db.users.filter(
    (user) =>
      user.role === 'teacher' &&
      sameSchool(user, currentUser()) &&
      (user.subjects || []).includes(subject)
  );
  showModal(
    `<div class="sheet-header"><h2>Запрос на оценку</h2><button class="sheet-close" data-close>×</button></div><p>${esc(subject)} · ${cost} баллов</p><form id="exchange-form"><label>Учитель<select name="teacherId" required><option value="">Выберите учителя</option>${teachers.map((user) => `<option value="${user.id}">${esc(user.name)}</option>`).join('')}</select></label><p class="notice">Баллы спишутся только после одобрения. Оценку учитель выставляет отдельно.</p><button class="btn" ${teachers.length ? '' : 'disabled'}>Отправить запрос</button><p class="form-error" role="alert">${teachers.length ? '' : 'В вашей школе пока нет учителя, указавшего этот предмет.'}</p></form>`
  );
  $('#exchange-form').onsubmit = async (event) => {
    event.preventDefault();
    try {
      const teacherId = new FormData(event.target).get('teacherId');
      await mutate(() => {
        const user = currentUser();
        if (
          balance(user.id) < cost ||
          db.exchanges.some(
            (row) => row.userId === user.id && row.subject === subject && row.status === 'pending'
          )
        )
          throw new Error('Недостаточно баллов или запрос уже отправлен');
        const row = {
          id: uid(),
          userId: user.id,
          teacherId,
          subject,
          cost,
          status: 'pending',
          createdAt: Date.now(),
        };
        db.exchanges.push(row);
        notify(
          teacherId,
          'exchange-request',
          'Запрос на оценку',
          `${user.name}: ${subject}`,
          'home',
          `exchange:${row.id}`
        );
      });
      closeModal();
      render();
      toast('Запрос отправлен учителю');
    } catch (error) {
      $('.form-error', modal).textContent = error.message;
    }
  };
}
async function decideExchange(id, approved) {
  if (processing) return;
  processing = true;
  try {
    await mutate(() => {
      const row = db.exchanges.find((item) => item.id === id);
      if (!isTeacher() || row?.teacherId !== currentUser().id || row.status !== 'pending')
        throw new Error('Запрос недоступен');
      if (approved && balance(row.userId) < row.cost)
        throw new Error('У ученика недостаточно баллов');
      row.status = approved ? 'approved' : 'rejected';
      if (approved)
        db.ledger.push({
          id: uid(),
          eventId: `exchange:${id}`,
          userId: row.userId,
          amount: -row.cost,
          text: `Обмен: ${row.subject}`,
          createdAt: Date.now(),
        });
      notify(
        row.userId,
        'exchange-result',
        approved ? 'Обмен одобрен' : 'Запрос отклонён',
        row.subject,
        'exchange',
        `exchange-result:${id}`
      );
    });
    render();
    toast(approved ? 'Обмен подтверждён. Выставьте оценку в журнале.' : 'Запрос отклонён');
  } catch (error) {
    toast(error.message);
  } finally {
    processing = false;
  }
}
function exportReport() {
  const cell = (value) =>
    '"' +
    String(value)
      .replace(/^[=+@-]/, "'")
      .replace(/"/g, '""') +
    '"';
  const rows = [
    ['Задание', 'Предмет', 'Баллы', 'Получатели'],
    ...myTasks().map((task) => [
      task.title,
      task.subject,
      task.points,
      task.targetType === 'student'
        ? db.users.find((user) => user.id === task.target)?.name
        : task.target,
    ]),
  ];
  const url = URL.createObjectURL(
    new Blob(['\uFEFF' + rows.map((row) => row.map(cell).join(';')).join('\r\n')], {
      type: 'text/csv;charset=utf-8',
    })
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = 'maks-report.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

$('#logout').onclick = logout;
$('#notification-bell').onclick = () =>
  isDirector() ? go('directorInbox') : isMinistry() ? go('ministryPackages') : notificationDialog();
$$('.account-avatar').forEach((button) => (button.onclick = () => go('profile')));
modal.addEventListener('close', () => {
  if (modal.classList.contains('credential-sheet')) modal.innerHTML = '';
  modal.oncancel = null;
  rewardOpen = false;
  if (currentUser()) queueMicrotask(maybeCelebrate);
});
window.addEventListener('hashchange', () => {
  render();
  window.scrollTo({ top: 0, behavior: 'instant' });
});
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshFromServer();
});
render();
refreshFromServer(true);
setInterval(() => {
  if (!document.hidden) refreshFromServer();
}, 10000);
window.addEventListener('online', () => refreshFromServer(true));
window.addEventListener('offline', () => connectionState(false));
window.addEventListener('focus', () => {
  if (session) refreshFromServer();
});
