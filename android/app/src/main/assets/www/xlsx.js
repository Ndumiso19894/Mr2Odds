/* Minimal, offline Open XML workbook writer for Google Sheets/Excel-compatible .xlsx exports. */
(function (PR) {
  'use strict';

  const MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  const encoder = new TextEncoder();
  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  function write16(view, at, value) { view.setUint16(at, value, true); }
  function write32(view, at, value) { view.setUint32(at, value >>> 0, true); }

  /** ZIP method 0 (stored) keeps this writer dependency-free and works in Android WebView offline. */
  function zip(files) {
    const localParts = [], centralParts = [];
    let localOffset = 0, centralSize = 0;
    for (const file of files) {
      const name = encoder.encode(file.name);
      const data = encoder.encode(file.text);
      const crc = crc32(data);
      const local = new Uint8Array(30);
      const lv = new DataView(local.buffer);
      write32(lv, 0, 0x04034b50); write16(lv, 4, 20); write16(lv, 6, 0x0800);
      write16(lv, 8, 0); write16(lv, 10, 0); write16(lv, 12, 33);
      write32(lv, 14, crc); write32(lv, 18, data.length); write32(lv, 22, data.length);
      write16(lv, 26, name.length); write16(lv, 28, 0);
      localParts.push(local, name, data);

      const central = new Uint8Array(46);
      const cv = new DataView(central.buffer);
      write32(cv, 0, 0x02014b50); write16(cv, 4, 20); write16(cv, 6, 20); write16(cv, 8, 0x0800);
      write16(cv, 10, 0); write16(cv, 12, 0); write16(cv, 14, 33);
      write32(cv, 16, crc); write32(cv, 20, data.length); write32(cv, 24, data.length);
      write16(cv, 28, name.length); write16(cv, 30, 0); write16(cv, 32, 0);
      write16(cv, 34, 0); write16(cv, 36, 0); write32(cv, 38, 0); write32(cv, 42, localOffset);
      centralParts.push(central, name);
      localOffset += local.length + name.length + data.length;
      centralSize += central.length + name.length;
    }

    const end = new Uint8Array(22);
    const ev = new DataView(end.buffer);
    write32(ev, 0, 0x06054b50); write16(ev, 4, 0); write16(ev, 6, 0);
    write16(ev, 8, files.length); write16(ev, 10, files.length);
    write32(ev, 12, centralSize); write32(ev, 16, localOffset); write16(ev, 20, 0);

    const total = localOffset + centralSize + end.length;
    const out = new Uint8Array(total);
    let pos = 0;
    for (const part of localParts) { out.set(part, pos); pos += part.length; }
    for (const part of centralParts) { out.set(part, pos); pos += part.length; }
    out.set(end, pos);
    return out;
  }

  function xml(value) {
    return String(value == null ? '' : value)
      .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g, '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
  }

  function columnName(zeroBased) {
    let n = zeroBased + 1, result = '';
    while (n > 0) {
      const rem = (n - 1) % 26;
      result = String.fromCharCode(65 + rem) + result;
      n = Math.floor((n - 1) / 26);
    }
    return result;
  }

  function sheetName(value, index, used) {
    let name = String(value || `Sheet ${index + 1}`).replace(/[\\/*?:\[\]]/g, ' ').trim().slice(0, 31) || `Sheet ${index + 1}`;
    let candidate = name, suffix = 2;
    while (used.has(candidate.toLowerCase())) {
      const tail = ` ${suffix++}`;
      candidate = name.slice(0, Math.max(1, 31 - tail.length)) + tail;
    }
    used.add(candidate.toLowerCase());
    return candidate;
  }

  function rowStyle(sheet, row, index) {
    const titleRows = Array.isArray(sheet.titleRows) ? sheet.titleRows : (sheet.titleRow === false ? [] : [sheet.titleRow == null ? 0 : sheet.titleRow]);
    const headerRows = Array.isArray(sheet.headerRows) ? sheet.headerRows : [];
    const sectionRows = Array.isArray(sheet.sectionRows) ? sheet.sectionRows : [];
    if (titleRows.indexOf(index) >= 0) return 1;
    if (headerRows.indexOf(index) >= 0) return 3;
    if (sectionRows.indexOf(index) >= 0) return 2;
    if (row.length === 1 && typeof row[0] === 'string' && /[A-Z]/.test(row[0]) && row[0] === row[0].toUpperCase()) return 2;
    const first = String(row[0] == null ? '' : row[0]);
    if (/^(?:Expected goals|Model probability \(%\)|Market selection|Recent form|Raw matches used|Head to head|Trends|Corners|Cards \(bookings\)|Match statistics|Sportybet prices)$/.test(first)) return 2;
    return 0;
  }

  function cellXml(value, ref, style) {
    if (value == null || value === '') return '';
    const styleAttr = style ? ` s="${style}"` : '';
    if (typeof value === 'number' && Number.isFinite(value)) return `<c r="${ref}"${styleAttr}><v>${String(value)}</v></c>`;
    if (typeof value === 'boolean') return `<c r="${ref}"${styleAttr} t="b"><v>${value ? 1 : 0}</v></c>`;
    return `<c r="${ref}"${styleAttr} t="inlineStr"><is><t xml:space="preserve">${xml(value)}</t></is></c>`;
  }

  function worksheet(sheet) {
    const rows = (sheet.rows || []).map((row) => Array.isArray(row) ? row : [row]);
    const maxColumns = Math.max(1, ...rows.map((row) => row.length));
    const maxRows = Math.max(rows.length, 1);
    const lastCell = `${columnName(maxColumns - 1)}${maxRows}`;
    const widths = Array.from({ length: maxColumns }, (_, col) => {
      let width = 10;
      for (const row of rows) {
        const value = row[col];
        if (value != null) width = Math.max(width, String(value).length + 2);
      }
      return Math.min(56, width);
    });
    const cols = widths.map((width, i) => `<col min="${i + 1}" max="${i + 1}" width="${width}" customWidth="1"/>`).join('');
    const data = rows.map((row, rowIndex) => {
      const style = rowStyle(sheet, row, rowIndex);
      const cells = row.map((value, colIndex) => cellXml(value, `${columnName(colIndex)}${rowIndex + 1}`, style)).join('');
      return `<row r="${rowIndex + 1}">${cells}</row>`;
    }).join('');
    const freezeRows = Math.max(0, Math.min(rows.length, Number(sheet.freezeRows) || 0));
    const view = freezeRows
      ? `<sheetViews><sheetView workbookViewId="0"><pane ySplit="${freezeRows}" topLeftCell="A${freezeRows + 1}" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="A${freezeRows + 1}" sqref="A${freezeRows + 1}"/></sheetView></sheetViews>`
      : '<sheetViews><sheetView workbookViewId="0"/></sheetViews>';
    const headerRow = Number.isInteger(sheet.filterHeaderRow) ? sheet.filterHeaderRow : 0;
    const filter = sheet.autoFilter && rows.length > headerRow
      ? `<autoFilter ref="A${headerRow + 1}:${columnName(maxColumns - 1)}${maxRows}"/>` : '';
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:${lastCell}"/>${view}<sheetFormatPr defaultRowHeight="18"/><cols>${cols}</cols><sheetData>${data}</sheetData>${filter}<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/></worksheet>`;
  }

  const styles = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">` +
    `<fonts count="3"><font><sz val="11"/><name val="Aptos"/><family val="2"/></font>` +
    `<font><b/><sz val="14"/><color rgb="FFFFFFFF"/><name val="Aptos Display"/><family val="2"/></font>` +
    `<font><b/><sz val="11"/><color rgb="FF173B43"/><name val="Aptos"/><family val="2"/></font></fonts>` +
    `<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>` +
    `<fill><patternFill patternType="solid"><fgColor rgb="FF12343B"/><bgColor indexed="64"/></patternFill></fill>` +
    `<fill><patternFill patternType="solid"><fgColor rgb="FFE2F3F0"/><bgColor indexed="64"/></patternFill></fill></fills>` +
    `<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>` +
    `<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>` +
    `<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>` +
    `<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>` +
    `<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>` +
    `<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs>` +
    `<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`;

  function create(sheets) {
    if (!Array.isArray(sheets) || !sheets.length || sheets.length > 255) throw new Error('An XLSX workbook needs between 1 and 255 worksheets.');
    const used = new Set();
    const normalized = sheets.map((sheet, index) => ({
      name: sheetName(sheet && sheet.name, index, used),
      rows: sheet && Array.isArray(sheet.rows) ? sheet.rows : [],
      titleRow: sheet && sheet.titleRow,
      titleRows: sheet && sheet.titleRows,
      headerRows: sheet && sheet.headerRows,
      sectionRows: sheet && sheet.sectionRows,
      freezeRows: sheet && sheet.freezeRows,
      autoFilter: sheet && sheet.autoFilter,
      filterHeaderRow: sheet && sheet.filterHeaderRow,
    }));
    const sheetOverrides = normalized.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('');
    const workbookSheets = normalized.map((sheet, i) => `<sheet name="${xml(sheet.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('');
    const worksheetRels = normalized.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('');
    const stylesId = normalized.length + 1;
    const files = [
      { name: '[Content_Types].xml', text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheetOverrides}</Types>` },
      { name: '_rels/.rels', text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>` },
      { name: 'xl/workbook.xml', text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView activeTab="0"/></bookViews><sheets>${workbookSheets}</sheets></workbook>` },
      { name: 'xl/_rels/workbook.xml.rels', text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${worksheetRels}<Relationship Id="rId${stylesId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>` },
      { name: 'xl/styles.xml', text: styles },
      ...normalized.map((sheet, i) => ({ name: `xl/worksheets/sheet${i + 1}.xml`, text: worksheet(sheet) })),
    ];
    return zip(files);
  }

  PR.xlsx = { MIME, create };
})(window.PR);
