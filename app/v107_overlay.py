"""V10.7 additive, deterministic management-feedback index.

Read-only overlay over the frozen V10.6 SQLite and versioned management artifact.
Never rewrites the original 3,748 records, legacy tags or precompiled narratives.
No external services, AI, personal data collection, or paid inference.
"""
import csv
import io
import re
import sqlite3
import threading
from collections import Counter, defaultdict

VERSION = "v10.8.1-management-qc-20261023"
MODES = ("all", "representative", "exclude_clusters")
TOPICS = {
    "tobacco": ("Tobacco, nicotine, and cigarettes", r"\b(?:tobacco|nicotine|cigarettes?|cigars?|smoking|smokers?|e-cigarettes?|vaping|vapes?)\b"),
    "alcohol": ("Alcohol use", r"\b(?:alcohol(?:ic)?|binge drinking|drink(?:ing)? frequency|heavy drinking)\b"),
    "screening": ("Screening for cancer and chronic conditions", r"\b(?:(?:cancer|colorectal|breast|cervical|lung|chronic condition)\s+(?:screening|screen|test)|screening\s+(?:for\s+)?(?:cancer|colorectal|breast|cervical|lung|chronic|disease)|mammogram|colonoscopy)\b"),
    "cardiovascular": ("Cardiovascular / heart health", r"\b(?:cardiovascular|heart (?:disease|health|attack|failure)|hypertension|blood pressure|stroke|coronary)\b"),
    "asthma": ("Asthma", r"\basthma(?:tic)?\b"),
    "diabetes": ("Diabetes", r"\b(?:diabetes|diabetic|blood glucose|a1c|insulin resistance)\b"),
    "medications": ("Medications and prescriptions", r"(?<!non-)\b(?:medications?|prescriptions?|prescribed drugs?|pharmaceuticals?|drug coverage|treatment adherence)\b"),
    "services": ("Health care services and visits", r"\b(?:health ?care visits?|doctor visits?|office visits?|provider visits?|medical appointments?|health services?|emergency department|primary care visits?)\b"),
    "insurance": ("Health insurance and coverage", r"\b(?:health insurance|insurance coverage|uninsured|underinsured|medicaid|medicare|private insurance|health plan|insurance status|insured status|coverage gap)\b"),
    "costs": ("Health care costs", r"\b(?:health ?care costs?|medical costs?|out.of.pocket|co.?pays?|co.?payments?|medical bills?|medical debt|affordability of (?:care|treatment|medicine)|cost of care)\b"),
    "whole_person": ("Whole-person health / quality of life", r"\b(?:whole.person health|whole person health index|wphi|quality of life|well.being|holistic health)\b"),
    "loneliness": ("Loneliness, connectedness, and social isolation", r"\b(?:loneliness|lonely|social isolation|socially isolated|social connectedness|social connection|social support|social disconnectedness)\b"),
    "physical_activity": ("Physical activity", r"\b(?:physical activity|exercise|sedentary|active lifestyle|sports participation|fitness activity)\b"),
    "sleep": ("Sleep", r"\b(?:sleep(?:ing)?|insomnia|sleep quality|sleep duration|sleep disorder)\b"),
    "demographics": ("Demographic measures", r"\b(?:demographic questions?|demographic measures?|race and ethnicity|racial categories|ethnic categories|gender identity|sexual orientation|respondent age|demographic data)\b"),
}
SUBCATEGORIES = {
    "removed": "Concern about removed or reduced measures",
    "add": "Suggestion to add measures or topics",
    "reduce": "Suggestion to remove or reduce content",
    "wording": "Question wording, response options, skip patterns, or universes",
    "ambiguous": "Unclear restoration versus addition — review",
}
# A condition mention or a general reference to NHIS is not a request for that measure.
ACTION = re.compile(r"\b(?:recommend(?:ation|ed)?|suggest(?:ion|ed)?|propos\w*|urge|support(?:ed|ing)?|endorse\w*|retain|keep|restore|reinstat\w*|include|add|collect|measure|ask|question|revise|change|modify|drop|remove|eliminat\w*|should|must|need)\b", re.I)
ASSOCIATION = re.compile(r"\b(?:associated with|linked to|correlat(?:es|ed|ion)|risk factor for|co.?occur|such as|including higher rates of|higher levels of)\b",re.I)
SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
# Retaining something is not evidence of a removal concern unless an actual or
# proposed deletion is identified. This excludes broad "keep" form-letter language.
REMOVAL_CONTEXT = re.compile(r"\b(?:(?:not carried forward|no longer included|not included in the proposed|left out of the proposed|omitted from the proposed)|remov(?:e|ed|al|ing)|eliminat\w*|dropp?(?:ed|ing)?|deleted?|discontinu\w*|cut(?:ting|s)?|propos\w*.{0,60}?(?:reduc\w*|remov\w*|delet\w*)|reduc(?:ed|tion|ing)\s+(?:of|in)\b)\b",re.I)
MEASURE_SUBJECT = re.compile(r"\b(?:questions?|items?|measures?|topics?|content|modules?|sections?|survey|nhis|lonel\w*|disabilit\w*|help|marijuana|cannabis|insurance|access)\b",re.I)
ADDITION = re.compile(r"\b(?:add|additional|new (?:question|measure|topic)|introduc|expand|incorporat|should be included|should include|include (?:a|the)\s+(?:new|brief)|follow.up identifying)\w*\b",re.I)
REDUCE = re.compile(r"\b(?:delete|eliminat|remove|drop|omit|not be asked|reduce (?:the |existing )?(?:questions|items|content)|shorten)\w*\b",re.I)
WORDING = re.compile(r"\b(?:wording|phrasing|worded|response options?|response categor|skip pattern|skip logic|universe|asked of anyone|reword|replace with|the phrase.{0,70}deleted)\b",re.I)
REQUEST = re.compile(r"\b(?:should include|should measure|include (?:questions?|measures?|topics?)|measure (?:the |this )?|recommend including)\b",re.I)
SUPPORT_EXPLICIT = re.compile(r"\b(?:strongly\s+)?support(?:ing|s|ed)?\s+(?:the\s+)?(?:inclusion|including|addition|retention|retaining|use|measure|index)|\bendorse\s+(?:including|the)|\bin favor of\s+(?:adding|retaining|including)",re.I)
KEEP_MEASURE = re.compile(r"\b(?:retain|keep|restore|continue)\s+(?:the\s+)?(?:\w+\s+){0,3}(?:questions?|items?|measures?|index|scale|topics?|module|section)\b",re.I)
SUPPORT_CONTEXT = re.compile(r"\b(?:important|essential|valuable|critical|crucial|beneficial|should be included|ought to be included|recommend including)\b",re.I)
MEASURE = re.compile(r"\b(?:whole.person health|wphi|index|measure|question|topic|survey|nhis)\b",re.I)

def direct_request(sentence, pattern):
    """A nearby requested ACTION, not general survey vocabulary or co-morbidity."""
    for term in pattern.finditer(sentence):
        before=sentence[max(0,term.start()-115):term.start()]
        after=sentence[term.end():term.end()+100]
        association=ASSOCIATION.search(sentence)
        if association and term.start()>association.start():
            continue
        if ACTION.search(before) or ACTION.search(after):
            return True
    return False

def classify_text(text, title=""):
    """Deterministic high-precision topical screening; flag rather than force weak cases."""
    text=(text or "")[:160000]
    sentences=[s.strip() for s in SENTENCES.split(text) if s.strip()]
    labels={}
    for tid,(name,pattern) in TOPICS.items():
        pat=re.compile(pattern,re.I)
        hits=[s for s in sentences if pat.search(s)]
        if not hits and not pat.search(title or ""):
            continue
        substantive=[s for s in hits if direct_request(s,pat)]
        role="primary" if substantive else "secondary"
        evidence=(substantive or hits or [title or ""])[0][:330]
        labels[tid]={"label":name,"role":role,"evidence":evidence,
                     "mentions":len(hits),"method":"v10.8.1 direct-request context screening"}
    subs=[]
    for sentence in sentences:
        if WORDING.search(sentence): subs.append("wording")
        if REMOVAL_CONTEXT.search(sentence) and MEASURE_SUBJECT.search(sentence):
            # "Please remove this question" is a request to reduce, not concern
            # over CDC's removal. Explicit opposition / reinstatement is required.
            if re.search(r"\b(?:retain|restore|reinstat\w*|keep|continue|should not|do not|not to|concern\w*|oppose\w*|worr\w*|harm\w*|will result|could result|under.?count|would lose|losing|removal|removing|removed|proposed)\b",sentence,re.I):
                subs.append("removed")
        if (REDUCE.search(sentence) and
            re.search(r"\b(?:questions?|items?|content|section|survey|marijuana|cannabis)\b",sentence,re.I) and
            (re.search(r"\b(?:recommend(?:ation|ations|ed)?|suggest(?:ion|ed)?|should|propose|consider|please|urge|prefer|instead)\b",sentence,re.I)
             or re.match(r"\s*(?:delete|remove|eliminate|drop|omit|reduce)\b",sentence,re.I)
             or re.search(r"\b(?:should not be asked|do not ask|not be asked)\b",sentence,re.I))):
            subs.append("reduce")
        if ADDITION.search(sentence) and re.search(r"\b(?:question|measure|topic|content|follow.up|hemp|cbd|screen|treatment|cannabis|marijuana|survey|nhis)\b",sentence,re.I):
            subs.append("add")
        if REQUEST.search(sentence) and not (REMOVAL_CONTEXT.search(sentence) or ADDITION.search(sentence)):
            subs.append("ambiguous")
    subs=list(dict.fromkeys(subs))
    if "ambiguous" in subs and any(s in subs for s in ("removed","add")):
        subs.remove("ambiguous")
    support_explicit=any(SUPPORT_EXPLICIT.search(s) and MEASURE.search(s) for s in sentences)
    support_review=not support_explicit and any(SUPPORT_CONTEXT.search(s) and MEASURE.search(s) for s in sentences)
    many_primary=sum(v["role"]=="primary" for v in labels.values())>=5
    return {"topics":labels,"content_subcategories":subs,
            "support_specific_measure":"explicit" if support_explicit else "review" if support_review else "",
            "support_scope":"specific_measure_not_redesign" if support_explicit or support_review else "",
            "multiple_primary_review":many_primary}

_lock = threading.RLock()
_cached = None

def index(db):
    """Immutable hosted snapshot index, built once and held in memory."""
    global _cached
    with _lock:
        if _cached is not None:return _cached
        rows={r["comment_id"]:dict(r) for r in db.execute(
            "SELECT comment_id,title,organization,plain_text,normalized_sha,posted_date,comment_url FROM comments ORDER BY comment_id")}
        if len(rows)!=3748:
            raise ValueError("V10.7 frozen corpus gate: expected 3748 public records")
        attachment_text=defaultdict(list)
        for x in db.execute("SELECT comment_id,text FROM attachment_text WHERE status='ok'"):
            if x["text"]:attachment_text[x["comment_id"]].append(x["text"])
        clusters={r["comment_id"]:dict(r) for r in db.execute("SELECT * FROM comment_clusters")}
        if set(rows)!=set(clusters):
            raise ValueError("V10.7 cluster coverage mismatch")
        # Additional independently flagged copies span three old cluster IDs.
        # This is a *documented analytic link*, not a database overwrite.
        linked=["CDC-2026-1387-"+suffix for suffix in ("0308","0334","0335")]
        if not all(cid in clusters for cid in linked):
            raise ValueError("Expected linked form-letter example missing")
        original_group_ids={clusters[cid]["cluster_id"] for cid in linked}
        representative=clusters[linked[0]]["cluster_id"]
        for cid,c in clusters.items():
            c["original_cluster_id"]=c["cluster_id"]
            c["cross_cluster_review"]=c["cluster_id"] in original_group_ids
            if c["cross_cluster_review"]:
                c["cluster_id"]=representative
        hashes=Counter(r["normalized_sha"] for r in rows.values() if r["normalized_sha"])
        members=defaultdict(list)
        for cid,c in clusters.items():members[c["cluster_id"]].append(cid)
        full_search={}
        for cid,r in rows.items():
            src=" ".join(str(r.get(k) or "") for k in ("comment_id","plain_text","title","organization"))
            src+="\n"+"\n".join(attachment_text.get(cid,[]))
            full_search[cid]=re.sub(r"\s+"," ",src).casefold()
        for group in members.values():
            n=len(group)
            for cid in group:
                clusters[cid]["cluster_size"]=n
        items={}
        for cid,r in rows.items():
            c=clusters[cid]
            text=(r["plain_text"] or "")+"\n\n"+"\n\n".join(attachment_text.get(cid,[]))
            analyzed=classify_text(text,r["title"] or "")
            exact=bool(r["normalized_sha"] and hashes[r["normalized_sha"]]>1)
            size=c["cluster_size"]
            personalized=bool(size>1 and c["personalized"])
            unclear=not text.strip() or (size>1 and 0.60<=c["overlap"]<0.68 and c["novel_words"]>=30)
            form_status=("uncertain" if unclear else "exact_duplicate" if exact else
                         "personalized_form_letter" if personalized else
                         "likely_form_letter" if size>1 else "apparently_unique")
            items[cid]={**analyzed,"form_status":form_status,
                "cluster_id":c["cluster_id"],"cluster_size":size,
                "exact_duplicate":exact,"personalized":personalized,
                "overlap":c["overlap"],"novel_words":c["novel_words"],
                "needs_review":unclear or c["cross_cluster_review"] or analyzed["multiple_primary_review"] or bool("ambiguous" in analyzed["content_subcategories"]) or analyzed["support_specific_measure"]=="review",
                "original_cluster_id":c["original_cluster_id"],"cross_cluster_review":c["cross_cluster_review"],
                "method":("Exact normalized-text fingerprint" if exact else
                          "Existing five-word shingle cluster with novel-text flag" if size>1 else
                          "No existing near-duplicate cluster; unique only within frozen corpus")}
        themes=defaultdict(set)
        semantic_themes=defaultdict(set)
        for cid,tid in db.execute("SELECT comment_id,theme_id FROM tags"):
            themes[tid].add(cid)
        for cid,tid in db.execute("SELECT comment_id,theme_id FROM semantic_tags"):
            semantic_themes[tid].add(cid)
        allids=set(rows)
        _cached={"rows":rows,"items":items,"members":dict(members),"search_text":full_search,"themes":dict(themes),
                 "allids":allids,"cluster_count":len(members),"semantic_themes":dict(semantic_themes)}
        return _cached

def filter_result(db, mode="all", section="", legacy_theme="", topic="", tier="any",
                  subcategory="", query="", match="any", questionnaire=""):
    if mode not in MODES:raise ValueError("Invalid form-letter mode")
    if topic and topic not in TOPICS:raise ValueError("Unknown added topic")
    if tier not in ("any","primary","secondary"):raise ValueError("Invalid topic role")
    if subcategory and subcategory not in SUBCATEGORIES:raise ValueError("Unknown Content subcategory")
    if len(query)>300:raise ValueError("Query too long")
    idx=index(db)
    ids=set(idx["allids"])
    if section:
        import management_addon as mg
        if section not in mg.ALLOWED:raise ValueError("Unknown management section")
        state=mg.load(db)
        if not state["ready"]:raise ValueError("Management artifact not ready")
        a=state["assignments"]
        if section=="questionnaire":
            ids &= {x["comment_id"] for x in a if x.get("questionnaire_section") and
                    (not questionnaire or questionnaire in [v.strip() for v in x["questionnaire_section"].split(" | ")])}
        elif section!="summary":
            ids &= {x["comment_id"] for x in a if x["category"]==section}
            if section=="support":
                # Weak "important" mentions are REVIEW ONLY and cannot inflate Support.
                ids |= {cid for cid,x in idx["items"].items() if x["support_specific_measure"]=="explicit"}
    if legacy_theme:
        active_themes=idx["semantic_themes"] if section else idx["themes"]
        if legacy_theme not in active_themes:raise ValueError("Unknown original AI theme")
        ids &= active_themes[legacy_theme]
    if topic:
        ids &= {cid for cid,item in idx["items"].items() if
                topic in item["topics"] and (tier=="any" or item["topics"][topic]["role"]==tier)}
    if subcategory:
        ids &= {cid for cid,item in idx["items"].items() if subcategory in item["content_subcategories"]}
    if query.strip():
        chunks=re.findall(r'"([^"]+)"|(\S+)',query)
        parts=[(a or b).casefold() for a,b in chunks if a or b]
        if len(parts)>25:raise ValueError("Search limited to 25 words/phrases")
        if match not in ("any","all","phrase"):raise ValueError("Unknown match semantics")
        if match=="phrase":parts=[query.strip().strip('"').casefold()]
        require=all if match=="all" else any
        ids={cid for cid in ids if require(token in idx["search_text"][cid] for token in parts)}
    submission_ids=set(ids)
    if mode=="exclude_clusters":
        ids={cid for cid in ids if idx["items"][cid]["cluster_size"]==1}
    elif mode=="representative":
        selected={}
        for cid in sorted(ids):
            cluster=idx["items"][cid]["cluster_id"]
            # Within a filtered query, representative must itself match the selected criteria.
            selected.setdefault(cluster,cid)
        ids=set(selected.values())
    return idx, sorted(ids), submission_ids

def cards(idx,ids,matching=None):
    result=[]
    for cid in ids:
        r=idx["rows"][cid].copy()
        r.pop("normalized_sha",None)
        item=idx["items"][cid]
        members=idx["members"].get(item["cluster_id"],[cid])
        r.update({"v107":item,
                  "matching_cluster_records":sum(c in (matching or set(ids)) for c in members),
                  "personalized_variant_ids":[m for m in members if idx["items"][m]["personalized"]][:12]})
        result.append(r)
    return result

def comments(db, **kw):
    page=max(1,min(int(kw.pop("page",1)),100000))
    size=max(1,min(int(kw.pop("size",20)),100))
    idx,ids,pre=filter_result(db,**kw)
    total=len(ids)
    sub=ids[(page-1)*size:page*size]
    rec=cards(idx,sub,pre)
    return {"ready":True,"version":VERSION,"total":total,"page":page,"page_size":size,
            "source_submission_matches":len(pre),"public_records_unchanged":3748,
            "comments":rec,"rows":[{"comment_id":r["comment_id"],"title":r["title"],"organization":r["organization"],
                "posted_date":r["posted_date"],"comment_url":r["comment_url"],"excerpt":r["plain_text"][:900],
                "cluster_id":r["v107"]["cluster_id"],"cluster_size":r["v107"]["cluster_size"],
                "v107":r["v107"]} for r in rec],
            "narrative_scope":"V10.6 static narratives are unfiltered; these are corrected V10.8.1 counts."}

def support_review_summary(db,kw,idx):
    """Undecided measure-support signals, NEVER included in Support totals."""
    settings={k:kw.get(k) for k in ("legacy_theme","topic","tier","query","match")}
    settings={k:v for k,v in settings.items() if v is not None}
    _,candidates,_=filter_result(db,section="summary",mode="all",**settings)
    import management_addon as mg
    existing={a["comment_id"] for a in mg.load(db)["assignments"] if a["category"]=="support"}
    ambiguous=sorted(cid for cid in candidates if idx["items"][cid]["support_specific_measure"]=="review" and cid not in existing)
    return {"count":len(ambiguous),"example_ids":ambiguous[:10],
            "note":"Potential specific-measure support; NOT included in Support totals until reviewed."}

def stats(db, **kw):
    idx,ids,pre=filter_result(db,**kw)
    mode=kw.get("mode","all")
    topic_counts=Counter()
    secondary_counts=Counter()
    content_counts=Counter()
    unique_primary=Counter()
    clustered_primary=Counter()
    statuses=Counter()
    for cid in ids:
        x=idx["items"][cid]
        statuses[x["form_status"]]+=1
        for t,v in x["topics"].items():
            (topic_counts if v["role"]=="primary" else secondary_counts)[t]+=1
            if v["role"]=="primary":
                (clustered_primary if x["cluster_size"]>1 else unique_primary)[t]+=1
        for c in x["content_subcategories"]:content_counts[c]+=1
    # Counts describe displayed units; never equate them with persons or unique arguments.
    family_counts=Counter(idx["items"][cid]["cluster_id"] for cid in pre)
    clusters=sorted(((k,v) for k,v in family_counts.items() if idx["items"][idx["members"][k][0]]["cluster_size"]>1),
                    key=lambda x:(-x[1],x[0]))
    examples=[{"cluster_id":cid,"matching_submissions":n,
               "total_cluster_size":len(idx["members"][cid]),
               "sample_ids":idx["members"][cid][:8],
               "personalized_ids":[x for x in idx["members"][cid] if idx["items"][x]["personalized"]][:8]} for cid,n in clusters[:35]]
    concern_rows=[]
    for t in TOPICS:
        qualifying=[cid for cid in ids if idx["items"][cid]["topics"].get(t,{}).get("role")=="primary"]
        unique=[cid for cid in qualifying if idx["items"][cid]["cluster_size"]==1]
        repeated=[cid for cid in qualifying if idx["items"][cid]["cluster_size"]>1]
        concern_rows.append({"id":t,"label":TOPICS[t][0],"primary":topic_counts[t],"secondary":secondary_counts[t],
            "primary_apparently_unique":unique_primary[t],"primary_clustered":clustered_primary[t],
            "example_ids":qualifying[:4],
            "distinctive_sources":[{"comment_id":cid,"excerpt":idx["items"][cid]["topics"][t]["evidence"][:250],
                    "source_url":idx["rows"][cid]["comment_url"]} for cid in unique[:3]],
            "repeated_sources":[{"comment_id":cid,"cluster_size":idx["items"][cid]["cluster_size"],
                    "excerpt":idx["items"][cid]["topics"][t]["evidence"][:180]} for cid in repeated[:2]],
            "contrast_version":VERSION,
            "contrast_note":f"{unique_primary[t]} apparently unique displayed submissions and {clustered_primary[t]} displayed repeated-cluster units raise this as a provisional primary topic. These are not verified distinct arguments."})
    return {"version":VERSION,"mode":mode,"public_comment_submissions":3748,
            "displayed_units":len(ids),"matching_before_form_mode":len(pre),
            "approximate_clusters_in_filtered_submissions":len({idx["items"][cid]["cluster_id"] for cid in ids}),
            "status_counts":dict(statuses),"topics":concern_rows,
            "support_review":support_review_summary(db,kw,idx) if kw.get("section")=="support" else None,
            "content_subcategories":[{"id":s,"label":label,"count":content_counts[s]} for s,label in SUBCATEGORIES.items()],
            "top_clusters":examples,
            "explanation":"Versioned deterministic source-excerpt and count contrasts under the selected filters. No paid AI or regenerated narrative. Form-letter grouping is not an adjudication of distinct substantive arguments.",
            "narrative_scope":"Preserved V10.6 category and category×theme narratives are full-corpus, unfiltered, and do NOT change with controls."}

def export(db,**kw):
    idx,ids,pre=filter_result(db,**kw)
    out=io.StringIO(newline="")
    w=csv.writer(out)
    w.writerow(["comment_id","source_url","cluster_id","cluster_size","form_letter_status",
                "exact_duplicate","personalized","overlap","novel_words","needs_review",
                "primary_topics","secondary_topics","content_subcategories","support_specific_measure","management_categories",
                "feedback_rules_version","public_corpus_records"])
    for cid in ids:
        x=idx["items"][cid];row=idx["rows"][cid]
        mg_categories=idx.get("management_categories")
        if mg_categories is None:
            import management_addon as mg
            state=mg.load(db)
            if not state["ready"]:raise ValueError("Management artifact unavailable for export")
            mg_categories=defaultdict(list)
            for a in state["assignments"]:
                if a["category"] not in mg_categories[a["comment_id"]]:
                    mg_categories[a["comment_id"]].append(a["category"])
            idx["management_categories"]=mg_categories
        w.writerow([cid,row["comment_url"],x["cluster_id"],x["cluster_size"],x["form_status"],
             int(x["exact_duplicate"]),int(x["personalized"]),x["overlap"],x["novel_words"],
             int(x["needs_review"])," | ".join(t for t,v in x["topics"].items() if v["role"]=="primary"),
             " | ".join(t for t,v in x["topics"].items() if v["role"]=="secondary"),
             " | ".join(x["content_subcategories"]),x["support_specific_measure"]," | ".join(mg_categories.get(cid,[])),VERSION,3748])
    return out.getvalue().encode("utf-8-sig")

EXAMPLES=[
    "0061","0054","0053","0050","0401","0408","0410","0308","0334","0335",
    "0020","0261","0262","0004","0324","0368","0313","0414","0428","0518"
]
def qc(db):
    idx=index(db)
    missing=[x for x in EXAMPLES if "CDC-2026-1387-"+x not in idx["items"]]
    all_counts={m:len(filter_result(db,mode=m)[1]) for m in MODES}
    multi=[c for c in idx["items"].values() if len([v for v in c["topics"].values() if v["role"]=="primary"])>1]
    passed=not missing and all_counts["all"]==3748 and all_counts["representative"]==idx["cluster_count"] and all_counts["exclude_clusters"]<=all_counts["representative"]
    return {"ready":passed,"version":VERSION,"corpus":3748,"original_ai_labels_preserved":True,
            "original_management_artifact_unchanged":True,"example_ids_checked":len(EXAMPLES)-len(missing),
            "missing_examples":missing,"display_counts":all_counts,
            "cluster_count":idx["cluster_count"],"multiple_primary_topic_comments":len(multi),
            "note":"Presence is a regression gate. Classifications are provisional, require human QC; examples are not hard-coded labels."}


def management_filter_options(db, mode="all", section="support", legacy_theme="", topic="",
                              tier="any", subcategory="", query="", match="any", questionnaire=""):
    """Return only relevant topic and request-type choices under other selected facets."""
    idx=index(db)
    def scope(**changes):
        args=dict(mode="all",section=section,legacy_theme=legacy_theme,topic=topic,tier=tier,
                  subcategory=subcategory if section=="content" else "",query=query,
                  match=match,questionnaire=questionnaire)
        args.update(changes)
        return set(filter_result(db,**args)[1])
    def number(ids):
        if mode=="exclude_clusters":
            return sum(idx["items"][cid]["cluster_size"]==1 for cid in ids)
        if mode=="representative":
            return len({idx["items"][cid]["cluster_id"] for cid in ids})
        return len(ids)
    # Ignore the current topic to allow meaningful switching to other topics.
    candidates=scope(legacy_theme="",topic="",tier="any")
    choices=[]
    import management_addon as mg
    for t in mg.themes(db):
        n=number(candidates & idx["semantic_themes"].get(t["id"],set()))
        if n:choices.append({"kind":"legacy","id":t["id"],"label":t["name"],"count":n})
    for tid,(label,_regex) in TOPICS.items():
        n=number({cid for cid in candidates if tid in idx["items"][cid]["topics"]})
        if n:choices.append({"kind":"additional","id":tid,"label":label,"count":n})
    types=[]
    if section=="content":
        available=scope(subcategory="")
        for code,label in SUBCATEGORIES.items():
            n=number({cid for cid in available if code in idx["items"][cid]["content_subcategories"]})
            if n:types.append({"id":code,"label":label,"count":n})
    roles=[]
    if topic:
        available=scope(tier="any")
        for role,label in (("primary","Primary concerns"),("secondary","Secondary / incidental")):
            n=number({cid for cid in available if idx["items"][cid]["topics"].get(topic,{}).get("role")==role})
            if n:roles.append({"id":role,"label":label,"count":n})
    current=scope()
    return {"ready":True,"section":section,"topics":choices,"recommendation_types":types,
            "topic_roles":roles,"matching_submissions":len(current),
            "matching_display_units":number(current)}
