const types=[['Дополнительное соглашение','Дополнительное\\s+соглашение'],['Договор','Договор'],['Соглашение','Соглашение'],['Акт','Акт'],['Счёт','Сч[её]т'],['Доверенность','Доверенность'],['Протокол','Протокол'],['Спецификация','Спецификация'],['Накладная','Накладная'],['Уведомление','Уведомление'],['Заявление','Заявление'],['Приказ','Приказ']];
const numberPattern=/№\s*([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9._/\\–—-]{0,79})/u;
export function extractDocumentInfo(text){
 const lines=text.replace(/\u00a0/g,' ').split(/\r?\n/).map(t=>t.trim()).filter(Boolean).slice(0,35);
 for(let i=0;i<lines.length;i++){
  const line=lines[i];if(line.length>180)continue;
  const type=types.find(([,pattern])=>new RegExp('^'+pattern+'(?=$|[\\s№:—-])','iu').test(line));
  if(!type)continue;
  let match=line.match(numberPattern);
  if(!match)for(const next of lines.slice(i+1,i+3)){if(/^№/.test(next)){match=next.match(numberPattern);break;}}
  if(!match&&i>8&&line!==line.toUpperCase())continue;
  const number=match&&/\d/.test(match[1])?match[1].replace(/[.]$/,''):null;
  return {type:type[0],number,label:type[0]+(number?' №'+number:'')};
 }
 return null;
}
export async function documentInfoFromPDF(pdf){
 const page=await pdf.getPage(1),content=await page.getTextContent();
 const lines=[];let line='',previousY=null;
 for(const item of content.items){
  if(!('str' in item))continue;
  const y=item.transform?.[5];
  if(line&&previousY!==null&&Math.abs(y-previousY)>3){lines.push(line);line='';}
  line+=(line?' ':'')+item.str;previousY=y;
  if(item.hasEOL){lines.push(line);line='';previousY=null;}
 }
 if(line)lines.push(line);
 return extractDocumentInfo(lines.join('\n'));
}
