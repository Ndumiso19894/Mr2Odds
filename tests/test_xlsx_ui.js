// Validate the offline Open XML workbook writer and stored-ZIP package layout.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{PR:{}}, TextEncoder, TextDecoder, Uint8Array, Uint32Array, DataView};
vm.createContext(context);
vm.runInContext(fs.readFileSync('android/app/src/main/assets/www/xlsx.js', 'utf8'), context);
const xlsx = context.window.PR.xlsx;

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function zipEntry(bytes, expectedName) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const decoder = new TextDecoder();
  for (let at = 0; at + 30 <= bytes.length;) {
    const signature = view.getUint32(at, true);
    if (signature === 0x02014b50) break;
    assert.equal(signature, 0x04034b50, `unexpected ZIP record at ${at}`);
    const method = view.getUint16(at + 8, true);
    const expectedCrc = view.getUint32(at + 14, true);
    const size = view.getUint32(at + 18, true);
    const nameLength = view.getUint16(at + 26, true);
    const extraLength = view.getUint16(at + 28, true);
    const nameAt = at + 30;
    const dataAt = nameAt + nameLength + extraLength;
    const name = decoder.decode(bytes.subarray(nameAt, nameAt + nameLength));
    const data = bytes.subarray(dataAt, dataAt + size);
    assert.equal(method, 0, 'files use ZIP store mode');
    assert.equal(size, data.length);
    assert.equal(crc32(data), expectedCrc, `CRC for ${name}`);
    if (name === expectedName) return decoder.decode(data);
    at = dataAt + size;
  }
  throw new Error(`missing ZIP entry ${expectedName}`);
}

const bytes = xlsx.create([
  {name:'Daily/Analysis', rows:[['Match', 'Model %'], ['Å & O\'Connor', 72.5], ['=1+1', -0.25]], titleRow:false, headerRows:[0], freezeRows:1, autoFilter:true},
  {name:'Daily/Analysis', rows:[['Summary'], ['Fixtures', 12]]},
]);
assert.ok(bytes instanceof Uint8Array);
assert.deepEqual(Array.from(bytes.slice(0, 4)), [0x50, 0x4b, 0x03, 0x04]);
assert.equal(xlsx.MIME, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
const types = zipEntry(bytes, '[Content_Types].xml');
const workbook = zipEntry(bytes, 'xl/workbook.xml');
const sheet1 = zipEntry(bytes, 'xl/worksheets/sheet1.xml');
const sheet2 = zipEntry(bytes, 'xl/worksheets/sheet2.xml');
assert.match(types, /spreadsheetml\.sheet\.main\+xml/);
assert.match(workbook, /name="Daily Analysis"/);
assert.match(workbook, /name="Daily Analysis 2"/);
assert.match(sheet1, /<pane ySplit="1" topLeftCell="A2"/);
assert.match(sheet1, /<autoFilter ref="A1:B3"\/>/);
assert.match(sheet1, /<c r="B2"><v>72\.5<\/v><\/c>/);
assert.match(sheet1, /Å &amp; O&apos;Connor/);
assert.match(sheet1, /<c r="A3" t="inlineStr"><is><t xml:space="preserve">=1\+1<\/t><\/is><\/c>/);
assert.doesNotMatch(sheet1, /<f>/, 'text beginning with equals is not exported as a formula');
assert.match(sheet2, /Fixtures/);
assert.throws(() => xlsx.create([]), /between 1 and 255/);

// Android's native save bridge receives a small file as one Base64 call and large files in
// independently decodable chunks, avoiding a giant JavaScript-interface argument.
let directSave=null, chunkSave=null;
const native={
  saveBase64:(name,mime,b64)=>{directSave={name,mime,b64};},
  saveBase64Start:(name,mime,count,size)=>{chunkSave={name,mime,count,size,chunks:[],finished:false};},
  saveBase64Chunk:(index,b64)=>{chunkSave.chunks[index]=Buffer.from(b64,'base64');},
  saveBase64Finish:()=>{chunkSave.finished=true;},
};
const exportContext={window:{PR:{state:{},toast(){},selLabel(){},tzNow(){return new Date();},ymd(){return '2026-11-10';},native}},
  TextEncoder,Uint8Array,Uint32Array,DataView,Blob,btoa,URL,document:{createElement(){throw new Error('native save expected');},body:{appendChild(){}}},setTimeout,console};
vm.createContext(exportContext);
vm.runInContext(fs.readFileSync('android/app/src/main/assets/www/export.js','utf8'),exportContext);
const savePR=exportContext.window.PR;
const small=Uint8Array.from([0,1,2,3,255]);
savePR.saveBinaryFile('small.xlsx',small,xlsx.MIME);
assert.equal(directSave.name,'small.xlsx');
assert.equal(directSave.mime,xlsx.MIME);
assert.deepEqual(Buffer.from(directSave.b64,'base64'),Buffer.from(small));
const large=Uint8Array.from({length:700000},(_,i)=>i%251);
savePR.saveBinaryFile('large.xlsx',large,xlsx.MIME);
assert.equal(chunkSave.name,'large.xlsx');
assert.equal(chunkSave.size,large.length);
assert.ok(chunkSave.finished && chunkSave.chunks.length === chunkSave.count);
assert.deepEqual(Buffer.concat(chunkSave.chunks),Buffer.from(large));
console.log('XLSX workbook writer and native save tests passed');
