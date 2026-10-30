let importSource = '', importPreview = null;
const packageStatus = p => p.status==='draft' ? 'Черновик' : p.status==='distributed' ? 'Распределён' : p.openedAt ? 'Прочитан директором' : 'Доставлен · не прочитан';
const rosterTemplate = 'ФИО;Роль;Класс\r\nИванов Иван Иванович;ученик;8А\r\nПетрова Анна Сергеевна;учитель;\r\n';

function administrativeProfile() {
  const user=currentUser();
  const schools=isMinistry() ? [...new Set((admin?.recipients || []).map(r=>r.school))] : (admin?.organizations || []).map(o=>o.name);
  return heading('Мой аккаунт','Доступ и образовательные организации.','<button class="btn outline" data-go="home">В кабинет</button>') + `<section class="card admin-profile"><div class="admin-profile-identity">${avatar(user)}<div><h2>${esc(user.name)}</h2><p class="subtitle">${isMinistry()?'Министерство':'Директор'}</p></div></div><h3>Образовательные организации</h3><div class="subject-tags">${schools.map(name=>`<span class="pill">${esc(name)}</span>`).join('') || '<p class="subtitle">Организации ещё не назначены.</p>'}</div><button class="btn outline" id="admin-profile-logout">Выйти из аккаунта</button></section>`;
}

function downloadText(text, name, type='text/plain') {
  const url = URL.createObjectURL(new Blob(['\ufeff',text], {type:type+';charset=utf-8'}));
  const anchor = document.createElement('a'); anchor.href=url; anchor.download=name; anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function ministryHome() {
  const packets=admin?.packages || [], recipients=admin?.recipients || [];
  const schools=[...new Set(recipients.map(r=>r.school))];
  return heading('Управление доступом','Учётные записи участников и доставка персональных кодов в образовательные организации.','<button class="btn" data-go="ministryUpload">+ Загрузить список</button>') + `<div class="metrics">${metric('▧','','Организаций',schools.length)}${metric('▤','','Черновиков',packets.filter(p=>p.status==='draft').length,'ministryPackages')}${metric('✓','green','Отправлено пакетов',packets.filter(p=>p.status!=='draft').length,'ministryPackages')}</div><section class="card director-organizations"><div class="section-heading"><h2>Образовательные организации</h2><span class="pill">${schools.length}</span></div><div class="subject-tags">${schools.map(name=>`<span class="pill">${esc(name)}</span>`).join('') || '<p class="subtitle">Назначенные организации появятся здесь.</p>'}</div></section><div class="section-heading"><h2>Последние пакеты</h2><button class="btn outline" data-go="ministryPackages">Все отправления</button></div>${packageCards(packets.slice(0,3),true)}<details class="card portal-guide"><summary>Порядок подготовки и выдачи доступа</summary><ol><li>Загрузите CSV со столбцами ФИО, Роль и Класс. Укажите организацию и директора.</li><li>Проверьте строки и сформируйте пакет с персональными кодами.</li><li>Откройте список и инструкцию, затем отправьте пакет директору.</li><li>Отслеживайте получение и распределение доступа в разделе «Отправления».</li></ol></details>`;
}

function packageCards(packets, ministry) {
  return `<section class="package-list">${packets.map(p=>`<article class="card package-card"><div class="package-heading"><span class="tile">▤</span><div><h3>${esc(p.title)}</h3><p class="subtitle">${esc(p.school)} · ${p.rowCount} участников</p></div><span class="pill ${p.status==='distributed' ? 'green' : ''}">${packageStatus(p)}</span></div><p class="subtitle">${ministry ? 'Получатель: '+esc(p.director) : 'Отправитель: кабинет министерства'} · ${dateLabel(p.sentAt || p.createdAt)}</p><div class="package-actions"><button class="btn outline" data-package-open="${esc(p.id)}">Открыть список и инструкцию</button>${ministry && p.status==='draft' ? `<button class="btn" data-package-send="${esc(p.id)}">Отправить директору</button>` : !ministry && p.status!=='distributed' ? `<button class="btn soft" data-package-distribute="${esc(p.id)}" ${p.openedAt ? '' : 'disabled'}>Отметить распределённым</button>` : ''}</div></article>`).join('') || empty(ministry ? 'Отправлений пока нет' : 'Входящих пока нет',ministry ? 'Загрузите таблицу и сформируйте первый пакет.' : 'Когда министерство отправит список, он появится здесь вместе с уведомлением.')}</section>`;
}

function packageListPage(ministry) {
  return heading(ministry ? 'Отправления' : 'Входящие от министерства',ministry ? 'Проверяйте черновики и отслеживайте получение списков.' : 'Коды и инструкции доступны только назначенному директору.',ministry ? '<button class="btn" data-go="ministryUpload">+ Загрузить таблицу</button>' : '') + packageCards(admin?.packages || [],ministry);
}

function ministryUpload() {
  const recipients=admin?.recipients || [];
  return heading('Загрузка списка','Один пакет — одна организация и один директор. До 200 участников.','<button class="btn outline" id="roster-template">Скачать шаблон CSV</button>') + `<section class="card create-card"><form id="ministry-import-form"><label>Организация и директор<select name="recipient" required>${recipients.map((r,i)=>`<option value="${i}">${esc(r.school)} — ${esc(r.director)}</option>`).join('')}</select></label><label>Название пакета<input name="title" required maxlength="120" value="Доступ к школьной платформе"></label><label>Таблица CSV<input id="roster-file" type="file" accept=".csv,text/csv" required></label><p class="subtitle">Столбцы: ФИО, Роль, Класс. Роли: ученик / учитель. Для учителя класс пустой. CSV UTF-8 и Windows-1251, разделители ; , и табуляция. Файлы XLSX сначала сохраните как CSV UTF-8.</p><label>Сопроводительное сообщение<textarea name="instructions" rows="4" maxlength="8000" placeholder="Необязательно: сообщение будет добавлено к стандартной инструкции"></textarea></label><button class="btn outline" id="preview-roster" type="button" ${recipients.length ? '' : 'disabled'}>Проверить таблицу</button><div id="roster-preview" aria-live="polite"></div><p class="form-error" role="alert"></p><button class="btn" id="create-package" type="submit" disabled>Создать аккаунты и пакет с кодами</button><p class="subtitle">До отправки новые аккаунты неактивны. Повторная загрузка созданных профилей блокируется. Участников с полностью одинаковыми ФИО, ролью и классом нужно сверить отдельно.</p>${recipients.length ? '' : '<p class="notice">Организация и директор ещё не назначены. Обратитесь к администратору платформы.</p>'}</form></section>`;
}

function ministryAccounts() {
  return heading('Аккаунты','Замена кода оформляется отдельным пакетом. Старый код действует до его отправки.') + `<section class="card">${(admin?.accounts || []).map(a=>`<article class="director-account-row"><div class="task-body"><h3>${esc(a.name)}</h3><p class="subtitle">${esc(a.school)} · ${a.role==='teacher' ? 'Учитель' : 'Ученик · '+esc(a.className)}</p></div>${a.active ? `<button class="btn outline" data-ministry-reissue="${esc(a.id)}">Перевыпустить код</button>` : '<span class="pill">Ожидает отправки</span>'}</article>`).join('') || empty('Аккаунтов пока нет','Создайте первый пакет из таблицы.')}</section>`;
}

async function openDeliveryPackage(id) {
  try {
    const packet=await api('packages/open',{packageId:id});
    await refreshFromServer(true);
    showModal(`<div class="sheet-header"><h2>${esc(packet.title)}</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><div class="issued-code-body"><p class="notice">Передавайте каждому участнику только его строку. Скачанный файл храните в защищённом месте.${packet.status==='draft' ? ' Новые аккаунты станут доступны после отправки пакета.' : ''}</p><div class="package-actions"><button class="btn" id="download-package">Скачать таблицу CSV</button><button class="btn outline" id="download-instructions">Скачать инструкцию</button></div><div class="package-table-wrap"><table class="package-table"><thead><tr><th>ФИО</th><th>Роль / класс</th><th>Персональный код</th></tr></thead><tbody>${packet.rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${r.role==='teacher' ? 'Учитель' : 'Ученик · '+esc(r.className)}</td><td>${r.current ? `<input class="package-code" aria-label="Код: ${esc(r.name)}" readonly value="${esc(r.code)}" autocomplete="off" spellcheck="false">` : '<span class="pill">Код заменён</span>'}</td></tr>`).join('')}</tbody></table></div><h3>Инструкция директору</h3><div class="package-instructions">${esc(packet.instructions)}</div><button class="btn outline" data-close>Закрыть список</button></div>`, 'task-sheet credential-sheet package-sheet');
    const cell=value=>'"'+String(value ?? '').replace(/^[\s]*[=+@-]/,m=>"'"+m).replace(/"/g,'""')+'"';
    $('#download-package').onclick=()=>downloadText(['ФИО;Роль;Класс;Организация;Персональный код;Статус',...packet.rows.map(r=>[r.name,r.role==='teacher'?'учитель':'ученик',r.className,r.school,r.current?r.code:'',r.current?'актуален':'код заменён'].map(cell).join(';'))].join('\r\n'),'accounts-'+packet.id+'.csv','text/csv');
    $('#download-instructions').onclick=()=>downloadText(packet.instructions,'instruction-'+packet.id+'.txt');
  } catch(error) { toast(error.message); }
}

async function performPackageAction(button,action) {
  const label=button.textContent; button.disabled=true; button.textContent=action==='send'?'Отправляем…':'Сохраняем…';
  try { acceptState(await api('packages/'+action,{packageId:button.dataset[action==='send'?'packageSend':'packageDistribute']}));render();toast(action==='send'?'Пакет доставлен директору':'Пакет отмечен как распределённый'); }
  catch(error) { toast(error.message);button.disabled=false;button.textContent=label; }
}

function bindProvisioning() {
  $('#admin-profile-logout')?.addEventListener('click',logout);
  $$('[data-package-open]',app).forEach(b=>b.onclick=()=>openDeliveryPackage(b.dataset.packageOpen));
  $$('[data-package-send]',app).forEach(b=>b.onclick=()=>performPackageAction(b,'send'));
  $$('[data-package-distribute]',app).forEach(b=>b.onclick=()=>performPackageAction(b,'distribute'));
  $('#roster-template')?.addEventListener('click',()=>downloadText(rosterTemplate,'roster-template.csv','text/csv'));
  $('#director-organization')?.addEventListener('change',e=>{directorOrganization=e.target.value;render();});
  $('#director-search')?.addEventListener('input',e=>{directorQuery=e.target.value;const pos=e.target.selectionStart;render();$('#director-search').focus();$('#director-search').setSelectionRange(pos,pos);});
  const form=$('#ministry-import-form');
  if(form) {
    importSource='';importPreview=null;
    const invalidate=()=>{importPreview=null;$('#create-package').disabled=true;$('#roster-preview').innerHTML='';};
    form.onchange=invalidate;
    const fields=()=>{const data=Object.fromEntries(new FormData(form));const recipient=(admin?.recipients || [])[Number(data.recipient)];return {...data,...recipient,csv:importSource};};
    $('#preview-roster').onclick=async e=>{
      invalidate();$('.form-error',form).textContent='';
      const file=$('#roster-file').files[0];if(!file){$('.form-error',form).textContent='Выберите CSV-файл';return;}
      e.target.disabled=true;processing=true;
      try {
        if(file.size>300000)throw new Error('Файл должен быть не больше 300 КБ');
        const buffer=await file.arrayBuffer();try{importSource=new TextDecoder('utf-8',{fatal:true}).decode(buffer);}catch{importSource=new TextDecoder('windows-1251').decode(buffer);}
        importPreview=await api('ministry/preview',fields());
        $('#roster-preview').innerHTML=`<h3>Готово к созданию: ${importPreview.count}</h3>${importPreview.errors.length ? `<ul class="import-errors">${importPreview.errors.map(r=>`<li>Строка ${r.line}: ${esc(r.message)}</li>`).join('')}</ul>` : ''}<div class="roster-sample">${importPreview.rows.slice(0,12).map(r=>`<p>${esc(r.name)} · ${r.role==='teacher'?'Учитель':'Ученик · '+esc(r.className)}${r.legacyId?' · сохранится существующий профиль':''}</p>`).join('')}</div>${importPreview.count>12?'<p class="subtitle">Показаны первые 12 строк.</p>':''}`;
        $('#create-package').disabled=!!importPreview.errors.length || !importPreview.count;
      }catch(error){$('.form-error',form).textContent=error.message;}finally{processing=false;e.target.disabled=false;}
    };
    form.onsubmit=async e=>{
      e.preventDefault();if(!importPreview || importPreview.errors.length || processing)return;
      processing=true;$('#create-package').disabled=true;$('#create-package').textContent='Создаём аккаунты и защищаем коды…';
      try{acceptState(await api('ministry/import',fields()));importSource='';importPreview=null;location.hash='ministryPackages';render();toast('Пакет создан. Проверьте и отправьте директору.');}
      catch(error){$('.form-error',form).textContent=error.message;$('#create-package').disabled=false;$('#create-package').textContent='Создать аккаунты и пакет с кодами';}finally{processing=false;}
    };
  }
  $$('[data-ministry-reissue]',app).forEach(button=>button.onclick=()=>{
    const account=admin.accounts.find(a=>a.id===button.dataset.ministryReissue), recipients=(admin.recipients || []).filter(r=>r.school===account.school);
    showModal(`<div class="sheet-header"><h2>Замена персонального кода</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><form id="reissue-form" class="issued-code-body"><h3>${esc(account.name)}</h3><label>Получатель<select name="recipient">${recipients.map((r,i)=>`<option value="${i}">${esc(r.school)} — ${esc(r.director)}</option>`).join('')}</select></label><p>Будет создан черновик с новым кодом. При его отправке прежний код и сеансы участника будут отозваны.</p><button class="btn" ${recipients.length?'':'disabled'}>Создать пакет замены</button><p class="form-error" role="alert"></p></form>`,'task-sheet');
    $('#reissue-form').onsubmit=async e=>{e.preventDefault();const b=$('button.btn',e.target);b.disabled=true;try{acceptState(await api('ministry/reissue',{userId:account.id,...recipients[Number(e.target.elements.recipient.value)]}));closeModal();location.hash='ministryPackages';render();}catch(error){$('.form-error',e.target).textContent=error.message;b.disabled=false;}};
  });
}
