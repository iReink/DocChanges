import test from 'node:test';
import assert from 'node:assert/strict';
import {normalURL} from '../web/static/api-address.js';

test('proxy follows HTTPS tunnel and LAN page origin without port 8000',()=>{
 assert.equal(normalURL('/comparison-api','https://example.tuna.free'),'https://example.tuna.free/comparison-api');
 assert.equal(normalURL('/comparison-api','http://192.168.0.109:8080'),'http://192.168.0.109:8080/comparison-api');
 assert.equal(normalURL('/comparison-api','http://localhost:8080'),'http://localhost:8080/comparison-api');
});
test('manual direct API and HTTPS endpoints preserve ports and paths',()=>{
 assert.equal(normalURL('192.168.0.109','http://localhost:8080'),'http://192.168.0.109:8000');
 assert.equal(normalURL('http://localhost:8000/','http://localhost:8080'),'http://localhost:8000');
 assert.equal(normalURL('https://api.example.com','http://localhost:8080'),'https://api.example.com');
 assert.equal(normalURL('https://example.com/comparison-api/','http://localhost:8080'),'https://example.com/comparison-api');
 assert.throws(()=>normalURL('http://user:password@example.com','http://localhost:8080'));
 assert.throws(()=>normalURL('ftp://example.com','http://localhost:8080'));
});
