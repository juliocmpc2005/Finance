import {readFile} from 'node:fs/promises';
import {renderPaper} from '../dist/templates.js';
const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);const input=Buffer.concat(chunks).toString('utf8');
if(process.argv.includes('--pdf')){
 const {chromium}=await import('playwright');const executable=process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined);
 const browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{})});
 try{const page=await browser.newPage({viewport:{width:1440,height:1200},javaScriptEnabled:false});await page.route('**/*',route=>route.abort());await page.setContent(input,{waitUntil:'load',timeout:10000});await page.evaluate(()=>Promise.all([...document.images].map(image=>image.decode().catch(()=>{}))));const pdf=await page.pdf({format:'A4',preferCSSPageSize:true,printBackground:true});process.stdout.write(pdf);}finally{await browser.close();}
}else{
 const {invoice,company,client,originalNumber='',assets={}}=JSON.parse(input);
 let paper=renderPaper(invoice,{client:()=>client,company:()=>company,originalNumber});
 for(const [path,value] of Object.entries(assets))paper=paper.replaceAll('src="'+path+'"','src="'+value+'"');
 const css=(await readFile(new URL('../dist/styles.css',import.meta.url),'utf8')).replace(/@import\s+url\([^;]*\);/g,'');
 const title=String(invoice.number||'Factura').replace(/[<>&"]/g,'');
 process.stdout.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src 'none';"><title>${title}</title><style>${css}</style></head><body><div id="app"><main class="main"><div class="content"><div class="reviewlayout">${paper}</div></div></main></div></body></html>`);
}
