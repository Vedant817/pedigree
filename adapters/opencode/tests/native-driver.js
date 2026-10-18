/** Simulated native execution driving actual plugin hooks into a live API. */
import fs from "node:fs";
import path from "node:path";
import { PedigreePlugin } from "../pedigree.js";
const job=JSON.parse(fs.readFileSync(process.argv[2],"utf8"));
const plugin=await PedigreePlugin({directory:job.project,worktree:job.project});
const filePath=path.join(job.project,"created.txt");
const results=[];
async function operation(tool,callID,args,execute,metadata){
 const input={tool,sessionID:job.sessionID,callID};
 try{
 await plugin["tool.execute.before"](input,{args});
 execute();
 const value=await plugin["tool.execute.after"]({...input,args},metadata());
 results.push({tool,ok:true,captured:value?.captured===true});
 }catch(error){results.push({tool,ok:false,code:error.code});}
}
await operation("write","write1",{filePath,content:"owned before\n"},()=>fs.writeFileSync(filePath,"owned before\n"),
 ()=>({output:"",metadata:{filepath:filePath,exists:false,truncated:false}}));
await operation("edit","edit1",{filePath,oldString:"before",newString:"after"},()=>fs.writeFileSync(filePath,"owned after\n"),
 ()=>({output:"",metadata:{filediff:{file:filePath,additions:1,deletions:1},truncated:false}}));
await operation("bash","bash1",{command:"echo owned"},()=>{},
 ()=>({output:"owned\n",metadata:{output:"owned\n",exit:0,truncated:false}}));
// The Bash output is untrusted influence, so a later high-risk mutation must deny.
await operation("write","write2",{filePath,content:"should not run"},()=>fs.writeFileSync(filePath,"should not run"),
 ()=>({output:"",metadata:{filepath:filePath,exists:true,truncated:false}}));
process.stdout.write(JSON.stringify({results})+"\n");
