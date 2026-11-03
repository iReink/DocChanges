import { extractDocumentInfo, documentInfoFromPDF } from '/document-info.js?v=20261102-independent';
import { DocumentViewer } from '/document-viewer.js?v=20261102-independent';
import { normalURL as parseAPIAddress } from '/api-address.js?v=20261103-proxy';
import * as pdfjs from '/vendor/pdfjs/pdf.mjs';
pdfjs.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.mjs';
const $=id=>document.getElementById(id);
const labels={text:'Текст',money:'Суммы',requisites:'Реквизиты',parties:'Стороны',dates:'Даты и сроки',table:'Таблицы',formatting:'Абзацы и переносы',movement:'Перемещения',signatures:'Подписи'};
const operations={insert:'Добавлен текст',delete:'Удалён текст',replace:'Замена',row_insert:'Добавлена строка',row_delete:'Удалена строка',row_move:'Перемещена строка',column_insert:'Добавлен столбец',column_delete:'Удалён столбец',table_insert:'Добавлена таблица',table_delete:'Удалена таблица',cell_merge:'Объединение ячеек',paragraph_boundary:'Граница абзаца',move:'Перемещение',signature_change:'Изменён состав подписей'};
const operationLabel=c=>c.operation==='row_move'&&c.details?.edited?'Перемещение и изменение строки':c.operation==='move'&&c.details?.renumbered?'Перемещение и перенумерация':c.operation==='move'&&c.details?.scope==='sentence'?'Перемещение предложения':(operations[c.operation]||c.operation);
let api='',connected=false,task=null,result=null,poller=null,heartbeat=null,selected=null,resultRevision=-1;
const pdfs={},pages={old:1,new:1},viewers={},documentInfos={};
for(const side of ['old','new'])viewers[side]=new DocumentViewer($(side+'Stream'),{
 onPageChange:(page,total)=>{pages[side]=page||1;$(side+'PageLabel').textContent=total?`${page} / ${total}`:'Подготовка просмотра страниц';
  document.querySelectorAll(`[data-side="${side}"][data-direction]`).forEach(button=>button.disabled=!total||(Number(button.dataset.direction)<0?page<=1:page>=total));},
 onStatus:message=>{$(side+'PageLabel').textContent=message;},
 onError:error=>notify('Не удалось открыть страницу: '+error.message)
});
function notify(text=''){ $('notice').textContent=text;$('notice').hidden=!text; }
function show(view){for(const v of ['upload','progress','result'])$(v+'View').hidden=v!==view;
 for(const id of ['headerDocument','resultHeading','reportActions','newComparison'])$(id).hidden=view!=='result';document.body.classList.toggle('result-mode',view==='result');}
function openSettings(){if(!$('connectionPanel').open)$('connectionPanel').showModal();}
function documentHeading(){
 const a=documentInfos.old,b=documentInfos.new;
 const label=a&&b&&a.label!==b.label?a.label+' → '+b.label:(a?.label||b?.label||'Сравнение документов');
 $('documentTitle').textContent=label;$('documentTitle').title=label;
}

function normalURL(value){return parseAPIAddress(value,location.origin);}
async function request(path,options={}){const response=await fetch(api+path,{cache:'no-store',...options});if(!response.ok){let msg;try{const body=await response.json();msg=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail);}catch{msg='Ошибка HTTP '+response.status;}throw Object.assign(new Error(msg),{status:response.status});}return response.json();}
async function connect(value){
 try{const nextAPI=normalURL(value),changed=api&&api!==nextAPI;api=nextAPI;$('apiAddress').value=api;$('connectionError').hidden=true;$('connectionText').textContent='Проверка подключения';
 const health=await request('/health',{signal:AbortSignal.timeout(4000)});if(health.service!=='atlas-comparison')throw new Error('По этому адресу работает другое приложение.');
 const caps=await request('/api/v1/capabilities',{signal:AbortSignal.timeout(6000)});
 connected=true;localStorage.setItem('atlas-api',api);localStorage.setItem('atlas-api-routing','proxy-v1');$('connectionDot').classList.add('online');$('connectionText').textContent='Сервер подключён';$('compareButton').disabled=false;if($('connectionPanel').open)$('connectionPanel').close();
 const converterInfo=!caps.converter?'Конвертер Word отсутствует. ':!health.converter?'Сервер запущен без ускоренного конвертера. Перезапустите сервер сравнения. ':health.converter.ready?'Ускоренный конвертер готов. ':health.converter.state==='warming'?'Конвертер прогревается. ':'Ускоренный конвертер недоступен. Перезапустите сервер сравнения. ';
 $('connectionInfo').textContent=converterInfo+(caps.models.available?'Сервер моделей доступен.':'Сервер моделей недоступен — сравнение продолжится кодом.');notify();
 if(changed)await clearLocalResult();
 if(location.hash.startsWith('#task=')){task=location.hash.slice(6);show(result?'result':'progress');watch();}
 }catch(error){connected=false;$('connectionDot').classList.remove('online');$('connectionText').textContent='Нет подключения';$('compareButton').disabled=true;$('connectionError').textContent='Не удалось подключиться: '+error.message+' Проверьте адрес, порт и доступ к локальной сети.';$('connectionError').hidden=false;openSettings();}
}
$('settingsButton').onclick=openSettings;
$('useWebAPI').onclick=()=>{clearInterval(poller);connect('/comparison-api');};
$('closeSettings').onclick=()=>$('connectionPanel').close();
$('connectionPanel').addEventListener('click',event=>{const box=$('connectionPanel').getBoundingClientRect();if(event.target===$('connectionPanel')&&(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom))$('connectionPanel').close();});
$('connectForm').onsubmit=e=>{e.preventDefault();clearInterval(poller);connect($('apiAddress').value);};
for(const side of ['old','new']){
 const input=$(side+'File'),drop=$(side+'Drop');
 const update=()=>{const f=input.files[0];$(side+'Name').textContent=f?f.name:'Выберите документ';$(side+'Meta').textContent=f?(f.size/1048576).toFixed(2)+' МБ':'или перетащите его сюда';};input.onchange=update;
 drop.ondragover=e=>{e.preventDefault();drop.classList.add('drag');};drop.ondragleave=()=>drop.classList.remove('drag');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('drag');const transfer=new DataTransfer();if(e.dataTransfer.files[0])transfer.items.add(e.dataTransfer.files[0]);input.files=transfer.files;update();};
}
$('uploadForm').onsubmit=async e=>{
 e.preventDefault();if(!connected)return;notify();
 const body=new FormData();body.append('employee',$('employee').value.trim()||$('employee').placeholder);
 for(const side of ['old','new']){const file=$(side+'File').files[0];if(file.size>50*1048576){notify('Размер файла превышает 50 МБ.');return;}body.append(side,file);for(const sig of $(side+'Signatures').files)body.append(side+'_signatures',sig);}
 $('compareButton').disabled=true;
 try{const job=await request('/api/v1/comparisons',{method:'POST',body});task=job.id;location.hash='task='+task;show('progress');watch();}
 catch(error){notify(error.message);}finally{$('compareButton').disabled=!connected;}
};
function stopTimers(){clearInterval(poller);clearInterval(heartbeat);poller=heartbeat=null;}
async function watch(){stopTimers();let busy=false;const poll=async()=>{if(busy||!task)return;busy=true;try{
 const job=await request('/api/v1/comparisons/'+task);$('progressStage').textContent=job.stage;
 $('progressMeta').textContent=(job.queue_position?'Позиция в очереди: '+job.queue_position+' · ':'')+'Прошло '+Math.max(0,Math.floor(Date.now()/1000-job.created))+' сек.';
 if(job.result_available&&job.result_revision!==resultRevision){result=await request('/api/v1/comparisons/'+task+'/result');resultRevision=job.result_revision;await displayResult();}
 if(result?.provisional){$('backgroundStatus').hidden=false;$('backgroundStatus').textContent='Предварительный результат — проверка продолжается. Список изменений может уточняться; отчёты появятся после завершения.';}
 if(job.state==='completed'){stopTimers();if(!result||result.provisional){result=await request('/api/v1/comparisons/'+task+'/result');await displayResult();}startHeartbeat();}
 else if(job.state==='failed'||job.state==='cancelled'){stopTimers();await clearLocalResult();notify(job.error||'Задача отменена.');show('upload');}
 }catch(error){if(error.status===404){stopTimers();task=null;await clearLocalResult();history.replaceState(null,'',location.pathname);show('upload');}notify(error.message+(error.status===404?'':' При сбое связи можно повторно открыть эту страницу.'));}finally{busy=false;}};
 poller=setInterval(poll,1200);await poll();}
async function clearLocalResult(){result=null;selected=null;resultRevision=-1;for(const side of ['old','new']){viewers[side].reset();if(pdfs[side])await pdfs[side].destroy();delete pdfs[side];delete documentInfos[side];pages[side]=1;}documentHeading();}
async function removeTask(){stopTimers();if(task){try{await request('/api/v1/comparisons/'+task,{method:'DELETE'});}catch(error){if(error.status!==404){notify(error.message);return false;}}}task=null;await clearLocalResult();history.replaceState(null,'',location.pathname);show('upload');return true;}
$('cancelButton').onclick=removeTask;$('newComparison').onclick=removeTask;
async function displayResult(){
 const previousID=selected?.id,previousFilter=$('categoryFilter').value;
 show('result');$('resultTitle').textContent=result.comparison_status==='unavailable'?'Сравнение текста невозможно':result.count?`Найдено изменений: ${result.count}`:'Различий не выявлено';$('resultMeta').textContent=result.employee+' · '+new Date(result.compared_at).toLocaleString('ru-RU')+(result.partial?' · Сравнение выполнено не полностью':'');
 $('changeCount').textContent=result.comparison_status==='unavailable'?'':result.count;$('warningCount').textContent=result.warnings.length||'';$('warningCount').hidden=!result.warnings.length;
 $('backgroundStatus').hidden=!result.provisional;
 for(const fmt of ['pdf','docx','json']){const link=$(fmt+'Report');link.href=api+'/api/v1/comparisons/'+task+'/reports/'+fmt;link.classList.toggle('disabled',!!result.provisional);link.setAttribute('aria-disabled',String(!!result.provisional));}
 $('printReport').disabled=!!result.provisional;
 $('printReport').onclick=()=>window.open($('pdfReport').href,'_blank','noopener');
 notify(result.comparison_status==='unavailable'?result.summary:result.partial?'Есть ограничения проверки. Откройте вкладку «Полнота проверки» перед использованием результата.':result.navigation_partial?'Текст сравнен; часть привязок к страницам неточна. Подробности — во вкладке полноты проверки.':'');
 const filter=$('categoryFilter');filter.replaceChildren(new Option('Все изменения','all'));
 for(const cat of [...new Set(result.changes.flatMap(c=>c.categories))])filter.add(new Option(labels[cat]||cat,cat));
 if([...filter.options].some(o=>o.value===previousFilter))filter.value=previousFilter;
 filter.onchange=()=>{const visible=result.changes.filter(c=>filter.value==='all'||c.categories.includes(filter.value));if(visible.length&&!visible.some(c=>c.id===selected?.id))selectChange(visible[0]);else renderList();};renderList();renderSignatures();renderWarnings();
 for(const side of ['old','new']){$(side+'DocumentName').textContent=result.documents[side].name;
 if(documentInfos[side]===undefined)documentInfos[side]=extractDocumentInfo(result.documents[side].name.replace(/\.[^.]+$/,'').replace(/_/g,' '));
 if(!pdfs[side]&&result.documents[side].pages>0){pages[side]=1;try{
  viewers[side].setPreparationStatus('Загрузка PDF для просмотра');
  const loading=pdfjs.getDocument({url:api+'/api/v1/comparisons/'+task+'/documents/'+side+'/preview',cMapUrl:'/vendor/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/vendor/pdfjs/standard_fonts/',wasmUrl:'/vendor/pdfjs/wasm/'});
  loading.onProgress=({loaded,total})=>viewers[side].setPreparationStatus('Загрузка PDF для просмотра',total>0?Math.min(100,Math.round(loaded/total*100)):null);
  pdfs[side]=await loading.promise;
  try{documentInfos[side]=await documentInfoFromPDF(pdfs[side])||documentInfos[side];}catch{}
 }catch(e){notify('Не удалось открыть страницы: '+e.message);}}}
 documentHeading();
 const visible=result.changes.filter(c=>filter.value==='all'||c.categories.includes(filter.value));
 if(visible.length)await selectChange(visible.find(c=>c.id===previousID)||visible[0],!previousID);else{selected=null;await Promise.all(['old','new'].map(side=>renderPage(side)));}
 startHeartbeat();
}
function startHeartbeat(){clearInterval(heartbeat);heartbeat=setInterval(()=>request('/api/v1/comparisons/'+task+'/heartbeat',{method:'POST'}).catch(async e=>{if(e.status===404){stopTimers();task=null;await clearLocalResult();history.replaceState(null,'',location.pathname);show('upload');notify('Срок хранения результата истёк или сервер перезапущен. Загрузите документы повторно.');}else notify(e.message);}),60000);}
function renderList(){const list=$('changeList'),previousScroll=list.scrollTop;list.replaceChildren();const cat=$('categoryFilter').value;const changes=result.changes.filter(c=>cat==='all'||c.categories.includes(cat));
 if(!changes.length){const p=document.createElement('p');p.className='empty';p.textContent=result.comparison_status==='unavailable'?'Список изменений не сформирован: есть страницы без текстового слоя. Загрузите текстовую PDF-версию или Word-файл.':result.count?'Нет изменений этой категории.':'Изменений не обнаружено. Проверьте полноту обработки во вкладке рядом.';list.append(p);}
 for(const c of changes){const btn=document.createElement('button');btn.className='change-item'+(selected?.id===c.id?' active':'');btn.dataset.id=c.id;
 const title=document.createElement('span');title.className='change-title';title.textContent=(result.changes.indexOf(c)+1)+'. '+operationLabel(c);btn.append(title);
 for(const [value,style,prefix]of [[c.details?.display_before??c.before,'removed','− '],[c.details?.display_after??c.after,'added','+ ']])if(value){const el=document.createElement('small');el.className=style;el.textContent=prefix+value.slice(0,150)+(value.length>150?'…':'');btn.append(el);}
 const badge=document.createElement('span');badge.className='badge';badge.textContent=c.categories.map(x=>labels[x]||x).join(' · ');btn.append(badge);btn.onclick=()=>selectChange(c);list.append(btn);}list.scrollTop=previousScroll;}
async function selectChange(change,scroll=true){selected=change;renderList();
 await Promise.all(['old','new'].map(side=>renderPage(side,scroll)));
}

async function renderPage(side,center=false){
 const target=selected;
 if(!pdfs[side]){viewers[side].setText(target?.details?.[side+'_context']||(side==='old'?target?.before:target?.after)||'Изменений нет. Подготавливаются страницы.');return;}
 const fresh=await viewers[side].setDocument(pdfs[side]);
 if(target!==(selected))return;
 const locations=target?.[side+'_locations']||[];viewers[side].setHighlights(locations,side);
 if(fresh||center){if(locations.length)await viewers[side].focusLocations(locations);else if(fresh)await viewers[side].goToPage(1);}
}
document.querySelectorAll('[data-direction]').forEach(button=>button.onclick=()=>{const side=button.dataset.side;if(pdfs[side])viewers[side].goToPage(pages[side]+Number(button.dataset.direction));});

document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));for(const name of ['changes','signatures','warnings'])$(name+'Tab').hidden=name!==button.dataset.tab;if(button.dataset.tab==='changes')Promise.all(['old','new'].map(side=>renderPage(side)));});
function renderSignatures(){const root=$('signaturesTab');root.replaceChildren();const intro=document.createElement('p');intro.textContent='Проверяется соответствие подписи исходному файлу для поддерживаемых алгоритмов. Доверие к сертификатам и отзыв не проверяются.';root.append(intro);const grid=document.createElement('div');grid.className='signature-grid';
 const status={valid:'Подпись соответствует файлу',invalid:'Проверка не пройдена',not_checked:'Не проверено'};
 for(const side of ['old','new']){const section=document.createElement('section');const heading=document.createElement('h2');heading.textContent=side==='old'?'Согласованная версия':'Полученная версия';section.append(heading);
 if(!result.signatures[side].length){const p=document.createElement('p');p.textContent=result.provisional?'Проверка подписей ещё не завершена.':'Подписи не предоставлены или не обнаружены.';section.append(p);}
 for(const sig of result.signatures[side]){const item=document.createElement('div');item.className='signature-item';const title=document.createElement('strong');title.textContent=status[sig.mathematical]||'Не проверено';item.append(title);const dl=document.createElement('dl');
 for(const [field,label]of [['subject','Подписант'],['issuer','Издатель'],['algorithm_name','Алгоритм'],['not_before','Действует с'],['not_after','Действует до'],['claimed_signing_time','Заявленное время подписания'],['later_revisions','Есть последующие ревизии PDF'],['message','Сведения']])if(sig[field]!==undefined){const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');dd.textContent=String(sig[field]);dl.append(dt,dd);}item.append(dl);section.append(item);}
 grid.append(section);}root.append(grid);}
function renderWarnings(){const root=$('warningsTab');root.replaceChildren();const h=document.createElement('h2');h.textContent=result.comparison_status==='unavailable'?'Сравнение текста не выполнено. OCR выключен.':result.provisional?'Точные изменения доступны; уточнение категорий и проверка подписей продолжаются':result.partial?'Сравнение выполнено не полностью':'Проверки согласованного объёма завершены';root.append(h);const ul=document.createElement('ul');for(const warning of result.warnings){const li=document.createElement('li');li.textContent=warning;ul.append(li);}root.append(ul);
 const p=document.createElement('p');p.textContent='Страницы Word относятся к отображению комплекса. Абзацы PDF восстановлены по геометрии. Шрифты, размеры, цвет и изображения не входят в объём сравнения.';root.append(p);
 const areas={text:'Текст',tables:'Таблицы',formatting:'Абзацы и переносы',signatures:'Подписи',navigation:'Привязка к страницам'};const values={unavailable:'Текст недоступен без OCR',not_performed:'Не выполнено',pending:'Подготавливается',complete:'Проверено',partial:'Есть ограничения',reconstructed:'Структура восстановлена автоматически; требует внимания',paragraphs_and_breaks:'Проверены границы абзацев и явные переносы',not_applicable:'Не проверяется для пары с PDF',integrity_only:'Только доступная проверка соответствия файлу',not_provided:'Подписи не предоставлены или не обнаружены',not_checked:'Не проверено'};for(const side of ['old','new']){const heading=document.createElement('h2');heading.textContent=side==='old'?'Согласованная версия':'Полученная версия';root.append(heading);const list=document.createElement('ul');for(const [area,value]of Object.entries(result.documents[side].coverage)){const li=document.createElement('li');li.textContent=(areas[area]||area)+': '+(values[value]||value);list.append(li);}root.append(list);}}
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(result)for(const side of ['old','new'])viewers[side].refreshLayout();},250);});
try{const config=await fetch('/config.json',{cache:'no-store'}).then(r=>r.json());const local=localStorage.getItem('atlas-api');
 // Migrate old automatic/direct selections once; keep subsequent manual choices.
 const migrated=localStorage.getItem('atlas-api-routing')==='proxy-v1';
 await connect((migrated&&local)||config.api_url||'/comparison-api');
}catch(error){$('connectionError').textContent=error.message;$('connectionError').hidden=false;openSettings();}
