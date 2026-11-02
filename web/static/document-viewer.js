// Continuous PDF strip. Only pages near the viewport retain bitmap canvases.
export function pageAtOffset(bounds,offset){
 let lo=0,hi=bounds.length-1;
 while(lo<hi){const mid=Math.floor((lo+hi)/2);if(bounds[mid].bottom<offset)lo=mid+1;else hi=mid;}
 if(lo>0&&offset<bounds[lo].top&&offset-bounds[lo-1].bottom<bounds[lo].top-offset)return lo-1;
 return lo;
}
export function centeredScrollTop(point,height,total){return Math.max(0,Math.min(total-height,point-height/2));}

export class DocumentViewer{
 constructor(root,{onPageChange,onError,onStatus}={}){
  this.root=root;this.onPageChange=onPageChange||(()=>{});this.onError=onError||(()=>{});this.onStatus=onStatus||(()=>{});
  this.epoch=0;this.navigation=0;this.records=[];this.highlights=[];this.pdf=null;this.frame=null;this.busy=false;
  root.addEventListener('scroll',()=>this.schedule(),{passive:true});
  for(const name of ['wheel','pointerdown','keydown'])root.addEventListener(name,()=>{this.navigation++;},{passive:true});
  this.observer=new ResizeObserver(()=>this.refreshLayout());this.observer.observe(root);
 }
 reset(){
  this.epoch++;this.navigation++;this.ready=null;this.pdf=null;this.highlights=[];this.pending=[];this.pendingFocus=null;this.pendingPage=null;
  for(const record of this.records)this.release(record);
  this.records=[];this.root.replaceChildren();this.root.scrollTop=0;this.width=0;this.height=0;
 }
 setText(text){
  if(this.pdf)this.reset();
  this.ensurePending();
  this.textNode.textContent=text;this.onPageChange(0,0);
 }
 ensurePending(){
  if(this.pendingNode&&this.root.contains(this.pendingNode))return;
  this.pendingNode=document.createElement('div');this.pendingNode.className='pending-preview';
  this.pendingNode.innerHTML='<details class="extracted-context"><summary>Текст выбранного фрагмента</summary><pre class="text-preview"></pre></details><div class="page page-skeleton" aria-hidden="true"><div class="skeleton-lines"></div></div>';
  this.root.replaceChildren(this.pendingNode);this.textNode=this.pendingNode.querySelector('pre');
  this.setPreparationStatus('Подготовка просмотра страниц');
 }
 setPreparationStatus(message,percent=null){
  if(this.pdf)return;
  this.ensurePending();this.onStatus(message+(percent===null?'':' · '+percent+'%'));
 }
 async setDocument(pdf){
  if(this.pdf===pdf){await this.ready;return false;}
  this.reset();this.pdf=pdf;const epoch=this.epoch;
  this.ready=(async()=>{
   const first=await pdf.getPage(1);if(epoch!==this.epoch)return;
   const base=first.getViewport({scale:1});
   this.strip=document.createElement('div');this.strip.className='pdf-strip';this.root.replaceChildren(this.strip);
   for(let number=1;number<=pdf.numPages;number++){
    const node=document.createElement('div');node.className='page pdf-sheet';node.dataset.page=number;
    node.setAttribute('aria-label','Страница '+number);node.setAttribute('aria-busy','true');
    const label=document.createElement('span');label.className='page-loading';label.textContent='Отрисовка страницы '+number;
    const progress=document.createElement('progress');progress.setAttribute('aria-label','Отрисовка страницы '+number);label.append(progress);
    const canvas=document.createElement('canvas');canvas.hidden=true;canvas.setAttribute('aria-label','Страница '+number);
    const overlay=document.createElement('div');overlay.className='highlights';node.append(canvas,overlay,label);this.strip.append(node);
    this.records.push({number,node,canvas,overlay,label,base:base,proxy:number===1?first:null,paintedWidth:0});
   }
   this.refreshLayout(false);this.onPageChange(1,pdf.numPages);this.schedule();
  })();
  await this.ready;return epoch===this.epoch;
 }
 bounds(){return this.records.map(r=>({top:r.node.offsetTop,bottom:r.node.offsetTop+r.node.offsetHeight}));}
 refreshLayout(preserve=true){
  if(!this.pdf||!this.records.length||!this.root.clientWidth||!this.root.clientHeight)return;
  const width=Math.max(40,this.root.clientWidth-24),height=this.root.clientHeight;
  if(Math.abs(width-this.width)<1&&height===this.height)return;
  const oldBounds=this.bounds(),index=pageAtOffset(oldBounds,this.root.scrollTop+(this.height||height)/2);
  const fraction=(this.root.scrollTop+(this.height||height)/2-oldBounds[index].top)/Math.max(1,oldBounds[index].bottom-oldBounds[index].top);
  this.width=width;this.height=height;
  // End padding lets even a change at the very start/end be centred.
  this.strip.style.paddingBlock=Math.ceil(height/2)+'px';
  for(const r of this.records){r.node.style.height=(width*r.base.height/r.base.width)+'px';if(Math.abs(r.paintedWidth-width)>=1)this.release(r);}
  if(preserve){const r=this.records[index];this.root.scrollTop=r.node.offsetTop+fraction*r.node.offsetHeight-height/2;}
  if(this.pendingFocus){const locations=this.pendingFocus;this.pendingFocus=null;this.focusLocations(locations);}
  else if(this.pendingPage){const number=this.pendingPage;this.pendingPage=null;this.goToPage(number);}
  this.schedule();
 }
 async geometry(record){
  if(record.proxy)return record.proxy;
  const epoch=this.epoch,pdf=this.pdf,proxy=await pdf.getPage(record.number);
  if(epoch!==this.epoch)return null;
  record.proxy=proxy;const base=proxy.getViewport({scale:1});
  const before=record.node.offsetHeight;record.base=base;record.node.style.height=(this.width*base.height/base.width)+'px';
  // Mixed page sizes must not shift the page currently being read.
  const delta=record.node.offsetHeight-before;
  if(delta&&record.node.offsetTop+before<this.root.scrollTop)this.root.scrollTop+=delta;
  return proxy;
 }
 setHighlights(locations,side){
  this.highlights=locations||[];this.side=side;
  for(const r of this.records)this.paintHighlights(r);
 }
 paintHighlights(record){
  record.overlay.replaceChildren();
  for(const loc of this.highlights.filter(l=>l.page===record.number)){
   const box=document.createElement('div');box.className='highlight '+this.side;
   const[x0,y0,x1,y1]=loc.bbox,base=record.base;
   Object.assign(box.style,{left:x0/base.width*100+'%',top:y0/base.height*100+'%',
    width:Math.max(.3,(x1-x0)/base.width*100)+'%',height:Math.max(.5,(y1-y0)/base.height*100)+'%'});
   record.overlay.append(box);
  }
 }
 async focusLocations(locations){
  const loc=locations?.[0];if(!loc)return;
  if(!this.root.clientHeight){this.pendingFocus=locations;return;}
  const record=this.records[loc.page-1];if(!record)return;
  const nav=++this.navigation,epoch=this.epoch;
  await this.geometry(record);if(nav!==this.navigation||epoch!==this.epoch)return;
  const boxes=locations.filter(l=>l.page===loc.page).map(l=>l.bbox);
  const middle=(Math.min(...boxes.map(b=>b[1]))+Math.max(...boxes.map(b=>b[3])))/2;
  const point=record.node.offsetTop+middle/record.base.height*record.node.offsetHeight;
  this.root.scrollTo({top:centeredScrollTop(point,this.root.clientHeight,this.root.scrollHeight),behavior:'auto'});
  this.updatePage();this.schedule();
 }
 async goToPage(number){
  if(!this.records.length)return;
  if(!this.root.clientHeight){this.pendingPage=number;return;}
  const record=this.records[Math.max(1,Math.min(this.records.length,number))-1];
  const nav=++this.navigation,epoch=this.epoch;
  await this.geometry(record);if(nav!==this.navigation||epoch!==this.epoch)return;
  const offset=record.node.offsetTop+Math.min(record.node.offsetHeight,this.root.clientHeight)/2;
  this.root.scrollTo({top:centeredScrollTop(offset,this.root.clientHeight,this.root.scrollHeight),behavior:'auto'});
  this.updatePage();this.schedule();
 }
 updatePage(){
  if(!this.records.length)return;
  const current=pageAtOffset(this.bounds(),this.root.scrollTop+this.root.clientHeight/2)+1;
  this.onPageChange(current,this.records.length);
 }
 schedule(){
  if(this.frame)return;
  this.frame=requestAnimationFrame(()=>{this.frame=null;this.updatePage();this.queueVisible();});
 }
 queueVisible(){
  if(!this.pdf||!this.root.clientHeight||!this.records.length)return;
  const top=this.root.scrollTop,bottom=top+this.root.clientHeight,margin=this.root.clientHeight*.7;
  const bounds=this.bounds(),center=(top+bottom)/2;
  this.pending=this.records.filter((r,i)=>bounds[i].bottom>=top-margin&&bounds[i].top<=bottom+margin)
   .sort((a,b)=>Math.abs((bounds[a.number-1].top+bounds[a.number-1].bottom)/2-center)-Math.abs((bounds[b.number-1].top+bounds[b.number-1].bottom)/2-center));
  const nearby=new Set(this.pending);
  for(const r of this.records)if(!nearby.has(r))this.release(r);
  this.drain();
 }
 release(record){
  if(record.renderTask){record.renderTask.cancel();record.renderTask=null;}
  record.canvas.width=record.canvas.height=0;record.canvas.hidden=true;record.paintedWidth=0;
  record.node.classList.remove('is-rendered');record.node.setAttribute('aria-busy','true');
 }
 async drain(){
  if(this.busy)return;this.busy=true;
  try{
   while(this.pending?.length){
    const record=this.pending.shift();if(record.failed||record.paintedWidth===this.width)continue;
    const epoch=this.epoch,width=this.width;
    try{
     const proxy=await this.geometry(record);if(!proxy||epoch!==this.epoch)continue;
     const viewport=proxy.getViewport({scale:width/record.base.width});
     const ratio=Math.min(window.devicePixelRatio||1,2,Math.sqrt(4000000/(viewport.width*viewport.height)));
     const canvas=record.canvas;canvas.width=Math.max(1,Math.floor(viewport.width*ratio));canvas.height=Math.max(1,Math.floor(viewport.height*ratio));
     const render=proxy.render({canvasContext:canvas.getContext('2d'),viewport,transform:ratio!==1?[ratio,0,0,ratio,0,0]:null});record.renderTask=render;
     await render.promise;
     if(epoch!==this.epoch||width!==this.width||record.renderTask!==render)continue;
     record.renderTask=null;record.paintedWidth=width;canvas.hidden=false;
     record.node.classList.add('is-rendered');record.node.setAttribute('aria-busy','false');this.paintHighlights(record);
    }catch(error){
     if(error.name==='RenderingCancelledException')continue;
     if(epoch!==this.epoch)continue;
     record.failed=true;record.label.textContent='Не удалось отобразить страницу '+record.number;
     record.node.setAttribute('aria-busy','false');this.onError(error);
    }
   }
  }finally{this.busy=false;}
 }
}
