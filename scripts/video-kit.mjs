// Shared machinery for the Guía de uso videos (scripts/guide-video*.mjs): a temporary server with demonstration
// data, captions and cursor drawn by the page, the browser screencast and the MP4 + .srt assembly.
// Nothing real is used or sent: temporary data, a local SMTP sink and ADG_VERIFACTU_NETWORK=off.
import {authenticateTest} from '../tests/auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn,spawnSync} from 'node:child_process';
import {createServer} from 'node:net';
import {seed} from '../dist/model.js';
import {initializeLedger} from '../dist/ledger.js';
import {adgCompany} from '../dist/reference.js';

const root=join(dirname(fileURLToPath(import.meta.url)),'..'),output=join(root,'dist/assets/guide');
const size={width:1280,height:720};

// arquitecturadeguardia with the demonstration clients and no invoices.
export function demoState(){const db=initializeLedger(seed());db.company={...adgCompany,email:'estudio@arquitecturadeguardia.example'};db.adgProfileVersion=1;db.demoMarked=true;db.invoices=[];return db;}

const css=`#toast{bottom:150px!important}
 .v-layer{position:fixed;margin:0;padding:0;border:0;background:transparent;overflow:visible;pointer-events:none;inset:auto}
 #v-caption{left:50%;bottom:28px;transform:translateX(-50%);max-width:1040px;width:max-content;background:rgba(22,36,29,.9);color:#fff;font:600 23px/1.45 -apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;padding:13px 24px;border-radius:12px;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,.25);transition:opacity .25s}
 #v-caption:empty{opacity:0}
 #v-caption.top{top:24px;bottom:auto}
 #v-cursor{left:0;top:0;width:26px;height:26px;transition:transform .75s cubic-bezier(.45,0,.2,1);transform:translate(640px,360px)}
 #v-cursor svg{width:26px;height:26px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
 #v-cursor i{position:absolute;left:-17px;top:-17px;width:34px;height:34px;border-radius:50%;border:3px solid #2f7d5b;opacity:0}
 #v-cursor.click i{animation:v-ring .55s ease-out}
 @keyframes v-ring{from{opacity:.95;transform:scale(.35)}to{opacity:0;transform:scale(1.7)}}
 #v-card{inset:0;width:100vw;height:100vh;display:none;align-items:center;justify-content:center;flex-direction:column;gap:14px;background:#f6f8f7;color:#1f3a2e;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;text-align:center}
 #v-card.on{display:flex}#v-card strong{font-size:44px;line-height:1.2;max-width:900px}#v-card span{font-size:22px;color:#5d6f63}#v-card img{width:74px;margin-bottom:8px}`;

// Captions, cursor and title cards live in the top layer (popover) so they stay above dialogs too. They are
// created on every page load, because switching issuer reloads the application.
function overlay(css){const setup=()=>{if(document.getElementById('v-caption'))return;
 const style=document.createElement('style');style.textContent=css;document.head.append(style);
 const layer=(id,html='')=>{const e=document.createElement('div');e.id=id;e.className='v-layer';e.popover='manual';e.innerHTML=html;document.body.append(e);e.showPopover();return e;};
 const card=layer('v-card'),caption=layer('v-caption'),cursor=layer('v-cursor','<i></i><svg viewBox="0 0 24 24"><path d="M3 2l17 9.5-7.2 1.6L9.5 21z" fill="#fff" stroke="#1f2b25" stroke-width="1.6" stroke-linejoin="round"/></svg>');
 window.__video={
  caption:text=>{caption.textContent=text;},
  card:(title,subtitle)=>{card.innerHTML=title?`<img src="assets/arquitecturadeguardia-logo.png" alt=""><strong>${title}</strong><span>${subtitle||''}</span>`:'';card.classList.toggle('on',!!title);cursor.style.opacity=title?0:1;},
  move:(x,y)=>{cursor.style.transform=`translate(${x-3}px,${y-2}px)`;caption.classList.toggle('top',y>innerHeight-170);},
  click:()=>{cursor.classList.remove('click');void cursor.offsetWidth;cursor.classList.add('click');},
  // A dialog opened later sits above the layers: show them again so they come back on top.
  raise:()=>{for(const e of [card,caption,cursor]){e.hidePopover();e.showPopover();}}};
 // The moment any dialog opens, put the layers back on top (before it is painted, so the caption never fades).
 new MutationObserver(()=>window.__video.raise()).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup();}

// setup({post,smtpPort}) prepares the data and returns {start:'/path', ...}; steps(video,data) records the tour.
export async function recordGuideVideo({name,title,subtitle,endTitle,endSubtitle,setup,steps,port=4197}){
 assert.equal(spawnSync('ffmpeg',['-version']).status,0,'Instala ffmpeg (brew install ffmpeg).');
 // Local SMTP sink: an e-mail step really sends, but only to this process.
 const smtp=createServer(socket=>{let buffer='',data=false;const reply=text=>socket.write(text+'\r\n');reply('220 demostracion');
  socket.on('data',chunk=>{buffer+=chunk.toString('latin1');let index;
   while((index=buffer.indexOf('\r\n'))>=0){const line=buffer.slice(0,index);buffer=buffer.slice(index+2);
    if(data){if(line==='.'){data=false;reply('250 Aceptado');}continue;}
    const verb=line.slice(0,4).toUpperCase();if(verb==='DATA'){data=true;reply('354 Fin con .');continue;}if(verb==='QUIT'){reply('221 Adiós');socket.end();continue;}reply('250 OK');}});});
 await new Promise(resolve=>smtp.listen(0,'127.0.0.1',resolve));
 const temp=await mkdtemp(join(tmpdir(),'adg-video-')),base=`http://localhost:${port}`;
 const server=spawn('python3',['serve.py'],{cwd:root,env:{...process.env,ADG_DATA_DIR:join(temp,'data'),ADG_PORT:String(port),ADG_VERIFACTU_NETWORK:'off'},stdio:'ignore'});
 let browser;
 const post=async(path,body,headers={})=>{const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(body)});const value=await response.json();assert.ok(response.ok,value.error);return value;};
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  const qa=await authenticateTest(base);globalThis.fetch=qa.fetch;
  const data=await setup({post,smtpPort:smtp.address().port});
  // Headless Chrome keeps 87 px of the window for its own frame: the window is taller so that the page and
  // the captured area are both exactly 1280×720 (with an emulated viewport the capture would cut the bottom).
  browser=await chromium.launch({headless:true,args:[`--window-size=${size.width},${size.height+87}`],executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:null,bypassCSP:true,acceptDownloads:true});await context.addInitScript(overlay,css);
  const page=await context.newPage();await qa.page(page);page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+(data.start||'/'));await page.getByRole('heading',{name:'Tus facturas'}).waitFor();
  assert.deepEqual(await page.evaluate(()=>[innerWidth,innerHeight]),[size.width,size.height],'La ventana no mide 1280×720: ajusta --window-size.');

  // Timeline: frames from the browser screencast, captions timed with the same clock.
  const cdp=await context.newCDPSession(page),frames=[],cues=[];
  cdp.on('Page.screencastFrame',async({data,metadata,sessionId})=>{frames.push({data,time:metadata.timestamp});try{await cdp.send('Page.screencastFrameAck',{sessionId});}catch{}});
  const clock=()=>Date.now()/1000,wait=ms=>page.waitForTimeout(ms),last={caption:'',move:[640,360]};
  const call=(method,...args)=>{if(method in last)last[method]=method==='caption'?args[0]:args;return page.evaluate(([method,args])=>window.__video[method](...args),[method,args]);};
  const center=async locator=>{await locator.evaluate(e=>e.scrollIntoView({block:'center',behavior:'instant'}));await wait(250);const box=await locator.boundingBox();return [box.x+Math.min(box.width/2,160),box.y+box.height/2];};
  const say=async(text,ms=2600)=>{cues.push({start:clock(),text});await call('caption',text);await wait(ms);};
  const point=async(locator,pause=850)=>{await call('move',...await center(locator));await wait(pause);};
  // A dialog opened by the click covers the layers: bring them back on top at once, and again once it has settled.
  const click=async(locator,after=700)=>{await point(locator);await call('click');await locator.click();await wait(150);await call('raise');await wait(Math.max(0,after-150));await call('raise');};
  const type=async(locator,text)=>{await click(locator,250);await locator.pressSequentially(text,{delay:55});await wait(350);};
  const select=async(locator,value,after=1100)=>{await point(locator);await call('click');await locator.selectOption(value);await wait(after);};
  // After a reload (issuer switch) the page draws the layers again: restore caption and cursor.
  const restore=async()=>{await page.waitForFunction(()=>!!window.__video);await call('move',...last.move);await call('caption',last.caption);};
  const video={page,wait,call,say,point,click,type,select,restore};
  await cdp.send('Page.startScreencast',{format:'jpeg',quality:88,maxWidth:size.width,maxHeight:size.height,everyNthFrame:1});
  const started=clock();
  await call('card',title,subtitle);await wait(3500);await call('card','');await wait(400);
  await steps(video,data);
  await call('caption','');cues.push({start:clock(),text:''});
  await call('card',endTitle,endSubtitle);await wait(3500);
  const ended=clock();await cdp.send('Page.stopScreencast');await wait(300);
  assert.deepEqual(errors,[]);

  // Assemble: each frame lasts until the next one; captions use the same timeline.
  // Standard limited-range yuv420p/High: plays in QuickTime, iOS, Android and WhatsApp.
  const work=join(temp,'frames');await mkdir(work,{recursive:true});await mkdir(output,{recursive:true});
  frames.sort((a,b)=>a.time-b.time);const t0=Math.min(started,frames[0].time);
  const list=[];for(const [n,frame] of frames.entries()){const file=join(work,`f${String(n).padStart(5,'0')}.jpg`);await writeFile(file,Buffer.from(frame.data,'base64'));
   const next=n+1<frames.length?frames[n+1].time:ended;list.push(`file '${file}'`,`duration ${Math.max(0.001,next-frame.time).toFixed(3)}`);}
  list.push(`file '${join(work,`f${String(frames.length-1).padStart(5,'0')}.jpg`)}'`);await writeFile(join(work,'list.txt'),list.join('\n'));
  const mp4=join(output,name+'.mp4');
  const encode=spawnSync('ffmpeg',['-y','-loglevel','error','-f','concat','-safe','0','-i',join(work,'list.txt'),'-vf',`fps=30,scale=${size.width}:${size.height}:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p`,'-c:v','libx264','-profile:v','high','-level','4.0','-pix_fmt','yuv420p','-color_range','tv','-preset','slow','-crf','24','-movflags','+faststart',mp4]);
  assert.equal(encode.status,0,String(encode.stderr));
  assert.equal(spawnSync('ffmpeg',['-y','-loglevel','error','-ss','6','-i',mp4,'-frames:v','1','-q:v','3',join(output,name+'.jpg')]).status,0);
  const stamp=s=>{const ms=Math.max(0,Math.round((s-t0)*1000));return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;};
  const srt=cues.map((cue,n)=>cue.text?`${stamp(cue.start)} --> ${stamp(cues[n+1]?.start??ended)}\n${cue.text}\n`:'').filter(Boolean);
  await writeFile(join(output,name+'.srt'),srt.map((cue,n)=>`${n+1}\n${cue}`).join('\n'));
  console.log(`Vídeo: ${mp4} · ${(ended-started).toFixed(1)} s · ${frames.length} fotogramas · ${srt.length} subtítulos`);
 }finally{await browser?.close();server.kill();smtp.close();await rm(temp,{recursive:true,force:true});}
}
