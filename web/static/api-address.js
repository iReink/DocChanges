// Relative API addresses stay on the page origin, including HTTPS tunnel hosts.
export function normalURL(value, origin) {
 const raw=value.trim();
 if(/^[a-z][a-z\d+.-]*:\/\//i.test(raw)&&!/^https?:\/\//i.test(raw))
  throw new Error('Поддерживаются только HTTP(S)-адреса.');
 const explicit=/^https?:\/\//i.test(raw);
 const relative=raw.startsWith('/')&&!raw.startsWith('//');
 const url=new URL(relative?raw:explicit?raw:'http://'+raw,origin);
 if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)
  throw new Error('Укажите HTTP(S)-адрес API без пароля, параметров и фрагмента.');
 // A bare LAN IP/hostname retains the familiar direct API port.
 if(!relative&&!explicit&&!url.port)url.port='8000';
 return url.href.replace(/\/$/,'');
}
