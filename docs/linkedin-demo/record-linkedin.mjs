// Dedicated extension of web/scripts/record-demo.mjs. Fictional fixtures only.
// No backend is started. All /api requests are fulfilled here; remote traffic is blocked.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createHash } from 'node:crypto';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const web=path.join(root,'web');
const require=createRequire(path.join(web,'package.json'));
const {chromium}=require('@playwright/test');
const {createServer}=await import(pathToFileURL(path.join(web,'node_modules/vite/dist/node/index.js')));
const sha=async p=>createHash('sha256').update(await fs.readFile(p)).digest('hex');
const original=await sha(path.join(root,'docs/demo.mp4'));
await fs.mkdir(path.join(here,'ui'),{recursive:true});
await fs.mkdir(path.join(here,'validation'),{recursive:true});
const server=await createServer({root:web,server:{host:'127.0.0.1',port:4187,strictPort:true,hmr:false},logLevel:'error'});
await server.listen();
let browser;
try {
 const chrome=process.env.DTA_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
 browser=await chromium.launch({executablePath:chrome,headless:true});
 const context=await browser.newContext({viewport:{width:620,height:1300},deviceScaleFactor:4,locale:'en-US',serviceWorkers:'block',reducedMotion:'reduce'});
 const page=await context.newPage();
 const errors=[], blocked=[], calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 const conversation={id:'DEMO_CHAT',title:'Demo project → MEGA'};
 const destination={id:'DEMO_MEGA',name:'Demo on MEGA',kind:'mega',path:'Demo'};
 const names=['Brand','Photos','Videos'];
 const counts=[12,24,6],sizes=[20,100,120].map(n=>n*1048576);
 const plan={id:'DEMO_PLAN',status:'ready',requires_approval:true,approved:false,destination,items:names.map((name,i)=>({name,source_id:`DEMO_FOLDER_${i}`,target:`mega:Demo/${name}`})),steps:['Check size and free space','Copy selected folders','Verify file sizes'],note:'Review the paths before approving.'};
 const queue=names.map((name,i)=>({item_id:`DEMO_QUEUE_${i}`,folder_label:name,source_ref:`DEMO_FOLDER_${i}`}));
 const baseJob={id:'DEMO_TRANSFER',status:'running',stage:'copy',revision:1,message:'Simulated transfer in progress.',current:0,cancel_requested:false,spec:{mode:'download',conversation_id:conversation.id,destination_id:destination.id},stats:{bytes:0,totalBytes:251658240,speed:12582912},items:names.map((name,i)=>({name,count:counts[i],bytes:sizes[i],destination:`mega:Demo/${name}`,status:'pending',stage:'copy'}))};
 let messages=[],jobs=[],prepared=[];
 await context.addInitScript(id=>{
  localStorage.setItem('dta-conversation',id);
  window.__streams=[];
  window.EventSource=class {constructor(){this.listeners={};window.__streams.push(this)}addEventListener(n,fn){this.listeners[n]=fn}close(){this.closed=true}};
  window.__snapshot=job=>{for(const s of window.__streams)if(!s.closed)s.listeners.snapshot?.({data:JSON.stringify(job)})};
 },conversation.id);
 await context.route('**/*',async route=>{
  const url=new URL(route.request().url()),method=route.request().method();
  if(url.origin!=='http://127.0.0.1:4187'){blocked.push(url.origin);return route.abort()}
  if(!url.pathname.startsWith('/api/'))return route.continue();
  const endpoint=url.pathname;calls.push({endpoint,method});let body;
  if(endpoint==='/api/health')body={ok:true,platform:'win32',rclone:{installed:true,version:'rclone v1.75.2'},connections:{google:true,mega:true,model:true}};
  else if(endpoint==='/api/destinations')body=[destination];
  else if(endpoint==='/api/preferences')body={destination_id:destination.id,default_action:'download',export_gdocs:true,create_empty:true,auto_repair:true,reserve_bytes:1073741824};
  else if(endpoint==='/api/conversations')body=url.search?'':method==='POST'?conversation:[conversation];
  else if(endpoint.endsWith('/messages')&&method==='POST'){
   const input=route.request().postDataJSON();
   messages=[{id:'DEMO_USER',role:'user',text:input.text},{id:'DEMO_REPLY',role:'assistant',text:'I selected Brand, Photos and Videos and prepared the queue and transfer plan for Demo on MEGA. The copy is waiting for your approval.',plan}];
   prepared=queue;body=messages[1];
  } else if(endpoint.endsWith('/messages'))body=messages;
  else if(endpoint.endsWith('/queue'))body={items:prepared};
  else if(endpoint==='/api/jobs')body=jobs;
  else if(endpoint.endsWith('/preflight')){
   const check={...structuredClone(baseJob),id:'DEMO_PREFLIGHT',status:'success',stage:'done',spec:{...baseJob.spec,mode:'inspect'},stats:{},message:'42 files · 240 MiB. There is enough space on MEGA.',items:baseJob.items.map(item=>({...item,status:'success',stage:'done',capacity:{status:'sufficient',remote_free_bytes:53687091200}}))};
   jobs=[check];messages.push({id:'DEMO_SPACE',role:'system',status:'success',text:'Space check complete. 240 MiB selected; 50 GiB free on MEGA.',task_id:check.id});body={job_id:check.id};
  } else if(endpoint.endsWith('/execute')){
   plan.approved=true;plan.status='started';prepared=[];jobs=[structuredClone(baseJob)];messages.push({id:'DEMO_RUN',role:'system',status:'running',text:'Plan approved. Starting the copy of all three folders.',task_id:baseJob.id});body={job_id:baseJob.id};
  } else throw new Error('Unexpected API endpoint: '+method+' '+endpoint);
  if(body==='')body=[];
  return route.fulfill({json:body});
 });
 const shots={},shotTexts={};
 // English localization is restricted to this recording page. No product sources change.
 async function localize(){await page.evaluate(()=>{
  const dictionary={
   'MENOS CLIQUES. MAIS TEMPO PARA VOCÊ.':'FEWER CLICKS. MORE TIME FOR YOU.',
   'Seus arquivos,':'Your files,','no lugar certo.':'in the right place.',
   'Cole um link do Google Drive e me diga para onde levar.':'Paste a Google Drive link and tell me where to copy it.',
   'Eu preparo, transfiro e acompanho tudo com você.':'I plan, transfer and track your files with you.',
   'Baixar para o PC':'Download to PC','Arquivos e pastas, organizados.':'Files and folders, organized.',
   'Levar para o MEGA':'Copy to MEGA','Uma cópia na sua nuvem.':'A copy in your cloud.',
   'Preparar meu espaço':'Set up my workspace','Conecte contas e destinos.':'Connect accounts and destinations.',
   'Você acompanha cada etapa. Seus arquivos originais ficam preservados.':'Track every step. Your originals stay in place.',
   'Plano de transferência · ':'Transfer plan · ',' origens':' sources','Destino: ':'Destination: ',
   'Etapas planejadas':'Planned steps','Consultar tamanho e espaço':'Check size and free space',
   'Aprovar plano e iniciar':'Approve plan and start','Iniciar plano':'Start plan',
   'Plano enviado ao executor. Acompanhe o resultado na tarefa.':'Plan sent to the executor. Track the result in the task.',
   'Fila preparada · ':'Prepared queue · ',' itens':' items','Começar a fila':'Start queue',
   'Transferência de arquivos':'File transfer','Consulta de origem':'Source inspection','Verificação de arquivos':'File verification',
   'Verificando arquivos':'Verifying files','Transferindo':'Transferring','Finalizada':'Finished','Concluída':'Completed','Em andamento':'In progress',
   ' arquivos · ':' files · ','Auditoria:':'Verification:','tamanho':'size','compatível':'matched',
   'Espaço: ':'Space: ','suficiente':'sufficient',' · livre':' · free',
   'Relatório':'Report','Abrir MEGA':'Open MEGA','Cancelar':'Cancel',' de ':' of ',
   'Destino':'Destination','Enter para enviar':'Enter to send',
  };
  const walker=document.createTreeWalker(document.getElementById('root'),NodeFilter.SHOW_TEXT);let n;
  while(n=walker.nextNode()){let v=n.nodeValue;for(const [from,to] of Object.entries(dictionary))v=v.split(from).join(to);v=v.replace(/(\d),(\d)/g,'$1.$2');if(v!==n.nodeValue)n.nodeValue=v;}
  document.querySelector('textarea')?.setAttribute('placeholder','Paste a link or tell me what you need…');
  document.documentElement.lang='en';
  document.querySelector('textarea')?.setAttribute('spellcheck','false');
 });}
 async function capture(name,selector,clipHeight){
  await localize();
  const loc=page.locator(selector).last();await loc.waitFor();
  shotTexts[name]=await loc.innerText();
  await loc.scrollIntoViewIfNeeded();
  let data,w,h;
  if(clipHeight){const b=await loc.boundingBox();w=b.width;h=Math.min(clipHeight,b.height);data=await page.screenshot({clip:{x:b.x,y:b.y,width:w,height:h},animations:'disabled'});}
  else {data=await loc.screenshot({animations:'disabled'});const b=await loc.boundingBox();w=b.width;h=b.height}
  await fs.writeFile(path.join(here,'ui',name+'.png'),data);
  shots[name]={image:'data:image/png;base64,'+data.toString('base64'),w,h};
 }
 await page.goto('http://127.0.0.1:4187',{waitUntil:'networkidle'});
 await page.evaluate(()=>document.fonts.ready);
 await capture('welcome','.welcome',275);
 await page.setViewportSize({width:420,height:1300});
 const input=page.getByLabel('Mensagem',{exact:true});
 const request='Select Brand, Photos and Videos from this Drive folder. Plan a copy to /Demo on MEGA. Wait for my approval.\nhttps://drive.google.com/drive/folders/DEMO_FOLDERS';
 // Real controlled React input; snapshots preserve the product's original styling.
 for(let i=0;i<=40;i++){
  await input.fill(request.slice(0,Math.round(request.length*i/40)));
  await capture('type-'+i,'.composer');
 }
 await page.getByRole('button',{name:'Enviar mensagem',exact:true}).click();
 await page.getByRole('region',{name:'Plano de transferência'}).waitFor();
 await capture('request','.message.user');
 await page.setViewportSize({width:620,height:1300});
 await capture('queue','.queue-preview');
 await capture('plan','.transfer-plan');
 await page.locator('.plan-actions button').first().click();
 await page.locator('.job-card').waitFor();
 await capture('space','.job-card');
 await capture('approve','.plan-actions');
 await page.locator('.plan-actions button').last().click();
 await page.getByText('Plan approved. Starting the copy of all three folders.',{exact:true}).waitFor();
 for(let i=0;i<=80;i++){
  const snapshot=structuredClone(baseJob);snapshot.stats.bytes=Math.round(snapshot.stats.totalBytes*i/80);snapshot.revision=i+2;
  snapshot.items.forEach((it,n)=>{it.status=i/80>=(n+1)/3?'success':i/80>=n/3?'running':'pending'});
  await page.evaluate(j=>window.__snapshot(j),snapshot);
  await capture('progress-'+i,'.job-card');
 }
 const checking=structuredClone(baseJob);checking.stage='check';checking.stats={};checking.message='Checking file sizes on MEGA.';checking.items.forEach(i=>{i.status='running';i.stage='check'});
 await page.evaluate(j=>window.__snapshot(j),checking);await capture('check','.job-card');
 const complete=structuredClone(checking);complete.status='success';complete.stage='done';complete.message='42 files copied. Size-based verification complete.';complete.items.forEach(i=>{i.status='success';i.stage='done';i.audit={ok:true,coverage:'size'}});
 await page.evaluate(j=>window.__snapshot(j),complete);await capture('done','.job-card');
 await capture('done-summary','.job-card',110);
 if(errors.length)throw new Error(errors.join('\n'));
 console.log('Captured real UI: typing, request, queue, plan, preflight, approval, progress, audit.');

 const film=await browser.newPage({viewport:{width:1080,height:1350},deviceScaleFactor:1});
 await film.route('**/*',route=>route.request().url().startsWith('file:')?route.continue():route.abort());
 await film.goto(pathToFileURL(path.join(here,'composition.html')).href);
 const scenes=[
  {start:0,end:5,key:'welcome',kicker:'My project in action',title:'I turned file transfers<br>into <em>a conversation.</em>',caption:'Drive Transfer Agent<br>From a chat request to a verified copy.',step:'01 / THE IDEA'},
  {start:5,end:9,key:t=>'type-'+Math.min(40,Math.floor((t-5)*10)),kicker:'01 · A request in chat',title:'Three Drive folders.<br><em>Destination: MEGA.</em>',caption:'Brand · Photos · Videos<br>First, prepare the plan.',step:'02 / THE REQUEST'},
  {start:9,end:15,key:'request',kicker:'01 · A request in chat',title:'Three Drive folders.<br><em>Destination: MEGA.</em>',caption:'I choose the folders<br>and ask to review before copying.',step:'02 / THE REQUEST'},
  {start:15,end:17,key:'queue',kicker:'02 · Folder selection',title:'Only the folders<br><em>I selected.</em>',caption:'The queue contains all three selected folders.',step:'03 / THE PLAN'},
  {start:17,end:20.5,key:'plan',kicker:'02 · Planning',title:'Sources and destinations.<br><em>Ready for my review.</em>',caption:'Each folder keeps its name at the destination.',step:'03 / THE PLAN'},
  {start:20.5,end:23,key:'space',kicker:'02 · Space check',title:'240 MiB to copy.<br><em>50 GiB available.</em>',caption:'Check file sizes and free space<br>before approving the copy.',step:'03 / THE PLAN'},
  {start:23,end:25,key:'approve',kicker:'02 · My approval',title:'Plan reviewed.<br><em>Ready to copy.</em>',caption:'The copy starts with “Approve plan and start”.',step:'03 / THE PLAN'},
  {start:25,end:33,key:t=>'progress-'+Math.min(80,Math.floor((t-25)*80/7.5)),kicker:'03 · Working through the queue',title:'Every folder in the queue.<br><em>Progress in view.</em>',caption:'Copy and track files through chat.<br><strong>Accelerated, simulated progress.</strong>',step:'04 / THE TRANSFER'},
  {start:33,end:36,key:'check',kicker:'03 · MEGA verification',title:'Files copied.<br><em>Time to verify.</em>',caption:'MEGA uses <strong>size-based verification.</strong><br>It does not prove byte-for-byte equality.',step:'04 / VERIFICATION'},
  {start:36,end:39,key:'done',kicker:'04 · The result',title:'Three folders.<br><em>42 files copied.</em>',caption:'File sizes match.<br>Results shown are simulated.',step:'05 / THE RESULT'},
  {start:39,end:45,key:'done',final:true,kicker:'Drive → PC or MEGA',title:'Plan and track<br>transfers<br><em>through chat.</em>',caption:'',step:'WHAT WOULD YOU AUTOMATE?'},
 ];
 async function render(t){
  const scene=scenes.find(s=>t>=s.start&&t<s.end)||scenes.at(-1);
  const shot=shots[typeof scene.key==='function'?scene.key(t):scene.key];
  const closeup=!scene.final&&(['space','check','done'].includes(scene.key)||scene.start===25);
  const maxHeight=scene.final?350:705;
  const width=closeup?950:Math.min(950,maxHeight*shot.w/shot.h);
  let pan=0;
  if(scene.start===25){const p=Math.max(0,Math.min(1,(t-28)/4.8));pan=(.5-Math.cos(Math.PI*p)/2)*.92;}
  if(scene.key==='check'){const p=Math.max(0,Math.min(1,(t-33)/2.8));pan=.22+.45*(.5-Math.cos(Math.PI*p)/2);}
  const crop=closeup?705:null;
  const {key,...layout}=scene;
  const finalShot=scene.final?shots['done-summary']:shot;
  await film.evaluate(args=>window.render(args),{...layout,...finalShot,width:scene.final?850:width,crop,pan,click:scene.start===23,time:t,local:t-scene.start});
 }
 for(const t of [0,2.5,5,7,9,12,15.5,18,21.5,23.7,25,29,32.9,34.5,36.5,39,42,44.9667]){
  await render(t);await film.screenshot({path:path.join(here,'validation',`frame-${String(t).replace('.','_')}.png`)});
 }
 // Poster is the opening card, with its text and simulation label intact.
 await render(2.5);await film.screenshot({path:path.join(here,'capa.png')});
 await fs.writeFile(path.join(here,'validation','capture.json'),JSON.stringify({original_sha256:original,ui_source:'web/src/main.tsx + web/src/style.css (unmodified)',api_calls:calls,blocked_external_origins:[...new Set(blocked)],browser_errors:errors,scene_timing:scenes.map(({start,end,title})=>({start,end,title})),shot_texts:shotTexts,fictional:true},null,2));
 if(!process.argv.includes('--preview')){
  const output=path.join(here,'drive-transfer-agent-linkedin.mp4');
  const encoder=spawn(process.env.FFMPEG||'ffmpeg',['-hide_banner','-y','-f','image2pipe','-framerate','30','-vcodec','mjpeg','-i','pipe:0','-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-r','30','-frames:v','1350','-movflags','+faststart','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',output],{stdio:['pipe','ignore','pipe'],windowsHide:true});
  let stderr='';encoder.stderr.on('data',d=>stderr+=d);encoder.stdin.on('error',()=>{});
  const completion=new Promise((resolve,reject)=>{encoder.on('error',reject);encoder.on('exit',code=>code===0?resolve():reject(new Error(stderr)))});
  for(let frame=0;frame<1350;frame++){
   await render(frame/30);const jpg=await film.screenshot({type:'jpeg',quality:94});
   if(!encoder.stdin.write(jpg))await once(encoder.stdin,'drain');
   if(frame%150===0)console.log(`Rendered ${frame}/1350 frames (${frame/30}s).`);
  }
  encoder.stdin.end();await completion;
  console.log('Exported 1350 frames at 30 fps = exactly 45 seconds.');
 }
 const after=await sha(path.join(root,'docs/demo.mp4'));
 if(after!==original)throw new Error('Original video hash changed!');
 console.log('Original demo.mp4 preserved: '+after);
} finally {await browser?.close();await server.close()}
