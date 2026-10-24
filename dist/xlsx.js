// Minimal .xlsx writer: styled cells, formulas with their computed value, frozen panes and filters.
// The zip is stored without compression, which every spreadsheet program reads.
const BUILTIN_FORMATS={'General':0,'0':1,'0.00':2,'#,##0':3,'#,##0.00':4,'0%':9,'0.00%':10,'@':49};
const MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main',RELS='http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const xml=v=>String(v??'').replace(/[^\t\n\r\x20-퟿-�\u{10000}-\u{10FFFF}]/gu,'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
export const column=n=>{let s='';for(n++;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
// Excel counts days from 30 December 1899.
export const serialDate=iso=>(Date.UTC(+iso.slice(0,4),+iso.slice(5,7)-1,+iso.slice(8,10))-Date.UTC(1899,11,30))/86400000;
export function sheetName(value){const name=String(value).replace(/[[\]:*?/\\]/g,'-').replace(/^'+|'+$/g,'').slice(0,31).trim();return name||'Hoja';}

function styles(){
 const formats=[],fonts=[],fills=['<fill><patternFill patternType="none"/></fill>','<fill><patternFill patternType="gray125"/></fill>'],borders=['<border><left/><right/><top/><bottom/><diagonal/></border>'],xfs=[],keys=new Map();
 const index=(list,item)=>{const at=list.indexOf(item);return at<0?list.push(item)-1:at;};
 const font=({bold,color='FF000000',size=10})=>index(fonts,`<font>${bold?'<b/>':''}<sz val="${size}"/><color rgb="${color}"/><name val="Arial"/><family val="2"/></font>`);
 font({});xfs.push('<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>');
 function id(style={}){
  const key=JSON.stringify(style);if(keys.has(key))return keys.get(key);
  const code=style.format||'General';let format=BUILTIN_FORMATS[code];if(format===undefined)format=164+index(formats,code);
  const fill=style.fill?index(fills,`<fill><patternFill patternType="solid"><fgColor rgb="${style.fill}"/><bgColor indexed="64"/></patternFill></fill>`):0;
  const side=edge=>style.border?`<${edge} style="${style.border}"><color rgb="FF000000"/></${edge}>`:`<${edge}/>`;
  const border=index(borders,`<border>${side('left')}${side('right')}${side('top')}${side('bottom')}<diagonal/></border>`);
  const align=style.align||style.valign||style.wrap?`<alignment${style.align?` horizontal="${style.align}"`:''}${style.valign?` vertical="${style.valign}"`:''}${style.wrap?' wrapText="1"':''}/>`:'';
  const xf=`<xf numFmtId="${format}" fontId="${font(style.font||{})}" fillId="${fill}" borderId="${border}" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"${align?' applyAlignment="1">'+align+'</xf>':'/>'}`;
  keys.set(key,xfs.length);xfs.push(xf);return xfs.length-1;
 }
 const toXml=()=>`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="${MAIN}">${formats.length?`<numFmts count="${formats.length}">${formats.map((code,i)=>`<numFmt numFmtId="${164+i}" formatCode="${xml(code)}"/>`).join('')}</numFmts>`:''}<fonts count="${fonts.length}">${fonts.join('')}</fonts><fills count="${fills.length}">${fills.join('')}</fills><borders count="${borders.length}">${borders.join('')}</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="${xfs.length}">${xfs.join('')}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`;
 return {id,toXml};
}

// A cell is a string, a number, {date:'YYYY-MM-DD'} or {formula:'SUM(D2:D9)',value}; any of them may carry a style.
function cellXml(cell,ref,style){
 if(cell===null||cell===undefined||cell==='')return style?`<c r="${ref}" s="${style}"/>`:'';
 const s=style?` s="${style}"`:'';
 if(typeof cell==='number')return Number.isFinite(cell)?`<c r="${ref}"${s}><v>${cell}</v></c>`:`<c r="${ref}"${s}/>`;
 if(typeof cell==='string')return `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${xml(cell)}</t></is></c>`;
 if(cell.date)return `<c r="${ref}"${s}><v>${serialDate(cell.date)}</v></c>`;
 if(cell.formula)return `<c r="${ref}"${s}><f>${xml(cell.formula)}</f>${Number.isFinite(cell.value)?`<v>${cell.value}</v>`:''}</c>`;
 return `<c r="${ref}"${s}/>`;
}
const content=cell=>cell!==null&&typeof cell==='object'?cell.value??cell.date??cell.formula:cell;

function sheetXml(sheet,registry,selected){
 const freeze=sheet.freeze||{},x=freeze.columns||0,y=freeze.rows||0,corner=column(x)+(y+1);
 const pane=x||y?`<pane${x?` xSplit="${x}"`:''}${y?` ySplit="${y}"`:''} topLeftCell="${corner}" activePane="${x&&y?'bottomRight':y?'bottomLeft':'topRight'}" state="frozen"/>`:'';
 const rows=sheet.rows.map((row,r)=>{const cells=row.cells.map((cell,c)=>{const style=row.styles?.[c]??row.style;return cellXml(cell,column(c)+(r+1),style?registry.id(style):0);}).join('');return `<row r="${r+1}"${row.height?` ht="${row.height}" customHeight="1"`:''}>${cells}</row>`;}).join('');
 const width=Math.max(1,...sheet.rows.map(row=>row.cells.length)),last=column(width-1)+Math.max(1,sheet.rows.length);
 return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="${MAIN}" xmlns:r="${RELS}"><dimension ref="A1:${last}"/><sheetViews><sheetView workbookViewId="0"${selected?' tabSelected="1"':''}>${pane}</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>${sheet.columns?.length?`<cols>${sheet.columns.map((w,i)=>`<col min="${i+1}" max="${i+1}" width="${w}" customWidth="1"/>`).join('')}</cols>`:''}<sheetData>${rows}</sheetData>${sheet.filter?`<autoFilter ref="${sheet.filter}"/>`:''}<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/><pageSetup paperSize="9" orientation="${sheet.landscape?'landscape':'portrait'}"/></worksheet>`;
}

export function workbook(sheets){
 const registry=styles(),names=new Set();
 for(const sheet of sheets){let name=sheetName(sheet.name),n=2;while(names.has(name.toLowerCase()))name=sheetName(sheet.name).slice(0,28)+' '+n++;names.add(name.toLowerCase());sheet.name=name;}
 const parts=sheets.map((sheet,i)=>[`xl/worksheets/sheet${i+1}.xml`,sheetXml(sheet,registry,i===0)]);
 const quoted=name=>`'${name.replaceAll("'","''")}'`;
 const filters=sheets.map((sheet,i)=>sheet.filter?`<definedName name="_xlnm._FilterDatabase" localSheetId="${i}" hidden="1">${xml(quoted(sheet.name))}!${sheet.filter.replace(/([A-Z]+)(\d+)/g,'$$$1$$$2')}</definedName>`:'').join('');
 const files=[
  ['[Content_Types].xml',`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheets.map((_,i)=>`<Override PartName="/xl/worksheets/sheet${i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')}</Types>`],
  ['_rels/.rels',`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${RELS}/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
  ['xl/workbook.xml',`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="${MAIN}" xmlns:r="${RELS}"><bookViews><workbookView activeTab="0"/></bookViews><sheets>${sheets.map((sheet,i)=>`<sheet name="${xml(sheet.name)}" sheetId="${i+1}" r:id="rId${i+1}"/>`).join('')}</sheets>${filters?`<definedNames>${filters}</definedNames>`:''}<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>`],
  ['xl/_rels/workbook.xml.rels',`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_,i)=>`<Relationship Id="rId${i+1}" Type="${RELS}/worksheet" Target="worksheets/sheet${i+1}.xml"/>`).join('')}<Relationship Id="rId${sheets.length+1}" Type="${RELS}/styles" Target="styles.xml"/></Relationships>`],
  ...parts,
  ['xl/styles.xml',registry.toXml()],
 ];
 return zip(files.map(([name,text])=>[name,new TextEncoder().encode(text)]));
}
export const lineCount=cell=>String(content(cell)??'').split('\n').length;

const CRC=Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++)n=n&1?0xEDB88320^(n>>>1):n>>>1;return n>>>0;});
const crc32=bytes=>{let c=0xFFFFFFFF;for(const b of bytes)c=CRC[(c^b)&255]^(c>>>8);return (c^0xFFFFFFFF)>>>0;};
function zip(files){
 const now=new Date(),time=now.getHours()<<11|now.getMinutes()<<5|now.getSeconds()>>1,day=(now.getFullYear()-1980)<<9|(now.getMonth()+1)<<5|now.getDate();
 const chunks=[],central=[];let offset=0;
 const header=(size,fill)=>{const bytes=new Uint8Array(size);fill(new DataView(bytes.buffer));return bytes;};
 for(const [name,data] of files){
  const path=new TextEncoder().encode(name),crc=crc32(data);
  const fields=(v,at)=>{v.setUint16(at,20,true);v.setUint16(at+2,0x0800,true);v.setUint16(at+4,0,true);v.setUint16(at+6,time,true);v.setUint16(at+8,day,true);v.setUint32(at+10,crc,true);v.setUint32(at+14,data.length,true);v.setUint32(at+18,data.length,true);v.setUint16(at+22,path.length,true);};
  chunks.push(header(30,v=>{v.setUint32(0,0x04034b50,true);fields(v,4);}),path,data);
  central.push(header(46,v=>{v.setUint32(0,0x02014b50,true);v.setUint16(4,20,true);fields(v,6);v.setUint32(42,offset,true);}),path);
  offset+=30+path.length+data.length;
 }
 const size=central.reduce((n,c)=>n+c.length,0);
 const end=header(22,v=>{v.setUint32(0,0x06054b50,true);v.setUint16(8,files.length,true);v.setUint16(10,files.length,true);v.setUint32(12,size,true);v.setUint32(16,offset,true);});
 const all=[...chunks,...central,end],out=new Uint8Array(all.reduce((n,c)=>n+c.length,0));let at=0;for(const c of all){out.set(c,at);at+=c.length;}
 return out;
}
