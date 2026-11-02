import * as pdfjs from '/pdfjs/pdf.mjs';
pdfjs.GlobalWorkerOptions.workerSrc = '/pdfjs/pdf.worker.mjs';
const $ = id => document.getElementById(id);
// Canvas preview also works in embedded browsers without a native PDF viewer.
const pdfView = document.createElement('div');
pdfView.id = 'pdf'; pdfView.hidden = true; pdfView.className = 'pdfview';
pdfView.innerHTML = '<div class="pdf-nav"><button id="prevpage" class="quiet" aria-label="Предыдущая страница">←</button><span id="pdfpage">Загрузка PDF…</span><button id="nextpage" class="quiet" aria-label="Следующая страница">→</button></div><div class="pdf-canvas"><canvas id="canvas"></canvas></div>';
$('pdf').replaceWith(pdfView);
let pdfDocument, pdfPage = 1, renderTask, previewVersion = 0;
async function renderPDF() {
  if (!pdfDocument) return;
  if (renderTask) { renderTask.cancel(); try { await renderTask.promise; } catch {} }
  const page = await pdfDocument.getPage(pdfPage);
  const scale = Math.min(2, ($('pdf').clientWidth - 48) / page.getViewport({scale:1}).width);
  const viewport = page.getViewport({scale});
  const canvas = $('canvas'); const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * ratio); canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
  $('pdfpage').textContent = `${pdfPage} / ${pdfDocument.numPages}`;
  $('prevpage').disabled = pdfPage === 1; $('nextpage').disabled = pdfPage === pdfDocument.numPages;
  renderTask = page.render({canvasContext:canvas.getContext('2d'),viewport,transform:[ratio,0,0,ratio,0,0]});
  try { await renderTask.promise; } catch(e) { if(e.name !== 'RenderingCancelledException') notice('Ошибка просмотра PDF: '+e.message); }
}
$('prevpage').onclick = () => { if(pdfPage>1){pdfPage--;renderPDF();} };
$('nextpage').onclick = () => { if(pdfDocument && pdfPage<pdfDocument.numPages){pdfPage++;renderPDF();} };
let resizeTimer;
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderPDF,150);});
let file, job, view = 'preview', busy = false, timer, renderedPages = -1, markdown = '';
const terminal = new Set(['completed', 'cancelled', 'failed']);
function notice(text) { $('notice').hidden = !text; $('notice').textContent = text || ''; }
function time(seconds) { const n = Math.max(0, Math.floor(seconds)); return `${String(Math.floor(n / 60)).padStart(2,'0')}:${String(n % 60).padStart(2,'0')}`; }
async function api(path, options) {
  const response = await fetch(`/api/${path}`, options);
  if (!response.ok) { let message; try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch { message = `Ошибка HTTP ${response.status}`; } const error = new Error(message); error.status = response.status; throw error; }
  return response;
}
function controls() {
  $('start').disabled = busy || !file;
  $('replace').disabled = busy || !file;
  $('cancel').hidden = !busy;
  $('dpi').disabled = $('tokens').disabled = busy;
  for (const id of ['copy','download','json']) $(id).disabled = !job?.pages?.length;
}
async function selectFile(next) {
  if (!next || busy) return;
  if (!/\.pdf$/i.test(next.name)) return notice('Выберите файл в формате PDF.');
  if (next.size > 50 * 1024 * 1024) return notice('Файл больше 50 МБ.');
  file = next; job = null; markdown = ''; renderedPages = -1;
  sessionStorage.removeItem('xiaomi-job');
  $('pdf').hidden = false; $('drop').hidden = true;
  $('filename').textContent = file.name; $('filemeta').textContent = file.size < 1048576 ? `${Math.ceil(file.size/1024)} КБ` : `${(file.size / 1048576).toFixed(1)} МБ`;
  $('stage').textContent = 'Документ готов'; $('elapsed').textContent = '00:00'; $('progress').style.width = '0%';
  $('pagecount').textContent = 'Markdown'; $('stats').textContent = 'Ожидание запуска';
  $('empty').hidden = false; $('preview').hidden = $('source').hidden = true;
  notice(''); controls();
  const version = ++previewVersion;
  try {
    const document = await pdfjs.getDocument({data:new Uint8Array(await file.arrayBuffer()),cMapUrl:'/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs/standard_fonts/',wasmUrl:'/pdfjs/wasm/'}).promise;
    if (version !== previewVersion) { await document.destroy(); return; }
    if (pdfDocument) await pdfDocument.destroy();
    pdfDocument = document; pdfPage = 1; await renderPDF();
  } catch(e) { notice('Не удалось открыть PDF: '+e.message); }
}
$('file').onchange = e => { selectFile(e.target.files[0]); e.target.value = ''; };
$('drop').onclick = () => $('file').click();
$('choose').onclick = e => { e.stopPropagation(); $('file').click(); };
$('replace').onclick = () => $('file').click();
$('drop').onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('file').click(); } };
for (const event of ['dragover','dragleave','drop']) $('drop').addEventListener(event,e=>{e.preventDefault();$('drop').classList.toggle('drag',event==='dragover');if(event==='drop')selectFile(e.dataTransfer.files[0]);});
function switchView() {
  const has = Boolean(job?.pages?.length);
  $('empty').hidden = has; $('preview').hidden = !has || view !== 'preview'; $('source').hidden = !has || view !== 'source';
  document.querySelectorAll('[data-view]').forEach(b => { b.classList.toggle('selected',b.dataset.view===view); b.setAttribute('aria-selected', String(b.dataset.view===view)); });
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;switchView();});
function ticker() { if (job) $('elapsed').textContent = time((job.finished_at || Date.now()/1000) - job.started_at); }
async function render() {
  $('stage').textContent = job.cancel_requested && !terminal.has(job.status) ? 'Остановка…' : job.stage;
  $('progress').style.width = `${job.completed_pages / job.total_pages * 100}%`;
  $('pagecount').textContent = `${job.completed_pages} / ${job.total_pages} стр.`;
  $('device').textContent = job.device ? `Устройство: ${job.device.toUpperCase()} · загрузка модели ${job.model_load_seconds} с` : 'Первый запуск: загрузка модели';
  const seconds = job.pages.reduce((sum,p)=>sum+p.seconds,0);
  $('stats').textContent = `${job.completed_pages} стр. · ${seconds.toFixed(1)} с обработки · ${job.pages.reduce((sum,p)=>sum+p.tokens,0)} токенов`;
  if (renderedPages !== job.pages.length) {
    markdown = job.pages.map(p=>`<!-- Страница ${p.page} -->\n\n${p.markdown}`).join('\n\n---\n\n');
    $('source').textContent = markdown;
    if (job.pages.length) {
      // Only server-sanitized HTML is inserted. No model HTML is trusted directly.
      const html = await (await api(`jobs/${job.id}/result?format=html`)).text();
      $('preview').innerHTML = html;
    }
    renderedPages = job.pages.length;
  }
  switchView(); ticker(); controls();
}
async function poll() {
  try {
    job = await (await api(`jobs/${job.id}`)).json();
    busy = !terminal.has(job.status);
    await render();
    if (busy) { timer = setTimeout(poll,1000); return; }
    $('cancel').disabled = false;
    if (job.error) notice(job.error);
    else if (job.pages.some(p=>p.truncated)) notice('Достигнут лимит токенов: часть результата может быть обрезана. Увеличьте лимит в параметрах и повторите запуск.');
    else if (job.status === 'cancelled') notice('Обработка остановлена. Готовые страницы доступны для скачивания.');
  } catch(e) {
    if (e.status === 404) { busy=false; sessionStorage.removeItem('xiaomi-job'); $('stage').textContent='Задание недоступно'; controls(); notice(e.message); return; }
    notice(`${e.message} Повторное подключение через 3 секунды.`); timer = setTimeout(poll,3000);
  }
}
$('start').onclick = async () => {
  notice(''); busy = true; renderedPages = -1; job = null; controls();
  $('stage').textContent = 'Передача PDF…'; $('elapsed').textContent = '00:00'; $('progress').style.width = '0%';
  $('empty').hidden = false; $('preview').hidden = $('source').hidden = true;
  const data = new FormData(); data.append('file',file); data.append('dpi',$('dpi').value); data.append('max_tokens',$('tokens').value);
  try { job = await (await api('jobs',{method:'POST',body:data})).json(); sessionStorage.setItem('xiaomi-job',job.id); clearTimeout(timer); poll(); }
  catch(e) { busy = false; $('stage').textContent = 'Не удалось запустить'; notice(e.message); controls(); }
};
$('cancel').onclick = async () => { if(!job)return; $('cancel').disabled=true; try { await api(`jobs/${job.id}/cancel`,{method:'POST'}); $('stage').textContent='Остановка…'; } catch(e){notice(e.message);$('cancel').disabled=false;} };
$('copy').onclick = async () => { try { await navigator.clipboard.writeText(markdown); $('copy').textContent='Скопировано'; setTimeout(()=>$('copy').textContent='Копировать',1500); } catch { notice('Не удалось скопировать. Используйте скачивание .md.'); } };
function download(format) { const a = document.createElement('a'); a.href=`/api/jobs/${job.id}/result?format=${format}`; a.download=`result.${format}`; a.click(); }
$('download').onclick=()=>download('md'); $('json').onclick=()=>download('json');
async function health() { try { const h=await(await api('health')).json(); $('connection').textContent=h.model_loaded?'● Модель загружена':'● Сервер подключён'; } catch { $('connection').textContent='○ Сервер недоступен'; } }
setInterval(ticker,250); setInterval(health,10000); health();
const saved = sessionStorage.getItem('xiaomi-job');
if (saved && /^[a-f0-9]{32}$/.test(saved)) { api(`jobs/${saved}`).then(r=>r.json()).then(j=>{job=j;busy=!terminal.has(j.status);$('filename').textContent=`${j.filename} · PDF можно загрузить повторно для просмотра`;controls();poll();}).catch(()=>sessionStorage.removeItem('xiaomi-job')); }
