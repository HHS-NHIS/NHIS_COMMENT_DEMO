/* V10.9: one management analysis screen. Frozen source and historical reports unchanged. */
(function(){
'use strict';
const E=id=>document.getElementById(id);
const isManagement=()=>!E('tab-management').classList.contains('hide');
let installed=false,optionsReq=0,resultsReq=0,initialized=false;
const oldShow=showTab,oldParams=v107Params;
function sourceState(){
 const section=E('mgSection').value||'summary';
 return {
    section,theme_original:E('mgTheme').value||'',
    v107_topic:E('mgTopic').value||'',v109_topic_compare:E('mgTopicCompare').value||'',
    v107_tier:E('mgTier').value||'any',
    v107_content:section==='content'?E('mgContent').value||'':'',
    v109_form_flag:E('mgFormFlag').value||'all',form_mode:'all',
    q:E('mgQuery').value.trim(),match:'phrase',
    questionnaire:section==='questionnaire'?E('mgQuestionnaire').value||'':''
 };
}
function params(q){return new URLSearchParams(q).toString();}
v107Params=function(){
 if(!isManagement())return oldParams();
 return {...sourceState(),form_mode:E("mgFormAudit")?.open?(E("mgAuditMode")?.value||"all"):"all"};
};
showTab=function(tab){
 if(tab==='feedback')tab='management';
 oldShow(tab);
 E('v107GlobalPanel').classList.add('hide');
 if(tab==='management'){setup();refreshFacets(false);}
};
function setup(){
 if(installed)return;
 installed=true;
 E('v107GlobalPanel').classList.add('hide');
 document.querySelector('.nav[data-tab="feedback"]')?.classList.add('hide');
 sections.management=['MANAGEMENT ANALYSIS','Explore categories, topics and evidence.',
  'One source-linked analysis using original AI themes, additional measures, content requests and likely form-letter identification.'];
 const panel=E('mgNarrative').closest('article.panel');
 const live=document.createElement('section');live.id='mgFilteredSummary';
 live.innerHTML='<h3>Filtered management analysis</h3><p>Loading matching submissions…</p>';
 panel.insertBefore(live,E('mgComboSummary'));
 const old=document.createElement('details');old.className='mg-reference';old.id='mgFullCorpusReference';
 old.innerHTML='<summary>Full-Corpus Management Synthesis &amp; Reports — 3,748 Submissions</summary>'+
  '<p class="footnote">Precompiled analysis covering all publicly indexed submissions, using the earlier management classification methodology. Saved prose and citations do not recompute when filters change. Current filtered counts, evidence and CSV are shown above.</p>';
 panel.insertBefore(old,live.nextSibling);
 for(const id of ['mgComboSummary','mgNarrative','mgRuleDetails','mgCitations',
      'mgCompiledArguments','mgRepeatedGroups','mgTopics','v107ManagementScope','v107ManagementSignals']){
   const node=E(id);if(node)old.appendChild(node);
 }
 const audit=document.createElement('details');audit.className='mg-reference';audit.id='mgFormAudit';
 audit.innerHTML='<summary>Form-Letter and Topic Audit — cluster representatives, personalized variants and source excerpts</summary>'+
 '<p class="footnote">Source submissions are never deleted. A likely form-letter flag is based on repeated or near-duplicate text. Review personalized variants and inferred links before deciding that substantive arguments are duplicates.</p>';
 const legacy=E('tab-feedback').querySelector('article.panel');
 if(legacy){while(legacy.firstChild)audit.appendChild(legacy.firstChild);}
 const tool=document.createElement('div');tool.className='formrow';
 tool.innerHTML='<label><span>Cluster audit display</span><select id="mgAuditMode"><option value="all">All matching comments</option><option value="representative">One representative per inferred group</option><option value="exclude_clusters">Only comments outside identified groups</option></select></label>'+
 '<p class="footnote">Audit only: representative groups (882 overall) and unclustered submissions (837 overall) are different units. The main analyst results always count selected submissions.</p>';
 audit.insertBefore(tool,audit.children[2]||null);
 E('tab-management').appendChild(audit);
 E('mgAuditMode').onchange=()=>{if(audit.open)v107Render();};
 audit.addEventListener('toggle',()=>{if(audit.open)v107Render();});
 E('mgNarrativeTitle').textContent='Filtered Management Analysis';
 const themeIntro=E('mgTheme').closest('.formrow');
 if(themeIntro)themeIntro.classList.add('mg-analyzer-controls');
 E('mgDownloadWord').textContent='Download full-corpus Word report ↓';
 E('mgDownloadTopicWord').textContent='Download full-corpus topic appendix (Word) ↓';
 E('mgDownloadTopicCSV').textContent='Download precompiled category × topic summaries (CSV) ↓';
 E('mgDownloadCodedCSV').textContent='Download all 3,748 coded comments ↓';
}
function choices(select,allText,entries,desired){
 select.replaceChildren(new Option(allText,''));
 for(const obj of entries){
   select.appendChild(new Option(obj.label+' ('+obj.count+')',obj.id));
 }
 const yes=entries.some(x=>x.id===desired);
 select.value=yes?desired:'';
 return Boolean(desired&&!yes);
}
async function refreshFacets(renderIfChanged=true){
 if(!isManagement()||!managementState?.ready)return;
 const ticket=++optionsReq;
 let wasReset=false;
 for(let round=0;round<3;round++){
   const current=sourceState();
   try{
     const result=await api('/api/v108/management-options?'+params(current));
     if(ticket!==optionsReq||!isManagement())return;
     const changed1=choices(E('mgTheme'),'All original AI themes',result.original_themes,current.theme_original);
     const changed2=choices(E('mgTopic'),'All additional topics',result.additional_topics,current.v107_topic);
     const compared=E('mgTopicCompare');
     compared.disabled=!E('mgTopic').value;
     const changed3=choices(compared,'All comparison topics',result.comparison_topics,
         compared.disabled?'':current.v109_topic_compare);
     const content=E('mgContent'),visible=current.section==='content';
     content.closest('label').classList.toggle('hide',!visible);
     const changed4=choices(content,'All recommendation types',result.recommendation_types,
         visible?current.v107_content:'');
     const changed5=choices(E('mgFormFlag'),'All comments',result.form_flag_choices,current.v109_form_flag);
     const tier=E('mgTier'),tierOn=Boolean(E('mgTopic').value||compared.value);
     tier.closest('label').classList.toggle('hide',!tierOn);
     tier.replaceChildren(new Option('All topic mentions','any'));
     if(tierOn)for(const r of result.topic_roles)tier.appendChild(new Option(r.label+' ('+r.count+')',r.id));
     const validRole=current.v107_tier==='any'||
       result.topic_roles.some(x=>x.id===current.v107_tier);
     tier.value=tierOn&&validRole?current.v107_tier:'any';
     const changed=changed1||changed2||changed3||changed4||changed5||
          (!validRole&&current.v107_tier!=='any');
     wasReset=wasReset||changed;
     E('mgIntegratedContext').textContent=
       'Current intersection: '+number(result.matching_submissions)+' source submissions. '+
       number(result.identified_form_letter_submissions)+' with identified repeated/near-duplicate text; '+
       number(result.unclustered_submissions)+' without. All dropdowns include All. '+
       'Selections combine with AND; provisional multi-label classifications.';
     if(!changed)break;
   }catch(err){
     if(ticket===optionsReq)E('mgIntegratedContext').textContent='Filter options unavailable: '+err.message;
     break;
   }
 }
 if(wasReset&&renderIfChanged){managementPage=1;await managementComments();}
}
function evidenceCard(r){
 const href=safeHref(r.comment_url);
 return '<article class="comment-card"><div class="comment-meta"><span>'+esc(r.comment_id)+
   ' · '+esc(r.posted_date||'')+'</span>'+(href?'<a target="_blank" rel="noopener noreferrer" href="'+esc(href)+'">Source ↗</a>':'')+
   '</div><div class="comment-title">'+esc(r.title||r.organization||r.comment_id)+'</div>'+
   '<div class="comment-snippet">'+esc(String(r.excerpt||'').slice(0,530))+'</div>'+
   '<div class="footnote">'+(r.cluster_size>1?number(r.cluster_size)+' submissions in this likely form-letter group · ':'')+
   '<button type="button" class="textbutton open-detail" data-id="'+esc(r.comment_id)+'">Read full text and classifications →</button></div></article>';
}
function topicTable(stats){
 const included=stats.topics.filter(x=>x.primary+x.secondary>0).sort((a,b)=>b.primary+b.secondary-a.primary-a.secondary);
 return included.length?'<table class="mg-topics-table"><thead><tr><th>Additional management topic</th><th>Primary</th><th>Secondary</th></tr></thead><tbody>'+
 included.map(t=>'<tr><td>'+esc(t.label)+'</td><td>'+number(t.primary)+'</td><td>'+number(t.secondary)+'</td></tr>').join('')+
 '</tbody></table>':'<p>No additional topics in this selection.</p>';
}
async function managementComments(){
 if(!managementState?.ready||!isManagement())return;
 setup();
 const ticket=++resultsReq;const q=sourceState();
 const url=params(q);
 try{
   const [list,stats]=await Promise.all([
     api('/api/management/comments?'+params({...q,page:managementPage,size:20})),
     api('/api/v107/stats?'+url)
   ]);
   if(ticket!==resultsReq||!isManagement())return;
   const section=E('mgSection').selectedOptions[0]?.textContent||'All management categories';
   const summary=E('mgFilteredSummary');
   const identified=stats.identified_form_letter_submissions??stats.status_counts?.likely_form_letter??0;
   let content='<h3>Filtered management analysis · '+esc(section)+'</h3>'+
     '<div class="mg-kpi-grid"><div class="mg-kpi"><strong>'+number(list.source_submission_matches)+'</strong><span>Matching submissions</span></div>'+
     '<div class="mg-kpi"><strong>'+number(list.total)+'</strong><span>Displayed records</span></div>'+
     '<div class="mg-kpi"><strong>'+number(stats.approximate_clusters_in_filtered_submissions)+'</strong><span>Approximate text groups in selection</span></div>'+
     '<div class="mg-kpi"><strong>'+number(identified)+'</strong><span>Matching submissions with repeated/near-duplicate text</span></div></div>';
   if(stats.topic_intersection){
     const pair=stats.topic_intersection;
     content+='<div id="mgTopicOverlap"><h4>Additional-topic intersection</h4>'+
       '<p><strong>'+number(pair.both)+'</strong> comments contain both selected topics within the current management/legacy-theme cohort. '+
       'The smaller topic has '+number(pair.pct_of_smaller)+'% overlap; Jaccard similarity is '+number(pair.jaccard)+'%.</p>'+
       '<p class="footnote">Smaller-topic overlap = both/min(topic A, topic B); Jaccard = both/either. These use submission counts, not people, and the selected Primary/Secondary restriction applies to both topics.</p></div>';
   }
   if(q.section==='content'){
     const ct=stats.content_subcategories.filter(x=>x.count>0);
     content+='<h4>Content recommendation types</h4>'+
       (ct.length?ct.map(x=>'<p>'+esc(x.label)+': <strong>'+number(x.count)+'</strong></p>').join(''):'<p>No type assigned.</p>');
   }
   if(q.section==='support'&&stats.support_review){
     content+='<h4>Possible support for specific measures — analyst review</h4>'+
     '<p>'+number(stats.support_review.count)+' comments identified for review, outside confirmed Support counts. Examples: '+
     (stats.support_review.example_ids||[]).slice(0,10).map(cid=>
       '<button type="button" class="tag open-detail" data-id="'+esc(cid)+'">'+esc(cid)+' ↗</button>').join(' ')+'</p>';
   }
   content+='<h4>Primary and secondary additional topics</h4>'+topicTable(stats)+
     '<p class="footnote">Each comment can be tagged to multiple topics. The table reflects this filtered record set; totals are not mutually exclusive.</p>';
   summary.innerHTML=content;
   E('mgCount').textContent=number(list.total)+' matching source records · '+number(stats.approximate_clusters_in_filtered_submissions)+
       ' approximate text groups; historical full-corpus reports remain separately available.';
   E('mgResults').innerHTML=(list.rows||[]).map(evidenceCard).join('')||'<p>No matching comments. Broaden a topic or choose All.</p>';
   const pages=Math.ceil(list.total/(list.page_size||20));
   E('mgPager').innerHTML=pages>1?
      '<button id="mgPrev" '+(managementPage<=1?'disabled':'')+'>← Previous</button> Page '+number(managementPage)+' of '+number(pages)+
      ' <button id="mgNext" '+(managementPage>=pages?'disabled':'')+'>Next →</button>':'';
   if(E('mgPrev'))E('mgPrev').onclick=()=>{managementPage--;managementComments();};
   if(E('mgNext'))E('mgNext').onclick=()=>{managementPage++;managementComments();};
   if(E('mgFullCorpusReference')?.open)showManagementTopicSynthesis();
   if(E('mgFormAudit')?.open)await v107Render();
 }catch(err){if(ticket===resultsReq)E('mgFilteredSummary').textContent='Could not load filtered analysis: '+err.message;}
}
// Replace the former per-tab management wrapper, including initial tab loads.
window.managementComments=managementComments;
window.addEventListener('DOMContentLoaded',()=>{
 setup();
 const reload=async(sectionChanged=false)=>{
   managementPage=1;
   if(sectionChanged){
     E('mgQuestionnaire').value='';
     await renderManagement();
   }
   await refreshFacets(false);
   await managementComments();
 };
 E('mgSection').onchange=()=>reload(true);
 for(const id of ['mgTheme','mgTopic','mgTopicCompare','mgContent','mgTier','mgFormFlag','mgQuestionnaire']){
   E(id).onchange=()=>reload();
 }
 E('mgApply').onclick=()=>reload();
 E('mgQuery').onkeydown=event=>{if(event.key==='Enter')reload();};
 E('mgReset').onclick=()=>{
    E('mgSection').value='summary';E('mgTheme').value='';E('mgTopic').value='';
    E('mgTopicCompare').value='';E('mgContent').value='';E('mgTier').value='any';
    E('mgFormFlag').value='all';E('mgQuery').value='';E('mgQuestionnaire').value='';
    reload(true);
 };
 E('mgDownloadCSV').onclick=()=>{location.href='/api/management/export?'+params(sourceState());};
 E('v107Export').onclick=()=>{location.href='/api/v107/export?'+params({...sourceState(),form_mode:E('mgAuditMode').value});};
 const timer=setInterval(()=>{
    if(managementState?.ready){clearInterval(timer);if(isManagement())refreshFacets(false);}
 },120);
 setTimeout(()=>clearInterval(timer),12000);
});
})();