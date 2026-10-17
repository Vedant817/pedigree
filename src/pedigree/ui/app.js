/* Tenant credentials live only in this closure. No browser persistence. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let token = '', epoch = 0, nodes = [], selected = null, graph = null, preview = null, confirming = false;
  const colors = {ok:'#3483ac', tainted:'#ad3549', preserved:'#177c69', revoked:'#45485e', quarantined:'#a96808'};
  const text = (tag, value, className) => {
    const el = document.createElement(tag); el.textContent = value;
    if (className) el.className = className;
    return el;
  };
  function notice(message, error = false) { $('notice').textContent = message; $('notice').className = error ? 'error' : ''; }
  async function api(path, body) {
    if (!token) throw new Error('Connect with your operator token first.');
    const started = epoch;
    const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
      headers: {'Authorization': 'Bearer ' + token, 'Content-Type':'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body), cache:'no-store', redirect:'error'});
    const result = await response.json();
    if (started !== epoch) throw new DOMException('Connection changed', 'AbortError');
    if (!response.ok) throw new Error(result.error?.message || `Request failed (${response.status}).`);
    return result;
  }
  function fail(error) { if (error.name !== 'AbortError') notice(error.message || 'Request failed. Try again.', true); }
  function showTrace(result) {
    const entries = result && Array.isArray(result.trace) ? result.trace : [];
    if (!entries.length) { $('trace').replaceChildren(text('p','No database operations recorded for the last action.','empty')); return; }
    const total = entries.reduce((sum, entry) => sum + entry.ms, 0);
    const list = document.createElement('ol');
    for (const entry of entries) list.append(text('li',`${entry.op} · ${entry.ms} ms · ${entry.rows} row${entry.rows === 1 ? '' : 's'}`));
    $('trace').replaceChildren(text('p',`${entries.length} op${entries.length === 1 ? '' : 's'} · ${total.toFixed(2)} ms total`,'eyebrow'), list);
  }
  function invalidatePreview() {
    preview = null; $('preview-result').replaceChildren(); $('confirm').hidden = true; $('cancel').hidden = true;
  }
  function controls() {
    $('blame').disabled = !selected; $('impact').disabled = !selected;
    $('check-gate').disabled = !selected;
    $('preview').disabled = !selected || !['Source','Memory'].includes(selected.type) || selected.status === 'revoked';
  }
  function reset() {
    epoch++; token = ''; nodes = []; selected = null; confirming = false;
    invalidatePreview(); if (graph) graph.destroy(); graph = null;
    $('node-list').replaceChildren(text('p','Connect to see recorded nodes.','empty'));
    $('node-count').textContent = '—'; $('selection').replaceChildren(text('p','Select a node to inspect its evidence.','empty'));
    $('selected-status').textContent = 'No selection'; $('evidence').replaceChildren(); $('gate-result').replaceChildren();
    $('affected').replaceChildren(text('li','Inspect impact to see affected actions.','empty'));
    $('trace').replaceChildren(text('p','Trace roots, see impact, preview a revocation or check an action to see its database operations here.','empty'));
    $('graph-empty').hidden = false; $('token').value = ''; $('connection').textContent = 'Disconnected';
    $('connection').className = 'connection'; $('disconnect').hidden = true; controls();
  }
  function renderList() {
    const focusedId = $('node-list').contains(document.activeElement) ? document.activeElement.dataset.nodeId : null;
    const query = $('filter').value.toLowerCase();
    const matches = nodes.filter(n => [n.id,n.title,n.tool,n.kind].filter(Boolean).join(' ').toLowerCase().includes(query));
    const fragment = document.createDocumentFragment();
    for (const node of matches) {
      const button = text('button','', 'node-button' + (selected?.id === node.id ? ' active' : ''));
      button.type = 'button'; button.setAttribute('aria-pressed',String(selected?.id === node.id));
      button.dataset.nodeId = node.id;
      button.append(text('i','',`dot ${node.status}`), document.createTextNode(node.title || node.id),
        text('small', `${node.type} · ${node.status}${node.tool ? ' · ' + node.tool : ''}`));
      button.addEventListener('click', () => select(node.id)); fragment.append(button);
    }
    if (!matches.length) fragment.append(text('p',nodes.length ? 'No nodes match your search.' : 'No recorded nodes. Run capture or seed the dedicated demo tenant.','empty'));
    $('node-list').replaceChildren(fragment);
    if (focusedId) [...$('node-list').querySelectorAll('button')].find(b=>b.dataset.nodeId === focusedId)?.focus({preventScroll:true});
  }
  function select(id) {
    selected = nodes.find(n => n.id === id) || null; invalidatePreview(); $('evidence').replaceChildren(); $('gate-result').replaceChildren();
    $('affected').replaceChildren(text('li','Inspect impact or preview this selection to see an action report.','empty'));
    if (!selected) return controls();
    $('selection').replaceChildren(text('h3',selected.title || selected.id), text('p',selected.id,'mono'),
      text('p',`${selected.type}${selected.kind ? ' / ' + selected.kind : ''}`),
      text('p',selected.uri || selected.tool || 'Recorded lineage'),
      text('p',selected.low_integrity ? 'Carries untrusted influence' : 'No inherited low-integrity flag'));
    $('selected-status').textContent = selected.status;
    if (graph) { graph.$(':selected').unselect(); graph.nodes().filter(n => n.id() === id).select(); }
    controls(); renderList();
  }
  async function refresh() {
    const result = await api('/v1/graph/view'); nodes = result.nodes;
    $('node-count').textContent = String(nodes.length); $('graph-empty').hidden = nodes.length > 0;
    renderList();
    const elements = nodes.map(n => ({data: {id:n.id,label:n.title || n.tool || n.id,status:n.status,type:n.type}}));
    result.edges.forEach((edge, index) => elements.push({data:{id:`edge-${index}`, source:edge.to,target:edge.from,kind:edge.type}}));
    if (graph) graph.destroy();
    graph = cytoscape({container:$('graph'),elements, minZoom:0.25,maxZoom:2.5,
      style:[{selector:'node',style:{'background-color':n=>colors[n.data('status')] || '#91a3b3','label':'data(label)',
        'font-family':'Segoe UI','font-size':10,'text-wrap':'ellipsis','text-max-width':100,'text-valign':'bottom','text-margin-y':9,
        color:'#20374b',width:24,height:24,'border-width':3,'border-color':'#ffffff',shape:n=>({Source:'diamond',Memory:'ellipse',Action:'round-rectangle'}[n.data('type')])}},
      {selector:'edge',style:{width:1.5,'line-color':'#afc5d1','target-arrow-color':'#afc5d1','target-arrow-shape':'triangle','curve-style':'bezier'}},
      {selector:'edge[kind="CORROBORATED_BY"]',style:{'line-style':'dashed','line-color':'#177c69','target-arrow-color':'#177c69'}},
      {selector:':selected',style:{'border-width':4,'border-color':'#176d89'}},
      {selector:'.on-path',style:{'border-width':5,'border-color':'#ad3549','background-color':'#ad3549'}}],
      layout:{name:'breadthfirst',directed:true,padding:38,spacingFactor:1.15,animate:false}});
    graph.on('tap','node',event=>select(event.target.id()));
    if (selected) select(selected.id);
    notice(result.truncated ? 'Showing a bounded graph view. More lineage exists; inspect a selected node for detail.' : `${nodes.length} recorded nodes loaded from your tenant.`);
  }
  function effects(actions) {
    const sorted = [...(actions || [])].sort((a,b)=>Number(b.effect === 'irreversible') - Number(a.effect === 'irreversible'));
    const items = sorted.map(action => {
      const li = text('li',`${action.tool || 'Action'} · ${action.id}`);
      li.append(text('small',action.summary || 'No summary recorded'));
      if (action.effect === 'irreversible') li.append(text('small','Irreversible external effect — review manually','irreversible'));
      if (action.artifacts?.length) li.append(text('small',action.artifacts.join(' · '),'mono'));
      return li;
    });
    $('affected').replaceChildren(...(items.length ? items : [text('li','No affected actions returned for this selection.','empty')]));
  }
  function snapshot() { return {id:selected?.id,reason:$('reason').value,depth:$('depth').value,epoch}; }
  function same(a,b) { return a && a.id === b.id && a.reason === b.reason && a.depth === b.depth && a.epoch === b.epoch; }
  $('connect-form').addEventListener('submit',async event => {
    event.preventDefault(); const candidate = $('token').value.trim(); reset(); token = candidate;
    $('connect-button').disabled = true;
    try { await refresh(); $('connection').textContent = 'Connected'; $('connection').className = 'connection active'; $('disconnect').hidden = false; }
    catch(error) { reset(); fail(error); }
    finally { $('connect-button').disabled = false; }
  });
  $('disconnect').addEventListener('click',()=>{reset();notice('Disconnected. Tenant data and token cleared from this page.');});
  $('filter').addEventListener('input',renderList);
  $('fit').addEventListener('click',()=>graph?.fit(undefined,38));
  $('depth').addEventListener('input',()=>{$('depth-value').textContent=$('depth').value;invalidatePreview();$('evidence').replaceChildren();});
  $('reason').addEventListener('input',invalidatePreview); $('cancel').addEventListener('click',invalidatePreview);
  for (const action of ['blame','impact']) $(action).addEventListener('click',async()=>{
    const node = selected?.id, started = epoch, depth = $('depth').value;
    if (!node) return;
    try {
      const result = await api(`/v1/${action}/${encodeURIComponent(node)}?max_depth=${depth}`);
      if (selected?.id !== node || epoch !== started || $('depth').value !== depth) return;
      const contents = [text('p',action === 'blame' ? 'Recorded roots' : 'Downstream influence','eyebrow')];
      if (action === 'blame') {
        const onPath = new Set();
        for (const root of result.roots) {
          for (const id of root.path || []) onPath.add(id);
          if (root.id) onPath.add(root.id);
        }
        if (graph) {
          graph.elements().removeClass('on-path');
          graph.nodes().filter(node => onPath.has(node.id())).addClass('on-path');
        }
        for (const root of result.roots) contents.push(text('p',`${root.status}: ${(root.path || []).join(' → ') || root.id}`,'mono'));
        if (!result.roots.length) contents.push(text('p','No revoked or low-integrity roots returned within this depth.'));
      } else { contents.push(text('p',`${result.counts.n_total} downstream nodes`)); effects(result.actions); }
      if (result.truncated) contents.push(text('p','Depth limit reached. Additional lineage exists.'));
      $('evidence').replaceChildren(...contents);
      showTrace(result);
    } catch(error) {fail(error);}
  });
  $('preview').addEventListener('click',async()=>{
    const current = snapshot(); invalidatePreview(); if (!current.id) return;
    $('preview').disabled = true;
    try {
      const result = await api('/v1/revoke',{root_id:current.id,reason:current.reason,dry_run:true});
      const impact = await api(`/v1/impact/${encodeURIComponent(current.id)}?max_depth=${current.depth}`);
      if (!same(current,snapshot())) return;
      preview = current;
      const counts = result.counts || {};
      $('preview-result').replaceChildren(text('p',`Would taint ${counts.would_taint || 0} · preserve ${counts.would_preserve || 0} · restore healthy ${counts.would_keep_ok || 0}`),
        text('p',`Selected root: ${current.id}. Preview has made no changes.`));
      effects(result.actions || impact.actions); $('confirm').hidden = false; $('cancel').hidden = false;
      showTrace(result);
    } catch(error) {invalidatePreview();fail(error);} finally {controls();}
  });
  $('confirm').addEventListener('click',async()=>{
    if (confirming || !same(preview,snapshot())) return;
    const current = preview; confirming = true; $('confirm').disabled = true;
    try {
      const result = await api('/v1/revoke',{root_id:current.id,reason:current.reason,dry_run:false});
      invalidatePreview(); await refresh(); effects(result.actions); showTrace(result);
      notice('Revocation recorded. Graph refreshed from persisted state.');
    } catch(error) {invalidatePreview();fail(error);} finally {confirming = false;$('confirm').disabled = false;}
  });
  $('gate-form').addEventListener('submit',async event=>{
    event.preventDefault(); const node = selected?.id; if (!node) return;
    $('check-gate').disabled = true;
    try {
      const result = await api('/v1/gate',{action:{tool:'Bash',summary:$('command').value},relied_on:[node]});
      if (selected?.id !== node) return;
      $('gate-result').replaceChildren(text('h3',result.decision), ...result.reasons.map(r=>text('p',`${r.code}: ${r.detail}${r.path.length ? ' · ' + r.path.join(' → ') : ''}`)));
      showTrace(result);
    } catch(error) {fail(error);} finally {controls();}
  });
})();
