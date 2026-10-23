// Guía de uso video «De cliente nuevo a factura enviada»: issuer, client, invoice, PDF and e-mail.
// Usage: PATH="$PWD/.venv/bin:$PATH" node scripts/guide-video.mjs   (needs ffmpeg; machinery in video-kit.mjs)
import {recordGuideVideo,demoState} from './video-kit.mjs';

await recordGuideVideo({name:'video-primera-factura',
 title:'Cómo crear un cliente y emitir una factura',subtitle:'Del emisor y el cliente a la factura enviada por correo',
 endTitle:'¡Ya sabes facturar!',endSubtitle:'Tienes más ayuda en el botón ? de la parte superior',
 async setup({post,smtpPort}){
  await post('/api/state',{revision:0,state:demoState()});
  await post('/api/mail/config',{host:'127.0.0.1',port:smtpPort,security:'none',fromAddress:'facturas@arquitecturadeguardia.example',fromName:'arquitecturadeguardia'});
  // A second issuer (a self-employed architect): the video starts there and shows choosing arquitecturadeguardia.
  const autonomo=(await post('/api/emitters',{kind:'professional',name:'Pepe Sánchez Ruiz',nif:'12345678Z',address:'Calle Mayor 4, 29001 Málaga'})).emitter;
  return {start:`/?emitter=${autonomo.id}`};
 },
 async steps({page,wait,say,point,click,type,select,restore}){
  // 1. Issuer: each company or self-employed person has its own clients, invoices and numbering.
  await say('Primero, elige arriba a la izquierda con qué empresa o autónomo vas a facturar.',1700);
  await select(page.locator('#emitter-switch'),'adg-original',0);
  await page.waitForURL(url=>url.searchParams.get('emitter')==='adg-original');await page.getByRole('heading',{name:'Tus facturas'}).waitFor();await restore();await wait(900);
  await say('Cada empresa o autónomo tiene sus propios clientes, facturas y numeración.',300);await point(page.locator('#emitter-switch'),2300);
  // 2. New client.
  await say('Ahora el cliente. En el menú, entra en «Clientes».',1200);
  await click(page.locator('[data-nav="clients"]:visible').first());await page.getByRole('heading',{name:'Tus clientes'}).waitFor();
  await say('Pulsa «Nuevo cliente».',600);await click(page.getByRole('button',{name:'Nuevo cliente'}).first());
  await say('Escribe el nombre o razón social, el NIF y la dirección fiscal: son obligatorios para facturar.',400);
  await type(page.getByLabel('Nombre o razón social'),'Casa Lumen, S.L.');await type(page.getByLabel('NIF / Identificación fiscal'),'B29123456');
  await type(page.getByLabel('Dirección fiscal'),'Calle Larios 12, 29005 Málaga');
  await say('Añade también su correo: será el destinatario cuando le envíes la factura.',400);await type(page.getByLabel('Correo electrónico'),'administracion@casalumen.example');
  await say('Pulsa «Guardar cliente». Ya lo tienes para todas sus facturas.',500);await click(page.getByRole('button',{name:'Guardar cliente'}),1600);
  // 3. Invoice.
  await say('Ahora la factura. Ve a «Facturas» y pulsa «Nueva factura».',600);
  await click(page.locator('[data-nav="invoices"]:visible').first());await click(page.getByRole('button',{name:'Nueva factura'}).first(),1000);
  await say('«Emitiendo como» confirma el emisor de la factura. Puedes cambiarlo antes de emitir.',300);await point(page.locator('#invoice-emitter'),2900);
  await say('En «¿A quién facturamos?», elige el cliente.',500);
  await select(page.locator('#client'),await page.locator('#client option',{hasText:'Casa Lumen'}).getAttribute('value'),1300);
  await say('Escribe el concepto y su precio sin IVA. El total se calcula solo, a la derecha.',400);
  await type(page.getByLabel('Concepto 1',{exact:true}),'Proyecto básico de reforma de local comercial');await type(page.getByLabel('Precio 1',{exact:true}),'2400');
  await point(page.locator('#summary-values'),1800);
  await say('Mientras escribes, el borrador se guarda solo. Cuando esté listo, pulsa «Revisar factura».',800);
  await click(page.getByRole('button',{name:/^Revisar factura/}).first(),1200);
  await say('Así quedará el documento. Comprueba el cliente, el concepto y los importes.',3200);
  await say('Si todo está bien, pulsa «Emitir factura». Recibe su número y ya no se puede modificar.',600);
  await click(page.getByRole('button',{name:/^Emitir factura/}),400);await page.getByRole('link',{name:'Descargar PDF'}).waitFor();await wait(1600);
  // 4. PDF and e-mail.
  await say('Desde aquí puedes descargar el PDF cuando lo necesites.',300);await point(page.getByRole('link',{name:'Descargar PDF'}),2000);
  await say('Para mandársela al cliente, pulsa «Enviar por correo».',500);await click(page.getByRole('button',{name:'Enviar por correo'}),900);
  await say('Su correo ya viene puesto. Revisa el asunto y el mensaje, y pulsa «Enviar».',400);
  await point(page.getByLabel('Para',{exact:true}),1300);await point(page.getByLabel('Mensaje',{exact:true}),1500);
  await click(page.getByRole('button',{name:'Enviar',exact:true}),300);await page.locator('#mail-history',{hasText:'administracion@casalumen.example'}).waitFor();
  await point(page.locator('#mail-history'),400);await say('Listo: la factura está emitida y enviada, y queda registrado el envío.',3200);
 }});
