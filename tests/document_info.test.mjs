import test from 'node:test';
import assert from 'node:assert/strict';
import {extractDocumentInfo} from '../web/static/document-info.js';

test('contract title and a separate number line',()=>{
 const text='УЧЕБНЫЙ ОБРАЗЕЦ\nДОГОВОР КУПЛИ-ПРОДАЖИ КВАРТИРЫ\n№ ГЛД-ЕКБ/26-1031\nг. Екатеринбург';
 assert.equal(extractDocumentInfo(text).label,'Договор №ГЛД-ЕКБ/26-1031');
});
test('number on the same line and an additional agreement',()=>{
 assert.equal(extractDocumentInfo('Договор №1433-аб-22 от 31.10.2026').label,'Договор №1433-аб-22');
 assert.equal(extractDocumentInfo('ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ №2').label,'Дополнительное соглашение №2');
});
test('does not use a reference in the body as the document number',()=>{
 assert.deepEqual(extractDocumentInfo('АКТ ПРИЕМА-ПЕРЕДАЧИ\nСтороны исполняют договор №123.'),{type:'Акт',number:null,label:'Акт'});
 assert.equal(extractDocumentInfo('old_generated.docx'),null);
});
