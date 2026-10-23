/* Consolidated Management Synthesis filters. All reports are read-only. */
(function(){
'use strict';
const e=id=>document.getElementById(id);
const active=()=>!e('tab-management').classList.contains('hide');
const oldParams=v107Params;
v107Params=function(){
  if(!active())return oldParams();
  const pick=e('mgTheme').value, newer=pick.startsWith('v108__');
  return {form_mode:e('mgFormMode').value||'all',v107_topic:newer?pick.slice(6):'',
    v107_tier:newer?e('mgTier').value:'any',
    v107_content:e('mgSection').value==='content'?e('mgContent').value:''};
};
const oldTab=showTab;
showTab=function(tab){
  oldTab(tab);
  e('v107GlobalPanel').classList.toggle('hide',tab!=='feedback');
  if(tab==='management'){prepareHistorical();refreshOptions(false);}
};
let prepared=false,facetReq=0,summaryReq=0;
function prepareHistorical(){
  if(prepared)return;
  prepared=true;
  const panel=e('mgNarrative').closest('article.panel');
  const dynamic=document.createElement('div');
  dynamic.id='mgFilteredSummary';
  dynamic.className='management-argument';
  dynamic.textContent='Filtered analysis loading…';
  panel.insertBefore(dynamic,e('mgComboSummary'));
  const history=document.createElement('details');
  history.id='mgHistoricalReference';
  history.className='management-rules';
  const head=document.createElement('summary');
  head.textContent='Original V10.6 syntheses and Word reports — UNFILTERED reference (expand)';
  history.appendChild(head);
  const info=document.createElement('p');
  info.className='footnote';
  info.textContent='The reports, original category prose, saved theme intersections, and their citations DO NOT reflect the active selections. They describe the frozen original full cohorts.';
  history.appendChild(info);
  for(const id of ['mgComboSummary','mgNarrative','mgRuleDetails','mgCitations','mgCompiledArguments',
                   'mgRepeatedGroups','mgTopics','v107ManagementScope','v107ManagementSignals',
                   'mgDownloadWord','mgDownloadCodedCSV','mgDownloadTopicCSV','mgDownloadTopicWord']){
    const item=e(id);if(item)history.appendChild(item);
  }
  panel.insertBefore(history,dynamic.nextSibling);
  const css=document.createElement('style');
  css.textContent='#mgIntegratedFilters label{min-width:195px;flex:1}#mgIntegratedFilters label.isHidden{display:none}'+
    '#mgFilteredSummary{margin:12px 0 18px;padding:14px;border:1px solid #d7dde5;border-radius:8px}'+
    '#mgFilteredSummary .mgFacts{display:flex;flex-wrap:wrap;gap:22px;margin:12px 0}'+
    '#mgFilteredSummary .mgFacts strong{font-size:1.45em}#mgHistoricalReference{margin:14px 0}'+
    '#mgHistoricalReference>button{margin:4px}';
  document.head.appendChild(css);
}
function state(){
  const topic=e('mgTheme').value;
  return {section:e('mgSection').value,theme:topic,
    form_mode:e('mgFormMode').value,v107_topic:topic.startsWith('v108__')?topic.slice(6):'',
    v107_tier:topic.startsWith('v108__')?e('mgTier').value:'any',
    v107_content:e('mgSection').value==='content'?e('mgContent').value:'',
    q:e('mgQuery').value.trim(),
    questionnaire:e('mgSection').value==='questionnaire'?e('mgQuestionnaire').value:''};
}
function fillChoices(select,base,items,selected){
  select.innerHTML='';
  select.appendChild(new Option(base,''));
  for(const item of items)select.appendChild(new Option(item.label+' ('+item.count+')',item.id));
  const found=items.some(x=>x.id===selected);
  select.value=found?selected:'';
  return selected&&!found;
}
async function refreshOptions(refresh=true){
  if(!active()||!managementState?.ready)return;
  const id=++facetReq,prior=state();
  try{
    const r=await api('/api/v108/management-options?'+new URLSearchParams(prior));
    if(id!==facetReq||!active())return;
    const content=e('mgContent'),selectedContent=prior.v107_content;
    const showContent=prior.section==='content';
    content.closest('label').classList.toggle('isHidden',!showContent);
    const resetContent=fillChoices(content,'All recommendation types',
      r.recommendation_types,showContent?selectedContent:'');
    const topic=e('mgTheme'),priorTheme=prior.theme;
    topic.innerHTML='';
    topic.appendChild(new Option('All topics / measures',''));
    for(const kind of ['legacy','additional']){
      const entries=r.topics.filter(x=>x.kind===kind).sort((a,b)=>a.label.localeCompare(b.label));
      if(!entries.length)continue;
      const group=document.createElement('optgroup');
      group.label=kind==='legacy'?'Original AI themes':'Additional management topics';
      for(const item of entries){
        group.appendChild(new Option(item.label+' ('+item.count+')',
          kind==='additional'?'v108__'+item.id:item.id));
      }
      topic.appendChild(group);
    }
    const allowed=r.topics.some(x=>(x.kind==='additional'?'v108__'+x.id:x.id)===priorTheme);
    topic.value=allowed?priorTheme:'';
    const role=e('mgTier'),added=topic.value.startsWith('v108__');
    role.closest('label').classList.toggle('isHidden',!added);
    role.innerHTML='';
    role.appendChild(new Option('All topic mentions','any'));
    if(added)for(const x of r.topic_roles)role.appendChild(new Option(x.label+' ('+x.count+')',x.id));
    role.value=added&&r.topic_roles.some(x=>x.id===prior.v107_tier)?prior.v107_tier:'any';
    const changed=Boolean(resetContent||(!allowed&&priorTheme)||(added&&prior.v107_tier!==role.value));
    e('mgIntegratedContext').textContent='Only relevant options shown. All available in every selector. '+
      r.matching_display_units+' displayed units from '+r.matching_submissions+
      ' matching submissions. The filtered CSV uses the exact same choices.';
    if(changed&&refresh){managementPage=1;managementComments();}
  }catch(err){if(id===facetReq)e('mgIntegratedContext').textContent='Filter options unavailable: '+err.message;}
}
const originalManagement=managementComments;
managementComments=async function(){
  if(!active())return originalManagement();
  prepareHistorical();
  const id=++summaryReq,query=state();
  await originalManagement();
  if(id!==summaryReq||!active())return;
  try{
    const [d,list]=await Promise.all([
      api('/api/v107/stats?'+new URLSearchParams(query)),
      api('/api/management/comments?'+new URLSearchParams({...query,page:1,size:5}))
    ]);
    if(id!==summaryReq||!active())return;
    const theme=e('mgTheme').selectedOptions[0]?.textContent||'All topics';
    const heading=e('mgSection').selectedOptions[0]?.textContent||'Management';
    const primary=d.topics.filter(x=>x.primary>0).sort((a,b)=>b.primary-a.primary).slice(0,7);
    const m=e('mgFilteredSummary');
    m.innerHTML='<h3>Current filtered evidence · '+esc(heading)+'</h3>'+
      '<div class="mgFacts"><div><strong>'+number(d.matching_before_form_mode)+'</strong><div>matching submissions</div></div>'+
      '<div><strong>'+number(d.displayed_units)+'</strong><div>displayed units</div></div>'+
      '<div><strong>'+number(d.approximate_clusters_in_filtered_submissions)+'</strong><div>approximate text groups</div></div></div>'+
      '<p>Topic: '+esc(theme.replace(/\s\(\d+\)$/,''))+'. '+
      'Form-letter mode: '+esc(e('mgFormMode').selectedOptions[0].textContent)+
      '. These are screen-based counts and source excerpts, not a new AI-written narrative or counts of people.</p>'+
      '<h4>Primary substantive topics in this selection</h4>'+
      (primary.length?primary.map(x=>'<p><strong>'+esc(x.label)+'</strong>: '+
        number(x.primary)+' primary, '+number(x.secondary)+' incidental; '+
        x.example_ids.slice(0,3).map(cid=>'<button class="tag open-detail" data-id="'+esc(cid)+'">'+esc(cid)+' ↗</button>').join(' ')+'</p>').join(''):
        '<p>No additional primary topic tags in this selection.</p>')+
      (query.section==='content'?'<h4>Content recommendation breakdown</h4>'+
        d.content_subcategories.filter(x=>x.count>0).map(x=>'<p>'+esc(x.label)+': '+number(x.count)+'</p>').join(''):'')+
      '<h4>Evidence from current matching comments</h4>'+
      (list.rows||[]).slice(0,4).map(r=>'<p><button class="tag open-detail" data-id="'+esc(r.comment_id)+'">'+
        esc(r.comment_id)+' ↗</button> '+esc(String(r.excerpt||'').slice(0,250))+'</p>').join('')+
      '<p class="footnote">Filtered analysis, matching records and filtered CSV use identical constraints. See collapsed historical section only for unfiltered legacy prose.</p>';
    e('mgNarrativeTitle').textContent='Management synthesis · filtered evidence';
    e('mgCount').textContent=number(d.displayed_units)+' displayed units from '+
      number(d.matching_before_form_mode)+' matching submissions';
  }catch(err){if(id===summaryReq)e('mgFilteredSummary').textContent='Filtered evidence unavailable: '+err.message;}
};
window.addEventListener('DOMContentLoaded',()=>{
  prepareHistorical();
  const apply=async(clear=false)=>{
    if(clear){e('mgTheme').value='';e('mgContent').value='';e('mgTier').value='any';}
    managementPage=1;
    await refreshOptions(false);
    await renderManagement();
    await refreshOptions(false);
  };
  e('mgSection').onchange=()=>apply(true);
  for(const id of ['mgTheme','mgContent','mgTier','mgFormMode','mgQuestionnaire']){
    e(id).onchange=()=>apply();
  }
  e('mgApply').onclick=()=>apply();
  e('mgQuery').onkeydown=event=>{if(event.key==='Enter')apply();};
  e('mgDownloadCSV').onclick=()=>{
    window.location.href='/api/management/export?'+new URLSearchParams(state());
  };
  const timer=setInterval(()=>{if(managementState?.ready){clearInterval(timer);refreshOptions(false);}},150);
  setTimeout(()=>clearInterval(timer),10000);
});
})();