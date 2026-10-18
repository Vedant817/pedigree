// Independent adversarial callbacks. Execution is simulated, transport may be real.
import assert from 'node:assert/strict';
import {createHash, randomUUID} from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {createCore} from '../../adapters/opencode/pedigree-core.js';

function fixture(t) {
  const project = fs.mkdtempSync(path.join(os.tmpdir(), 'pedigree-round2-'));
  t.after(() => fs.rmSync(project, {recursive:true, force:true}));
  const calls = [];
  const core = createCore({projectRoot:project, config:{enabled:true,
    baseUrl:process.env.ROUND2_URL || 'http://127.0.0.1:8119',
    token:process.env.ROUND2_TOKEN || 'synthetic-review', timeoutMs:5000,
    responseBytes:1048576, problems:[]}, fetchImpl:async(url, init) => {
      calls.push({url, body:JSON.parse(init.body)});
      if (process.env.ROUND2_URL) return fetch(url, init);
      return new Response(JSON.stringify(url.endsWith('/v1/gate')
        ? {decision:'allow'} : {created:['synthetic']}), {status:200});
    }});
  const sessionID = 'round2_' + randomUUID();
  const hook = (tool, callID, args) => ({tool, callID, args, sessionID});
  const before = (tool,args,id='first') => core.beforeHook(hook(tool,id,args),{args});
  const after = (tool,args,output,id='first') => core.afterHook(hook(tool,id,args),output);
  const actions = () => calls.flatMap(c=>c.body.events || []).filter(e=>e.type==='action_executed');
  const latched = async() => assert.rejects(before('bash',{command:'echo next'},'next'),e=>e.code==='incomplete');
  return {core,project,calls,hook,before,after,actions,latched};
}

test('intended content mismatch emits no successful action', async t => {
  const f=fixture(t), filePath=path.join(f.project,'out.txt'), args={filePath,content:'intended canary'};
  await f.before('write',args); fs.writeFileSync(filePath,'different bytes');
  await f.after('write',args,{metadata:{filepath:filePath,exists:false,truncated:false}});
  assert.equal(f.actions().length,0); await f.latched();
});

test('edit attributes full post-state digest without old/new/diff/body leakage', async t => {
  const f=fixture(t), filePath=path.join(f.project,'edit.txt');
  fs.writeFileSync(filePath,'prefix old-canary suffix');
  const args={filePath,oldString:'old-canary',newString:'new-canary'};
  await f.before('edit',args); fs.writeFileSync(filePath,'prefix new-canary suffix');
  assert.deepEqual(await f.after('edit',args,{metadata:{filediff:{file:filePath,
    patch:'private-patch-canary',additions:1,deletions:1},truncated:false}}),{captured:true});
  const digest=createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
  assert.ok(f.actions()[0].artifact_key.endsWith('@'+digest));
  const wire=JSON.stringify(f.calls);
  for(const value of ['old-canary','new-canary','private-patch-canary','prefix',f.project]) assert.ok(!wire.includes(value));
});

test('concurrent edit post-state cannot impersonate the intended replacement', async t => {
  const f=fixture(t), filePath=path.join(f.project,'edit.txt'); fs.writeFileSync(filePath,'one old two');
  const args={filePath,oldString:'old',newString:'new'}; await f.before('edit',args);
  fs.writeFileSync(filePath,'one new two plus concurrent change');
  await f.after('edit',args,{metadata:{filediff:{file:filePath,additions:1,deletions:1},truncated:false}});
  assert.equal(f.actions().length,0); await f.latched();
});

test('new file below nested nonexistent directory in escaping junction is denied before gate', async t => {
  const f=fixture(t), outside=fs.mkdtempSync(path.join(os.tmpdir(),'pedigree-round2-out-'));
  t.after(()=>fs.rmSync(outside,{recursive:true,force:true}));
  fs.symlinkSync(outside,path.join(f.project,'link'),process.platform==='win32'?'junction':'dir');
  const args={filePath:path.join(f.project,'link','not-created','new.txt'),content:'owned'};
  await assert.rejects(f.before('write',args),e=>e.code==='path_outside');
  assert.equal(f.calls.length,0); assert.equal(fs.existsSync(path.join(outside,'not-created')),false);
});

for (const outcome of ['missing','nonzero','string','output-mismatch']) test('bash outcome '+outcome+' never records success', async t => {
  const f=fixture(t), args={command:'echo private-command-canary'}; await f.before('bash',args);
  const metadata={output:'private-output-canary',exit:0,truncated:false};
  if(outcome==='missing') delete metadata.exit;
  if(outcome==='nonzero') metadata.exit=12;
  if(outcome==='string') metadata.exit='0';
  await f.after('bash',args,{output:outcome==='output-mismatch'?'changed':metadata.output,metadata});
  assert.equal(f.actions().length,0); await f.latched();
  assert.ok(!JSON.stringify(f.calls).includes('private-command-canary'));
  assert.ok(!JSON.stringify(f.calls).includes('private-output-canary'));
});

for(const mismatch of ['args','call','tool']) test('callback '+mismatch+' mismatch cannot reuse a gate', async t => {
  const f=fixture(t), args={command:'echo initial'}; await f.before('bash',args);
  await f.after(mismatch==='tool'?'write':'bash',mismatch==='args'?{command:'echo changed'}:args,
    {output:'ok',metadata:{output:'ok',exit:0,truncated:false}},mismatch==='call'?'foreign':'first');
  assert.equal(f.actions().length,0); await f.latched();
});

test('credential paths and case aliases denied without sending content', async t => {
  const f=fixture(t);
  for(const relative of ['.env.production','.AWS/credentials','nested/client.PEM','.git-credentials','.ssh/id_ed25519']) {
    const args={filePath:path.join(f.project,relative),content:'credential-canary'};
    await assert.rejects(f.before('write',args,relative),e=>e.code==='path_credential');
  }
  assert.equal(f.calls.length,0);
});

test('successful bash retains only untrusted output identity and unknown/high action', async t => {
  const f=fixture(t), args={command:'echo private-command-canary'}; await f.before('bash',args);
  assert.deepEqual(await f.after('bash',args,{output:'private-output-canary',metadata:{output:'private-output-canary',exit:0,truncated:false}}),{captured:true});
  const action=f.actions()[0]; assert.equal(action.risk,'high'); assert.equal(action.effect,'unknown');
  const source=f.calls.flatMap(c=>c.body.events||[]).find(e=>e.type==='source_read');
  assert.equal(source.content_hash,createHash('sha256').update('private-output-canary').digest('hex'));
  const wire=JSON.stringify(f.calls);
  assert.ok(!wire.includes(args.command)); assert.ok(!wire.includes('private-output-canary'));
});
