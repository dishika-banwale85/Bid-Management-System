import assert from 'node:assert/strict';
import {readFile,writeFile,rm} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {dirname,join} from 'node:path';
import test from 'node:test';
import ts from 'typescript';

const currentDir=dirname(fileURLToPath(import.meta.url));
const source=await readFile(join(currentDir,'../src/schemas/bidSchema.ts'),'utf8');
const runtimeFile=join(currentDir,'.bidSchema.runtime.mjs');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
await writeFile(runtimeFile,compiled);
const {bidCreateSchema}=await import(`${pathToFileURL(runtimeFile).href}?t=${Date.now()}`);
await rm(runtimeFile,{force:true});

function validBid(overrides={}){
 const today=new Date();today.setHours(0,0,0,0);
 const date=(offset)=>{const d=new Date(today);d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
 return {client_name:'Example Client',department:'',client_address:'1 Main Street',rfp_number:'RFP-1',project_title:'Bridge renewal',rfp_published_date:date(-5),prebid_query_deadline:date(2),prebid_query_na:false,prebid_meeting_date:date(3),prebid_meeting_na:false,submission_deadline:date(10),tender_opening_date:date(10),...overrides};
}

test('accepts valid bid data and keeps same-day submission and opening',()=>{
 const parsed=bidCreateSchema.safeParse(validBid());
 assert.equal(parsed.success,true);
});

test('rejects blank required strings and trims values',()=>{
 assert.equal(bidCreateSchema.safeParse(validBid({project_title:'   '})).success,false);
 const parsed=bidCreateSchema.safeParse(validBid({client_name:' Client '}));
 assert.equal(parsed.success,true);
 assert.equal(parsed.data.client_name,'Client');
});

test('rejects invalid chronology and past submission dates',()=>{
 assert.equal(bidCreateSchema.safeParse(validBid({rfp_published_date:'2027-04-01',submission_deadline:'2027-03-01'})).success,false);
 assert.equal(bidCreateSchema.safeParse(validBid({submission_deadline:'2027-03-02',tender_opening_date:'2027-03-01'})).success,false);
 assert.equal(bidCreateSchema.safeParse(validBid({prebid_meeting_date:'2027-03-11',submission_deadline:'2027-03-10'})).success,false);
 assert.equal(bidCreateSchema.safeParse(validBid({submission_deadline:'2000-01-01',tender_opening_date:'2000-01-02'})).success,false);
});

test('Not applicable clears the matching pre-bid date',()=>{
 const parsed=bidCreateSchema.safeParse(validBid({prebid_meeting_na:true,prebid_meeting_date:'',prebid_query_na:true,prebid_query_deadline:''}));
 assert.equal(parsed.success,true);
 assert.equal(parsed.data.prebid_meeting_date,null);
 assert.equal(parsed.data.prebid_query_deadline,null);
});
