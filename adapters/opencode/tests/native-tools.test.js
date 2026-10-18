/** Observed OpenCode 1.19.3 tool shapes; simulated execution is named explicitly. */
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { defaultServer, expectThrow, makeCore, removeProject } from "./helpers.js";
import { createCore, loadConfig } from "../pedigree-core.js";

const SID = "ses_native";
const sha = (value) => crypto.createHash("sha256").update(value).digest("hex");
const input = (tool, callID, args) => ({tool, sessionID:SID, callID, args});

test("observed write/edit hooks persist only verified artifact hashes and action metadata", async(t) => {
 const {core,project,calls}=makeCore(); t.after(()=>removeProject(project));
 const filePath=path.join(project,"created.txt");
 const write={filePath,content:"private owned fixture body"};
 assert.deepEqual(await core.beforeHook(input("write","w",write),{args:write}),{decision:"allow"});
 fs.writeFileSync(filePath,write.content); // simulated runtime, never installed proof
 assert.deepEqual(await core.afterHook(input("write","w",write),{
   title:filePath,output:"write complete",metadata:{diagnostics:{},filepath:filePath,exists:false,truncated:false}}),{captured:true});
 const edit={filePath,oldString:"fixture",newString:"changed"};
 await core.beforeHook(input("edit","e",edit),{args:edit});
 fs.writeFileSync(filePath,write.content.replace("fixture","changed"));
 assert.deepEqual(await core.afterHook(input("edit","e",edit),{
   title:filePath,output:"edit complete",metadata:{diagnostics:{},diff:"private diff",filediff:{file:filePath,patch:"private diff",additions:1,deletions:1},truncated:false}}),{captured:true});
 const actions=calls.flatMap(c=>c.body?.events||[]).filter(e=>e.type==="action_executed");
 assert.equal(actions.length,2);
 assert.equal(actions[0].tool,"write"); assert.equal(actions[1].tool,"edit");
 assert.match(actions[1].artifact_key,new RegExp(sha(fs.readFileSync(filePath))+"$"));
 const wire=JSON.stringify(calls.map(c=>c.body));
 for(const privateValue of [write.content,edit.oldString,edit.newString,"private diff",project]) assert.ok(!wire.includes(privateValue));
});

test("Bash is conservatively gated and captures only successful bounded output digests",async(t)=>{
 const {core,project,calls}=makeCore();t.after(()=>removeProject(project));
 const args={command:"echo private-command-token"};
 await core.beforeHook(input("bash","b",args),{args});
 const gate=calls.find(c=>c.url.endsWith("/v1/gate"));
 assert.equal(gate.body.action.risk,"high");assert.equal(gate.body.action.effect,"unknown");
 assert.ok(!JSON.stringify(gate.body).includes(args.command));
 assert.deepEqual(await core.afterHook(input("bash","b",args),{title:"private title",output:"private output",metadata:{output:"private output",exit:0,truncated:false}}),{captured:true});
 const events=calls.at(-1).body.events;
 assert.match(events.find(e=>e.type==="action_executed").summary,/exit=0/);
 assert.equal(events.find(e=>e.type==="source_read").content_hash,sha("private output"));
 assert.ok(!JSON.stringify(calls).includes("private output"));
});

test("failed Bash is never recorded as a successful action and latches the session",async(t)=>{
 const {core,project,calls}=makeCore();t.after(()=>removeProject(project));
 const args={command:"exit 7"};await core.beforeHook(input("bash","b",args),{args});
 await core.afterHook(input("bash","b",args),{output:"",metadata:{output:"",exit:7,truncated:false}});
 assert.equal(calls.flatMap(c=>c.body?.events||[]).filter(e=>e.type==="action_executed").length,0);
 await expectThrow(core.beforeHook(input("bash","next",args),{args}),"incomplete");
});

test("a mutation missing its after hook denies later operations instead of hiding a capture gap",async(t)=>{
 const {core,project}=makeCore();t.after(()=>removeProject(project));
 const args={filePath:path.join(project,"created.txt"),content:"owned"};
 await core.beforeHook(input("write","w",args),{args});
 await expectThrow(core.beforeHook(input("bash","later",{command:"echo x"}),{args:{command:"echo x"}}),"incomplete");
});

test("changed write arguments, mismatched path and unknown outcomes latch rather than claiming capture",async(t)=>{
 for(const kind of ["args","path","disk"]){
 const {core,project}=makeCore();t.after(()=>removeProject(project));
 const filePath=path.join(project,"created.txt"),args={filePath,content:"expected"};
 await core.beforeHook(input("write","w",args),{args});
 fs.writeFileSync(filePath,kind==="disk"?"different":args.content);
 await core.afterHook(input("write","w",kind==="args"?{...args,content:"changed"}:args),{metadata:{filepath:kind==="path"?path.join(project,"other.txt"):filePath,exists:false,truncated:false}});
 await expectThrow(core.beforeHook(input("write","later",args),{args}),"incomplete");
 }
});

test("capture delivery failure latches native writes and prevents further tools",async(t)=>{
 const {core,project}=makeCore({handler:(r)=>r.body?.events?.some(e=>e.type==="action_executed")?{status:503,data:{}}:defaultServer(r)});
 t.after(()=>removeProject(project));
 const filePath=path.join(project,"created.txt"),args={filePath,content:"owned"};
 await core.beforeHook(input("write","w",args),{args});fs.writeFileSync(filePath,args.content);
 assert.deepEqual(await core.afterHook(input("write","w",args),{metadata:{filepath:filePath,exists:false,truncated:false}}),{captured:false});
 await expectThrow(core.beforeHook(input("bash","later",{command:"echo x"}),{args:{command:"echo x"}}),"incomplete");
});

test("native writes cannot create files through an existing escaping symlink parent",async(t)=>{
 const {core,project}=makeCore();t.after(()=>removeProject(project));
 const outside=fs.mkdtempSync(path.join(path.dirname(project),"pedigree-outside-"));t.after(()=>removeProject(outside));
 fs.symlinkSync(outside,path.join(project,"escape"),process.platform==="win32"?"junction":"dir");
 const args={filePath:path.join(project,"escape","new.txt"),content:"owned"};
 await expectThrow(core.beforeHook(input("write","w",args),{args}),"path_outside");
 assert.ok(!fs.existsSync(path.join(outside,"new.txt")));
});

test("credential writes and blocked Bash never reach the execution point",async(t)=>{
 const {core,project,calls}=makeCore();t.after(()=>removeProject(project));
 const args={filePath:path.join(project,".env"),content:"owned"};
 await expectThrow(core.beforeHook(input("write","w",args),{args}),"path_credential");
 assert.equal(calls.length,0);
 const denied=makeCore({handler:r=>r.url.endsWith("/v1/gate")?{data:{decision:"reverify"}}:defaultServer(r)});t.after(()=>removeProject(denied.project));
 let ran=false;
 await expectThrow((async()=>{await denied.core.beforeHook(input("bash","b",{command:"echo owned"}),{args:{command:"echo owned"}});ran=true;})(),"gate_reverify");
 assert.equal(ran,false);
});

test("missing/noninteger exit, truncated output and mismatched hooks never report success", async(t) => {
  for (const failure of ["missing", "string", "truncated", "output", "tool", "call", "args"]) {
    const {core, project, calls} = makeCore();
    t.after(() => removeProject(project));
    const args = {command: "printf owned"};
    await core.beforeHook(input("bash", "b", args), {args});
    const hook = input(failure === "tool" ? "write" : "bash", failure === "call" ? "other" : "b",
      failure === "args" ? {command: "printf changed"} : args);
    const metadata = {exit: 0, output: "owned", truncated: false};
    if (failure === "missing") delete metadata.exit;
    if (failure === "string") metadata.exit = "0";
    if (failure === "truncated") metadata.truncated = true;
    await core.afterHook(hook, {output: failure === "output" ? "changed" : "owned", metadata});
    assert.equal(calls.flatMap(c => c.body?.events || []).filter(e => e.type === "action_executed").length, 0);
    await expectThrow(core.beforeHook(input("bash", "next", args), {args}), "incomplete");
  }
});

test("edit requires one exact occurrence and verifies the complete expected result", async(t) => {
  for (const original of ["missing", "twice twice", "unique"]) {
    const {core, project, calls} = makeCore();
    t.after(() => removeProject(project));
    const filePath = path.join(project, "edit.txt");
    fs.writeFileSync(filePath, original);
    const args = {filePath, oldString: original === "twice twice" ? "twice" : "unique", newString: "result"};
    if (original !== "unique") {
      await expectThrow(core.beforeHook(input("edit", "e", args), {args}), "malformed");
      assert.equal(calls.length, 0);
    } else {
      await core.beforeHook(input("edit", "e", args), {args});
      fs.writeFileSync(filePath, "result with concurrent change");
      await core.afterHook(input("edit", "e", args), {metadata: {
        filediff: {file: filePath, additions: 1, deletions: 1}, truncated: false}});
      await expectThrow(core.beforeHook(input("edit", "next", args), {args}), "incomplete");
    }
  }
});

test("replaced symlink parent is rejected even when metadata reports the former canonical target", async(t) => {
  const {core, project, calls} = makeCore();
  t.after(() => removeProject(project));
  const safe = path.join(project, "safe");
  const outside = fs.mkdtempSync(path.join(path.dirname(project), "pedigree-race-"));
  t.after(() => removeProject(outside));
  fs.mkdirSync(safe);
  const alias = path.join(project, "alias");
  fs.symlinkSync(safe, alias, process.platform === "win32" ? "junction" : "dir");
  const args = {filePath: path.join(alias, "new.txt"), content: "owned"};
  await core.beforeHook(input("write", "w", args), {args});
  fs.writeFileSync(path.join(safe, "new.txt"), args.content);
  fs.unlinkSync(alias);
  fs.symlinkSync(outside, alias, process.platform === "win32" ? "junction" : "dir");
  await core.afterHook(input("write", "w", args), {metadata: {
    filepath: path.join(safe, "new.txt"), exists: false, truncated: false}});
  assert.equal(calls.flatMap(c => c.body?.events || []).filter(e => e.type === "action_executed").length, 0);
  await expectThrow(core.beforeHook(input("bash", "next", {command: "printf owned"}), {args: {command: "printf owned"}}), "incomplete");
});

test("native artifact bounds are checked before execution and oversized content is denied", async(t) => {
  const {core, project, calls} = makeCore();
  t.after(() => removeProject(project));
  for (const args of [
    {filePath: path.join(project, ...Array(8).fill("nested".repeat(10)), "file.txt"), content: "owned"},
    {filePath: path.join(project, "file.txt"), content: "x".repeat(4 * 1024 * 1024 + 1)},
  ]) {
    await expectThrow(core.beforeHook(input("write", "w", args), {args}), "malformed");
  }
  assert.equal(calls.length, 0);
});

test("duplicate native callbacks never create two actions", async(t) => {
  const {core, project, calls} = makeCore();
  t.after(() => removeProject(project));
  const filePath = path.join(project, "file.txt");
  const args = {filePath, content: "owned"};
  const hook = input("write", "w", args);
  await core.beforeHook(hook, {args});
  fs.writeFileSync(filePath, args.content);
  const output = {metadata: {filepath: filePath, exists: false, truncated: false}};
  await core.afterHook(hook, output);
  await core.afterHook(hook, output);
  assert.equal(calls.flatMap(c => c.body?.events || []).filter(e => e.type === "action_executed").length, 1);
  await expectThrow(core.beforeHook(hook, {args}), "duplicate_call");
});

test("Win32 normalized credential aliases and device names cannot become native writes", {
  skip: process.platform !== "win32",
}, async(t) => {
  const {core, project, calls} = makeCore();
  t.after(() => removeProject(project));
  for (const file of [".netrc.", ".npmrc ", ".aws./new.txt", "NUL", "con.txt", "COM1.log"]) {
    const args = {filePath: path.join(project, file), content: "owned"};
    await expectThrow(core.beforeHook(input("write", "w", args), {args}), "path_stream");
  }
  assert.equal(calls.length, 0);
});

test("native relative paths resolve against the runtime directory inside the worktree", async(t) => {
  const fixture = makeCore();
  t.after(() => removeProject(fixture.project));
  const directory = path.join(fixture.project, "subdir");
  fs.mkdirSync(directory);
  const core = createCore({
    config: loadConfig({PEDIGREE_OPENCODE_ENABLED: "1", PEDIGREE_OPENCODE_TOKEN: "dummy-agent"}),
    projectRoot: fixture.project, workingDirectory: directory,
    fetchImpl: async() => new Response(JSON.stringify({decision: "allow", created: ["dummy"]})),
  });
  const args = {filePath: "new.txt", content: "owned"};
  await core.beforeHook(input("write", "w", args), {args});
  fs.writeFileSync(path.join(directory, "new.txt"), args.content);
  assert.deepEqual(await core.afterHook(input("write", "w", args), {metadata: {
    filepath: path.join(directory, "new.txt"), exists: false, truncated: false}}), {captured: true});
});

test("unavailable edit prestate fails closed with a sanitized error before networking", async(t) => {
  const {core, project, calls} = makeCore();
  t.after(() => removeProject(project));
  const args = {filePath: path.join(project, "missing.txt"), oldString: "old", newString: "new"};
  await assert.rejects(core.beforeHook(input("edit", "e", args), {args}), error => {
    assert.equal(error.code, "malformed");
    assert.ok(!error.message.includes(project));
    return true;
  });
  assert.equal(calls.length, 0);
});
