import test from 'node:test';
import assert from 'node:assert/strict';
import {pageAtOffset,centeredScrollTop} from '../web/static/document-viewer.js';

test('page counter follows viewport centre across unequal page sizes',()=>{
 const pages=[{top:300,bottom:1300},{top:1316,bottom:1816},{top:1832,bottom:3832}];
 for(const [offset,page] of [[0,0],[700,0],[1304,0],[1312,1],[1600,1],[1828,2],[3000,2],[4500,2]])assert.equal(pageAtOffset(pages,offset),page);
});

test('end padding permits exact centring of changes at document boundaries',()=>{
 const viewport=600,padding=viewport/2,pageHeight=1000,total=2*padding+pageHeight;
 for(const y of [0,20,500,980,1000]){
  const point=padding+y,scroll=centeredScrollTop(point,viewport,total);
  assert.equal(point-scroll,viewport/2);
 }
});

test('scroll requests are clamped to the available strip',()=>{
 assert.equal(centeredScrollTop(-100,600,2000),0);
 assert.equal(centeredScrollTop(5000,600,2000),1400);
 assert.equal(centeredScrollTop(100,600,200),0);
});
