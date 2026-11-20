/* Seleção automática e exploração local de entidades ao longo dos cortes. */
'use strict';
const DATA=JSON.parse(document.getElementById('research-data').textContent);
const el=id=>document.getElementById(id),fmt=n=>Number(n).toLocaleString('pt-BR');
const normalize=s=>String(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');
let year=2025,focusId=null,selected=null,activeNews=[],filteredNews=[],page=0,physics=true,cacheYear=null,cache=null,view={nodes:[],edges:[]};
const pageSize=40;
const catalogEntries=Object.entries(DATA.node_catalog).map(([id,n])=>({id:Number(id),...n,search:normalize(n.name+' '+id)}));
function text(tag,value,parent){const n=document.createElement(tag);if(value!==null)n.textContent=value;if(parent)parent.appendChild(n);return n;}
function scopeName(){return focusId===null?'global':String(focusId);}
function current(){return view;}
function fullYear(){
 if(cacheYear===year)return cache;
 const s=DATA.series[String(year)],typed=new Map();
 for(const r of s.typed){if(!typed.has(r[0]))typed.set(r[0],[]);typed.get(r[0]).push({source_id:r[1],target_id:r[2],label:DATA.labels[r[3]],weight:r[4]});}
 const allNodes=new Map(s.nodes.map(r=>[r[0],{id:r[0],degree:r[1],strength:r[2],rank:r[3],new_neighbors:r[4]<0?null:r[4],mention_news:r[5],relation_news:r[6]}]));
 const allPairs=s.pairs.map(r=>({id:String(r[0]),from:r[1],to:r[2],weight:r[3],news_count:r[4]}));
 cacheYear=year;cache={nodes:allNodes,pairs:allPairs,typed,leaders:s.leaders};return cache;
}
function selectGraph(){
 const data=fullYear();let chosen;
 if(focusId===null)chosen=[...data.nodes.values()].sort((a,b)=>b.degree-a.degree||a.id-b.id).slice(0,DATA.max_nodes);
 else if(!data.nodes.has(focusId))return {nodes:[],edges:[]};
 else{
  const adjacent=data.pairs.filter(e=>e.from===focusId||e.to===focusId).map(e=>({id:e.from===focusId?e.to:e.from,weight:e.weight}));
  adjacent.sort((a,b)=>b.weight-a.weight||data.nodes.get(b.id).degree-data.nodes.get(a.id).degree||a.id-b.id);
  chosen=[data.nodes.get(focusId),...adjacent.slice(0,DATA.max_nodes-1).map(n=>data.nodes.get(n.id))];
 }
 const ids=new Set(chosen.map(n=>n.id));
 const edges=data.pairs.filter(e=>ids.has(e.from)&&ids.has(e.to));
 edges.sort((a,b)=>Number(b.from===focusId||b.to===focusId)-Number(a.from===focusId||a.to===focusId)||b.weight-a.weight||a.from-b.from||a.to-b.to);
 return {nodes:chosen.sort((a,b)=>a.id-b.id),edges:edges.slice(0,DATA.max_pairs)};
}
function newsBefore(ids){return [...new Set(ids)].filter(id=>DATA.news[id]&&Number(DATA.news[id].publication_year)<=year).sort((a,b)=>String(DATA.news[b].publication_date).localeCompare(String(DATA.news[a].publication_date))||a-b);}
function safeURL(value){try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;}}
function article(id,parent){const n=DATA.news[id],li=text('li',null,parent),url=safeURL(n.link);if(url){const a=text('a',n.title||'(Sem título)',li);a.href=url;a.target='_blank';a.rel='noopener noreferrer';}else text('span',n.title||'(Sem título)',li);text('small',[n.publication_date,n.source,n.category_grouped].filter(Boolean).join(' · '),li);text('small','RE: '+n.re_state,li);}
function showEvidence(ids,title){activeNews=newsBefore(ids);el('evidence-title').textContent=title;el('news-search').value='';page=0;el('examples').replaceChildren();activeNews.slice(0,3).forEach(id=>article(id,el('examples')));renderNews();}
function renderNews(){const term=normalize(el('news-search').value);filteredNews=activeNews.filter(id=>{const n=DATA.news[id];return normalize([n.title,n.link,n.publication_date,n.category_grouped,n.author].join(' ')).includes(term);});const pages=Math.max(1,Math.ceil(filteredNews.length/pageSize));page=Math.max(0,Math.min(page,pages-1));el('evidence-count').textContent=fmt(activeNews.length)+' notícias até '+year+' · '+fmt(filteredNews.length)+' na busca';el('news-list').replaceChildren();el('news-list').start=page*pageSize+1;filteredNews.slice(page*pageSize,(page+1)*pageSize).forEach(id=>article(id,el('news-list')));el('page').textContent=(page+1)+' / '+pages;el('news-prev').disabled=page===0;el('news-next').disabled=page>=pages-1;}
function download(content,type,name){const url=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);}
function csvValue(value){let s=String(value??'');if(/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';}
function exportCSV(){const cols=['news_id','news_version_id','title','link','author','source','publication_date','publication_year','category_grouped','ner_availability','re_state'];download('\ufeff'+[cols.map(csvValue).join(','),...activeNews.map(id=>cols.map(k=>csvValue(DATA.news[id][k])).join(','))].join('\r\n'),'text/csv;charset=utf-8','noticias_'+year+'_'+scopeName()+'.csv');}
const nodes=new vis.DataSet(),edges=new vis.DataSet();
const network=new vis.Network(el('graph'),{nodes,edges},{nodes:{shape:'dot',font:{size:12,color:'#203440'}},edges:{smooth:{enabled:false},color:{color:'#87939a',opacity:.45}},interaction:{hover:true,keyboard:true},layout:{randomSeed:42},physics:{enabled:true,solver:'forceAtlas2Based',forceAtlas2Based:{gravitationalConstant:-55,centralGravity:.01,springLength:120,springConstant:.05,damping:.4,avoidOverlap:.4}}});
function nodeInfo(id){const n=fullYear().nodes.get(id);if(!n)return;selected={kind:'node',id};const info=DATA.node_catalog[String(id)],box=el('detail');box.replaceChildren();text('h3',info.name,box);text('p','ID '+id+' · '+(DATA.type_names[info.type]||info.type),box);text('p','Grau completo: '+fmt(n.degree)+' · posição com empates: '+fmt(n.rank),box);text('p','Força: '+fmt(n.strength)+' · novos vizinhos no ano: '+(n.new_neighbors===null?'estoque inicial de 1994':fmt(n.new_neighbors)),box);text('p','Notícias com menções: '+fmt(n.mention_news)+' · com participação em relações: '+fmt(n.relation_news),box);const refs=DATA.node_news[String(id)]||[];showEvidence(refs.filter(r=>el('all-mentions').checked||r[1]>0).map(r=>r[0]),el('all-mentions').checked?'Notícias com menções à entidade':'Notícias com participação relacional');}
function edgeInfo(id){const e=view.edges.find(e=>e.id===id);if(!e)return;selected={kind:'edge',id};const box=el('detail');box.replaceChildren();text('h3',DATA.node_catalog[String(e.from)].name+' — '+DATA.node_catalog[String(e.to)].name,box);text('p','Par não dirigido · '+DATA.pair_catalog[Number(id)][0],box);text('p',fmt(e.weight)+' ocorrências · '+fmt(e.news_count)+' notícias distintas',box);text('p','Composição semântica dirigida:',box);const list=text('ul',null,box);for(const d of fullYear().typed.get(Number(id))||[])text('li',DATA.node_catalog[String(d.source_id)].name+' → '+DATA.node_catalog[String(d.target_id)].name+' · '+d.label+' · '+fmt(d.weight),list);showEvidence(DATA.pair_news[id]||[],'Notícias que sustentam o par');}
function scopeInfo(){selected=null;el('detail').replaceChildren();text('p','Selecione um nó ou par. A lista cobre a rede completa do corte, incluindo relações fora da vista.',el('detail'));showEvidence(DATA.support_news,'Notícias da rede completa do corte');}
function setPhysics(on){physics=on;network.setOptions({physics:{enabled:on}});el('physics').textContent=on?'Desativar física':'Ativar física';if(on)network.startSimulation();else network.stopSimulation();}
function chooseEntity(id){focusId=Number(id);el('find').value=DATA.node_catalog[String(id)].name;update();if(fullYear().nodes.has(focusId)){nodeInfo(focusId);network.selectNodes([focusId]);network.focus(focusId,{scale:1,animation:true});}}
function nodeStyle(n,leaders){const info=DATA.node_catalog[String(n.id)],needle=normalize(el('find').value),match=needle&&normalize(info.name+' '+n.id).includes(needle),focused=n.id===focusId;const baseSize=Math.min(35,8+2.5*Math.log1p(n.degree));return {id:n.id,label:el('labels').checked||leaders.has(n.id)||focused?info.name:'',x:DATA.positions[String(n.id)][0],y:DATA.positions[String(n.id)][1],size:baseSize,color:{background:DATA.type_colors[info.type],border:focused||match?'#dc2626':leaders.has(n.id)?'#203440':'#ffffff',highlight:{background:DATA.type_colors[info.type],border:'#dc2626'}},borderWidth:focused?3:match?3:leaders.has(n.id)?2:1,shadow:focused?{enabled:true,color:'rgba(220,38,38,.45)',size:18,x:0,y:0}:{enabled:false},font:{size:12,face:'sans-serif'},title:text('div',info.name+' · ID '+n.id+' · grau '+n.degree)};}
function renderSearch(){
 const term=normalize(el('find').value),box=el('search-results');box.replaceChildren();
 if(!term){el('search-status').textContent='Busca em todas as '+fmt(catalogEntries.length)+' entidades da série temporal.';return;}
 const candidates=catalogEntries.filter(n=>n.search.includes(term)).sort((a,b)=>Number(fullYear().nodes.has(b.id))-Number(fullYear().nodes.has(a.id))||(fullYear().nodes.get(b.id)?.degree||0)-(fullYear().nodes.get(a.id)?.degree||0)||a.id-b.id);
 el('search-status').textContent=fmt(candidates.length)+' correspondências; até 30 opções mostradas. '+(focusId!==null?'Entidade acompanhada: ID '+focusId+(fullYear().nodes.has(focusId)?' — presente neste ano.':' — ainda ausente da rede neste ano.'):'Selecione uma entidade para abrir sua vizinhança.');
 candidates.slice(0,30).forEach(n=>{const b=text('button',n.name+' · '+n.type+' · ID '+n.id+(fullYear().nodes.has(n.id)?'':' · ausente em '+year),box);b.onclick=()=>chooseEntity(n.id);});
}
function update(){
 const preference=physics;network.stopSimulation();network.setOptions({physics:{enabled:false}});view=selectGraph();edges.clear();nodes.clear();const leaders=new Set(fullYear().leaders);
 nodes.add(view.nodes.map(n=>nodeStyle(n,leaders)));edges.add(view.edges.map(e=>({id:e.id,from:e.from,to:e.to,width:Math.min(6,1+Math.log1p(e.weight)/2),title:text('div',fmt(e.weight)+' ocorrências · '+fmt(e.news_count)+' notícias')})));
 const c=DATA.coverage[String(year)],metrics=el('metrics');metrics.replaceChildren();for(const [label,value]of[['Nós na rede completa',c.cumulative_nodes],['Pares na rede completa',c.cumulative_undirected_pairs],['Notícias de suporte acumuladas',c.cumulative_support_news]]){const b=text('div',null,metrics);b.className='metric';text('b',fmt(value),b);text('span',label,b);}
 let info='Subgrafo: '+fmt(view.nodes.length)+' nós e '+fmt(view.edges.length)+' pares. '+(focusId===null?'Seleção por grau no ano, desempate operacional por ID; pares por peso.':'Vizinhança de um salto de '+DATA.node_catalog[String(focusId)].name+'; vizinhos por peso, grau e ID.');
 if(focusId!==null&&!view.nodes.length)info+=' A entidade ainda não aparece nesta rede; a busca foi mantida.';if(year===2021)info+=' ATENÇÃO: 2021 não tem RE concluída nesta edição.';el('scope').textContent=info;
 el('coverage').textContent='Ano '+year+': '+fmt(c.re_completed_strict)+' / '+fmt(c.corpus_news)+' notícias com RE estritamente concluída ('+(100*c.strict_completion_share).toFixed(1).replace('.',',')+'%); '+fmt(c.re_partial)+' parciais; '+fmt(c.support_news)+' sustentam relações. '+(DATA.reference_years.includes(year)?'Marco de referência.':'Corte anual adicional.');
 el('ranking-criterion').textContent='Seleção automática dos 15 destaques em '+year+', por grau (quantidade de vizinhos distintos na rede completa acumulada até '+year+'), ordem decrescente, incluindo todos os empates na 15ª posição.';
 el('ranking-list').replaceChildren();const menu=el('view');menu.replaceChildren();text('option','Rede — seleção por grau',menu).value='global';
 for(const id of fullYear().leaders){const n=fullYear().nodes.get(id),name=DATA.node_catalog[String(id)].name;text('option',name+' · grau '+n.degree+' · posição '+n.rank,menu).value=String(id);text('div',n.rank+'º · '+name+' · grau '+n.degree,el('ranking-list'));}
 if(focusId!==null&&!leaders.has(focusId))text('option','Entidade acompanhada: '+DATA.node_catalog[String(focusId)].name,menu).value=String(focusId);menu.value=scopeName();
 el('year').value=String(year);el('slider').value=String(year);el('prev').disabled=year===1994;el('next').disabled=year===2025;
 scopeInfo();renderSearch();network.fit({animation:false});setPhysics(preference);if(focusId!==null&&fullYear().nodes.has(focusId))nodeInfo(focusId);
}
network.on('click',params=>{if(params.nodes.length)nodeInfo(params.nodes[0]);else if(params.edges.length)edgeInfo(params.edges[0]);});
DATA.years.forEach(y=>{const o=text('option',y+(DATA.reference_years.includes(y)?' · referência':''),el('year'));o.value=String(y);});
for(const [type,color]of Object.entries(DATA.type_colors)){const item=text('span',null,el('legend')),dot=text('span',null,item);dot.className='dot';dot.style.backgroundColor=color;text('span',DATA.type_names[type],item);}
const yearChanged=y=>{year=Number(y);update();};el('year').onchange=()=>yearChanged(el('year').value);el('slider').oninput=()=>yearChanged(el('slider').value);el('prev').onclick=()=>yearChanged(Math.max(1994,year-1));el('next').onclick=()=>yearChanged(Math.min(2025,year+1));
el('view').onchange=()=>{if(el('view').value==='global'){focusId=null;el('find').value='';update();}else chooseEntity(Number(el('view').value));};
el('find').oninput=()=>{if(!el('find').value){focusId=null;update();return;}renderSearch();const leaders=new Set(fullYear().leaders);for(const n of view.nodes){const style=nodeStyle(n,leaders);delete style.x;delete style.y;nodes.update(style);}};
el('labels').onchange=()=>{const leaders=new Set(fullYear().leaders);for(const n of view.nodes)nodes.update({id:n.id,label:el('labels').checked||leaders.has(n.id)||n.id===focusId?DATA.node_catalog[String(n.id)].name:''});};
el('physics').onclick=()=>setPhysics(!physics);el('reset').onclick=()=>{setPhysics(false);for(const n of view.nodes){const p=DATA.positions[String(n.id)];network.moveNode(n.id,p[0],p[1]);}network.fit({animation:false});};el('fit').onclick=()=>network.fit({animation:true});
el('scope-news').onclick=scopeInfo;el('all-mentions').onchange=()=>{if(selected&&selected.kind==='node')nodeInfo(selected.id);};el('news-search').oninput=()=>{page=0;renderNews();};el('news-prev').onclick=()=>{page--;renderNews();};el('news-next').onclick=()=>{page++;renderNews();};el('csv').onclick=exportCSV;
el('png').onclick=()=>{const c=el('graph').querySelector('canvas');if(c){const a=document.createElement('a');a.href=c.toDataURL('image/png');a.download='grafo_'+year+'_'+scopeName()+'.png';a.click();}};
function svgEscape(s){return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
el('svg').onclick=()=>{if(!view.nodes.length)return;const pos=network.getPositions(),xs=view.nodes.map(n=>pos[n.id].x),ys=view.nodes.map(n=>pos[n.id].y),x0=Math.min(...xs)-150,y0=Math.min(...ys)-70,w=Math.max(...xs)-x0+150,h=Math.max(...ys)-y0+70;let s='<svg xmlns="http://www.w3.org/2000/svg" viewBox="'+[x0,y0,w,h].join(' ')+'"><title>'+svgEscape('Subgrafo acumulado até '+year)+'</title><rect x="'+x0+'" y="'+y0+'" width="'+w+'" height="'+h+'" fill="white"/>';for(const e of view.edges){const a=pos[e.from],b=pos[e.to];s+='<line x1="'+a.x+'" y1="'+a.y+'" x2="'+b.x+'" y2="'+b.y+'" stroke="#87939a" stroke-opacity=".5" stroke-width="'+Math.min(6,1+Math.log1p(e.weight)/2)+'"/>';}for(const n of view.nodes){const p=pos[n.id],info=DATA.node_catalog[String(n.id)],v=nodes.get(n.id);s+='<circle cx="'+p.x+'" cy="'+p.y+'" r="'+v.size+'" fill="'+DATA.type_colors[info.type]+'" stroke="'+v.color.border+'" stroke-width="'+v.borderWidth+'"/>';if(v.label)s+='<text x="'+(p.x+v.size+3)+'" y="'+p.y+'" font-size="12" font-family="sans-serif">'+svgEscape(info.name)+'</text>';}download(s+'</svg>','image/svg+xml','grafo_'+year+'_'+scopeName()+'.svg');};
update();
