/* V10.7 feedback UI: public read-only; all filtering handled server-side. */
sections.feedback=['FORM-LETTER ANALYSIS','Find recurring submissions without losing distinctive concerns.','Exact duplicates, approximate clusters and personalized variants; source-linked and provisional.'];
function v107Params(){
  return {form_mode:$('v107Mode')?.value||'all',v107_topic:$('v107Topic')?.value||'',
          v107_tier:$('v107Tier')?.value||'any',v107_content:$('v107Content')?.value||''};
}
function v107QueryParams(extra={}){
  return new URLSearchParams({...v107Params(),...extra}).toString();
}
function v107Line(label,note,count){
  return '<div class="management-rule-row"><strong>'+esc(label)+'</strong><span>'+esc(note||'')+'</span><small>'+number(count)+' displayed units</small></div>';
}
function v107Metric(label,count){
  return '<div class="metric"><span>'+esc(label)+'</span><strong>'+number(count)+'</strong></div>';
}
let v107Ready=false,v107RequestId=0;
async function v107Render(){
  const n=++v107RequestId;
  try{
    const d=await api('/api/v107/stats?'+v107QueryParams());
    if(n!==v107RequestId)return;
    $('v107Stats').innerHTML=[
      v107Metric('Public comments received in frozen snapshot',d.public_comment_submissions),
      v107Metric('Matching submissions before cluster mode',d.matching_before_form_mode),
      v107Metric('Displayed records or representatives',d.displayed_units),
      v107Metric('Text clusters represented',d.approximate_clusters_in_filtered_submissions)
    ].join('');
    $('v107Explanation').textContent=d.explanation+' '+d.narrative_scope;
    $('v107Topics').innerHTML=d.topics.map(x=>v107Line(x.label,'Primary '+number(x.primary)+'; secondary '+number(x.secondary)+' · primary sources: '+x.example_ids.join(', '),x.primary+x.secondary)).join('');
    $('v107Contents').innerHTML=d.content_subcategories.map(x=>v107Line(x.label,'Rule-screened; review ambiguous requests against questionnaire history',x.count)).join('');
    $('v107Distinctive').innerHTML=d.topics.filter(x=>x.primary_apparently_unique>0).sort((a,b)=>a.primary_apparently_unique-b.primary_apparently_unique).slice(0,12).map(x=>
      '<article class="comment-card"><div class="comment-title">'+esc(x.label)+'</div>'+
      '<div class="comment-meta">'+number(x.primary_apparently_unique)+' apparently unique · '+number(x.primary_clustered)+' repeated-cluster units with PRIMARY concern</div>'+
      '<p class="footnote">'+esc(x.contrast_note)+'</p>'+
      (x.distinctive_sources||[]).map(v=>'<div class="management-argument"><button type="button" class="tag open-detail" data-id="'+esc(v.comment_id)+'">'+esc(v.comment_id)+' ↗</button><p>'+esc(v.excerpt)+'</p></div>').join('')+
      '</article>').join('')||'No apparently unique screened primary concerns in this selection.';
    $('v107Clusters').innerHTML=d.top_clusters.length?d.top_clusters.map(x=>
      '<article class="comment-card"><div class="comment-title">Cluster '+esc(x.cluster_id)+'</div>'+
      '<div class="comment-meta">'+number(x.total_cluster_size)+' full-corpus members · '+number(x.matching_submissions)+' match current filters</div>'+
      '<p class="footnote">Personalized copies: '+number(x.personalized_ids.length)+' shown (up to 8); inspect text before dropping distinct recommendations.</p>'+
      '<div class="tags">'+x.sample_ids.map(cid=>'<button type="button" class="tag open-detail" data-id="'+esc(cid)+'">'+esc(cid)+' ↗</button>').join('')+'</div>'+
      (x.personalized_ids.length?'<p class="footnote">Variants: '+x.personalized_ids.map(cid=>'<button type="button" class="tag open-detail" data-id="'+esc(cid)+'">'+esc(cid)+'</button>').join(' ')+'</p>':'')+'</article>'
    ).join(''):'No repeated clusters in this filtered view.';
    $('v107FilterStatus').textContent=
      'Showing '+number(d.displayed_units)+' units from '+number(d.matching_before_form_mode)+
      ' matching public submissions; the original frozen corpus remains 3,748. '+d.narrative_scope;
  }catch(e){$('v107Explanation').textContent='V10.7 filter analysis unavailable: '+e.message;}
}
async function v107RefreshThemeCounts(){
  try{
    const d=await api('/api/themes?'+v107QueryParams());
    if(d.themes&&Array.isArray(d.themes)){themes=d.themes;renderThemeRows();}
  }catch(e){msg('Cannot recalculate filtered topic counts: '+e.message,true);}
}
function v107Changed(){
  runQuery(1);loadExplorer(1);
  if(managementState?.ready){managementPage=1;managementComments();}
  v107RefreshThemeCounts();v107Render();
}
const v107OriginalDetail=openDetail;
openDetail=async function(cid){
  await v107OriginalDetail(cid);
  try{
    const r=await api('/api/comment/'+encodeURIComponent(cid)),x=r.v107;
    if(!x||!$('commentDialog').open)return;
    const group=x.form_status.replaceAll('_',' ');
    const topics=Object.entries(x.topics||{}).map(([id,t])=>
      '<span class="tag">'+esc(t.role.toUpperCase())+': '+esc(t.label)+'</span>').join('');
    const support=x.support_specific_measure?
      ' · Specific-measure support: '+esc(x.support_specific_measure)+(x.support_specific_measure==='review'?' (review before counting as confirmed)':''):'';
    $('detailBody').insertAdjacentHTML('afterbegin',
      '<div class="banner info"><strong>V10.7: '+esc(group)+'</strong>'+
      '<p>Cluster '+esc(x.cluster_id)+' · '+number(x.cluster_size)+' source submissions · overlap '+number(Math.round(x.overlap*100))+'% · novel five-word phrases '+number(x.novel_words)+support+'</p>'+
      '<div class="tags">'+topics+'</div>'+
      '<p class="footnote">Content classifications: '+esc(x.content_subcategories.join(' | ')||'None screened')+
      ' · '+esc(x.method)+(x.needs_review?' · Flagged for review':'')+'</p></div>');
  }catch(e){/* Original source detail remains available when additive annotation cannot load. */}
};
// Management historical narratives stay frozen; only the following source evidence is filtered.
const v107BaseManagementComments=managementComments;
let v107ManagementSignalsReq=0;
managementComments=async function(){
  const n=++v107ManagementSignalsReq;
  await v107BaseManagementComments();
  const section=$('mgSection').value,theme=$('mgTheme').value;
  const message=section==='support'
    ? 'The V10.6 support narrative and 240 original intersections exclude newly screened support for a specific measure. V10.7 filtered record counts below may include measure-specific support; ambiguous statements remain flagged for human review.'
    : 'V10.6 section and category × theme prose covers the original full cohort. Changing form-letter, topic, or search filters DOES NOT regenerate those legacy narratives or their cited counts.';
  $('v107ManagementScope').textContent=message;
  try{
    const q=urlParams({...v107Params(),section,theme,q:$('mgQuery').value,questionnaire:section==='questionnaire'?$('mgQuestionnaire').value:''});
    const d=await api('/api/v107/stats?'+q);
    if(n!==v107ManagementSignalsReq)return;
    $('v107ManagementSignals').innerHTML=d.topics.filter(x=>x.primary>0||x.secondary>0).sort((a,b)=>b.primary-a.primary).slice(0,15).map(t=>
      '<div class="management-rule-row"><strong>'+esc(t.label)+'</strong><span>'+
      'Primary '+number(t.primary)+' (apparently unique '+number(t.primary_apparently_unique)+
      '; repeated-cluster units '+number(t.primary_clustered)+'); incidental '+number(t.secondary)+
      '. Examples: '+esc(t.example_ids.join(', '))+'</span></div>').join('')
      ||'<p>No additional-topic rule matches in this view.</p>';
  }catch(e){if(n===v107ManagementSignalsReq)$('v107ManagementSignals').textContent='Filtered signals unavailable: '+e.message;}
};
document.addEventListener('DOMContentLoaded',()=>{
  const controls=['v107Mode','v107Topic','v107Tier','v107Content'];
  for(const k of controls)$(k).onchange=v107Changed;
  $('v107Export').onclick=()=>{
    const mgActive=!$('tab-management').classList.contains('hide');
    const extra=mgActive?{section:$('mgSection').value,theme:$('mgTheme').value,q:$('mgQuery').value,
        questionnaire:$('mgQuestionnaire').value}:
        {q:$('explorerQ').value,theme:$('explorerTheme').value,match:$('explorerMode').value};
    window.location.href='/api/v107/export?'+v107QueryParams(extra);
  };
  api('/api/v107/stats?form_mode=all').then(d=>{
    const topic=$('v107Topic');
    topic.innerHTML='<option value="">All additional topics</option>'+d.topics.map(t=>
      '<option value="'+esc(t.id)+'">'+esc(t.label)+'</option>').join('');
    const content=$('v107Content');
    content.innerHTML='<option value="">All Content subcategories</option>'+d.content_subcategories.map(t=>
      '<option value="'+esc(t.id)+'">'+esc(t.label)+'</option>').join('');
    v107Ready=true;
    v107Render();
  }).catch(e=>{$('v107FilterStatus').textContent='Could not load V10.7 rules: '+e.message;});
});
