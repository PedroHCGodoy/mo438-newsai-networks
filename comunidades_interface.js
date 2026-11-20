/* Consulta local de comunidades e notícias de suporte. */
'use strict';
const DATA=JSON.parse(document.getElementById('research-data').textContent);
let activeNews=[], network=null, graphNodes=null, graphEdges=null, representation='community';
const el=id=>document.getElementById(id);
const number=x=>Number(x).toLocaleString('pt-BR');
function element(tag,text,parent){const n=document.createElement(tag);if(text!==null)n.textContent=text;if(parent)parent.appendChild(n);return n;}
function safeLink(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:null;}catch{return null;}}
function article(id,parent){
 const n=DATA.news[id];if(!n)return;
 const item=element('li',null,parent),url=safeLink(n.link);
 if(url){const a=element('a',n.title,item);a.href=url;a.target='_blank';a.rel='noopener noreferrer';}
 else element('span',n.title,item);
 element('small',[n.source,n.publication_date,n.category_grouped].filter(Boolean).join(' · '),item);
}
function setEvidence(ids,title){
 activeNews=[...new Set(ids)];el('evidence-title').textContent=title;
 el('news-search').value='';el('examples').replaceChildren();
 activeNews.slice(0,3).forEach(id=>article(id,el('examples')));renderNews();
}
function renderNews(){
 const term=el('news-search').value.toLocaleLowerCase('pt-BR');
 const ids=activeNews.filter(id=>{const n=DATA.news[id];return n&&[n.title,n.source,n.category_grouped,n.publication_date,n.link].join(' ').toLocaleLowerCase('pt-BR').includes(term);});
 el('news-count').textContent=number(ids.length)+' de '+number(activeNews.length)+' notícias';
 const list=el('full-news');list.replaceChildren();
 ids.forEach(id=>article(id,list));
}
function download(text,type,name){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1500);}
function exportCSV(){
 const keys=['news_id','news_version_id','title','link','source','publication_date','category_grouped','author'];
 const quote=v=>{let s=String(v??'');if(/^[=+@\-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
 const rows=[keys,...activeNews.map(id=>keys.map(k=>DATA.news[id][k]))];
 download('\ufeff'+rows.map(row=>row.map(quote).join(',')).join('\r\n'),'text/csv;charset=utf-8','noticias_suporte.csv');
}
function description(title,lines){el('selection-title').textContent=title;el('selection-detail').replaceChildren();lines.forEach(x=>element('p',x,el('selection-detail')));}
function chooseCommunity(c){
 description(c.run_id+' · C'+c.community_id,[number(c.nodes)+' entidades na comunidade completa; '+number(c.connected_pieces)+' parte(s) conexa(s).',
  number(c.any_news)+' notícias de suporte em qualquer relação incidente; '+number(c.internal_news)+' sustentam relações internas.']);
 const scope=el('support-scope').value;
 setEvidence(DATA.communityNews[c.key][scope],scope==='internal'?'Notícias de relações internas':'Notícias de relações incidentes');
 const target=el('open-graph');target.hidden=!c.graph_file;if(c.graph_file)target.href=c.graph_file;
}
function renderCommunities(){
 const term=el('community-search').value.toLocaleLowerCase('pt-BR'),run=el('partition').value;
 const rows=DATA.communities.filter(c=>c.run_id===run&&[c.community_id,c.top_names].join(' ').toLocaleLowerCase('pt-BR').includes(term));
 el('community-count').textContent=number(rows.length)+' comunidades encontradas';
 const body=el('community-rows');body.replaceChildren();
 rows.forEach(c=>{const row=element('tr',null,body);const cell=element('td',null,row);const button=element('button','C'+c.community_id,cell);button.onclick=()=>chooseCommunity(c);
  [number(c.nodes),number(c.internal_news),c.connected_pieces>1?'Desconectada ('+c.connected_pieces+')':'Conexa',c.top_names].forEach(x=>element('td',x,row));});
}
function showNode(id){const n=DATA.nodeDetails[id];if(!n)return;
 description(n.name,[n.type+' · grupo '+id+' · comunidade C'+n.community_id,
  number(n.neighbor_degree)+' vizinhos na rede completa; força total '+number(n.weighted_strength)+'.',
  'Suporte: notícias com relações incidentes a esta entidade na rede completa, inclusive fora desta vista.']);
 setEvidence(DATA.nodeNews[id]||[],'Notícias de suporte da entidade');
}
function showEdge(id){const e=DATA.edgeDetails[id];if(!e)return;
 const lines=['Peso agregado: '+number(e.weight)+' registros; '+number(e.news_count)+' notícias distintas.',
  'Rótulos originais: '+e.labels.join(', ')+'.',number(e.typed_edge_ids.length)+' aresta(s) tipada(s) representada(s).',
  e.directed?'Suporte completo desta direção, considerando seus rótulos originais.':'Associação não dirigida: soma dos pesos de ambas as direções, sem criar novas relações.'];
 if(e.original_directions)lines.push(...e.original_directions);
 description(e.from_name+(e.directed?' → ':' — ')+e.to_name,lines);
 setEvidence(DATA.edgeNews[id]||[],'Notícias de suporte da conexão');
}
function exportSVG(){
 const p=network.getPositions(),escape=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
 const values=Object.values(p),xs=values.map(v=>v.x),ys=values.map(v=>v.y),x=Math.min(...xs)-100,y=Math.min(...ys)-100,w=Math.max(...xs)-x+100,h=Math.max(...ys)-y+100;
 let s=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x} ${y} ${w} ${h}"><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="white"/><defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="#87939a"/></marker></defs>`;
 graphEdges.forEach(e=>{const a=p[e.from],b=p[e.to];s+=`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#87939a" stroke-width="${e.width}" opacity=".5" ${representation==='semantic'?'marker-end="url(#arrow)"':''}/>`;});
 graphNodes.forEach(n=>{const a=p[n.id],color=typeof n.color==='string'?n.color:n.color.background;s+=`<circle cx="${a.x}" cy="${a.y}" r="${n.size}" fill="${escape(color)}"/>`;
 if(n.label)s+=`<text x="${a.x}" y="${a.y+n.size+14}" text-anchor="middle" font-family="sans-serif" font-size="12">${escape(n.label)}</text>`;});
 download(s+'</svg>','image/svg+xml','grafo_interativo.svg');
}
function startGraph(){
 el('color-mode').value=DATA.default_color_mode;el('representation').value='community';
 graphNodes=new vis.DataSet(DATA.graph.nodes);graphEdges=new vis.DataSet(DATA.graph.edges);
 network=new vis.Network(el('mynetwork'),{nodes:graphNodes,edges:graphEdges},DATA.graph.options);
 network.on('click',p=>{if(p.nodes.length)showNode(p.nodes[0]);else if(p.edges.length)showEdge(p.edges[0]);});
 el('find-node').oninput=()=>{const term=el('find-node').value.toLocaleLowerCase('pt-BR');const list=el('node-results');list.replaceChildren();
  Object.entries(DATA.nodeDetails).filter(([id,n])=>[id,n.name].join(' ').toLocaleLowerCase('pt-BR').includes(term)).slice(0,20).forEach(([id,n])=>{
   const b=element('button',n.name+' · '+id,list);b.onclick=()=>{network.selectNodes([Number(id)]);network.focus(Number(id),{scale:1.1,animation:true});showNode(id);};});};
 el('find-node').oninput();
 function legend(){const mode=el('color-mode').value;const target=el('legend');target.replaceChildren();
  const entries=mode==='type'?[{name:'Pessoa',color:'#4C78A8'},{name:'Organização',color:'#F58518'},{name:'Local',color:'#54A24B'}]:DATA.communityLegend;
  entries.forEach(e=>{const s=element('span','● '+e.name,target);s.style.color=e.color;});}
 el('color-mode').onchange=()=>{graphNodes.update(DATA.graph.nodes.map(n=>({id:n.id,color:el('color-mode').value==='type'?DATA.nodeDetails[n.id].type_color:DATA.nodeDetails[n.id].community_color})));legend();};legend();
 el('show-labels').onchange=()=>graphNodes.update(DATA.graph.nodes.map(n=>({id:n.id,label:el('show-labels').checked?DATA.nodeDetails[n.id].name:n.label})));
 el('fit').onclick=()=>network.fit({animation:true});
 let physics=false;el('physics').onclick=()=>{physics=!physics;network.setOptions({physics:{enabled:physics}});el('physics').textContent=physics?'Pausar física':'Ativar física';};
 el('png').onclick=()=>{const a=document.createElement('a');a.download='grafo_interativo.png';a.href=el('mynetwork').querySelector('canvas').toDataURL('image/png');a.click();};
 el('svg').onclick=exportSVG;
 function representationNote(){el('representation-note').textContent=representation==='community'?
  'Vista principal: projeção não dirigida ponderada usada para detectar as comunidades. Uma conexão por par; peso soma as duas direções e todos os rótulos.':
  'Inspeção complementar: relações semânticas originais dirigidas dos mesmos pares selecionados. As comunidades permanecem as detectadas na projeção não dirigida.';}
 el('representation').onchange=()=>{
  representation=el('representation').value;graphEdges.clear();graphEdges.add(representation==='community'?DATA.graph.edges:DATA.semantic_edges);
  network.unselectAll();representationNote();description('Selecione uma entidade ou conexão',[DATA.selection_note]);
  setEvidence(DATA.scopeNews,'Notícias de suporte do recorte completo');
 };representationNote();
 description('Selecione uma entidade ou conexão',[DATA.selection_note]);setEvidence(DATA.scopeNews,'Notícias de suporte do recorte completo');
}
el('news-search').oninput=renderNews;el('csv').onclick=exportCSV;
if(DATA.mode==='graph')startGraph();
else{
 DATA.partitions.forEach(p=>{const o=element('option',p,el('partition'));o.value=p;});
 el('partition').onchange=()=>{renderCommunities();const c=DATA.communities.find(c=>c.run_id===el('partition').value);if(c)chooseCommunity(c);};el('community-search').oninput=renderCommunities;
 el('support-scope').onchange=()=>{const c=DATA.communities.find(c=>el('selection-title').textContent===c.run_id+' · C'+c.community_id);if(c)chooseCommunity(c);};
 renderCommunities();const initial=DATA.communities.find(c=>c.run_id===DATA.partitions[0]);if(initial)chooseCommunity(initial);
}
