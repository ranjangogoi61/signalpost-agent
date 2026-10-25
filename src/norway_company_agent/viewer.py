"""Single-file, offline HTML viewer for Signalpost envelopes (find, compare, verify)."""
from __future__ import annotations

import copy
import json
from typing import Any

FIELDS = ["legal_name", "legal_form", "legal_status", "business_address", "founded", "municipality", "industry", "employees", "financials_latest", "annual_account_years", "job_postings", "role_holders", "registered_locations", "official_website"]


def slim(envelope: dict[str, Any], hide_person_names: bool) -> dict[str, Any]:
    claims = copy.deepcopy(envelope.get("claims", []))
    for claim in claims:
        if hide_person_names and claim["field"] == "role_holders" and isinstance(claim.get("value"), list):
            claim["value"] = [{"role": r.get("role"), "name": "(name omitted in this public demo)"} for r in claim["value"]]
    name = next((c["value"] for c in claims if c["field"] == "legal_name" and c.get("value")), None)
    return {
        "org": envelope.get("organisation_number"),
        "name": name or "(not found)",
        "state": envelope.get("state"),
        "modules": {k: v.get("availability") for k, v in (envelope.get("modules") or {}).items()},
        "claims": claims,
        "evidence": envelope.get("evidence", []),
        "synthesis": envelope.get("synthesis") or {"sentences": [], "unknown": []},
        "changes": envelope.get("changes", []),
        "errors": envelope.get("errors", []),
        "refresh": envelope.get("refresh") or {},
    }


def build_viewer(envelopes: list[dict[str, Any]], report: dict[str, Any] | None = None, *, hide_person_names: bool = False, title: str = "Signalpost company profiles") -> str:
    data = {
        "title": title,
        "run": {
            "run_id": (report or {}).get("run_id") or (envelopes[0].get("run", {}).get("run_id") if envelopes else ""),
            "generated_from": len(envelopes),
            "availability_totals": (report or {}).get("availability_totals", {}),
        },
        "fields": FIELDS,
        "companies": [slim(e, hide_person_names) for e in envelopes],
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    return TEMPLATE.replace("__TITLE__", title.replace("<", "&lt;")).replace("__DATA__", payload)


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f3f5f9;--card:#fff;--ink:#121826;--muted:#4b5668;--line:#d9dfe8;--accent:#1d4ed8;--accent-ink:#fff;--ok:#0b6b3a;--okbg:#e6f4ec;--warn:#8a5a00;--warnbg:#fff3d6;--bad:#9b1c1c;--badbg:#fde8e8;--grey:#4b5668;--greybg:#eef1f5;--shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.08)}
@media (prefers-color-scheme:dark){:root{--bg:#0d1118;--card:#171c26;--ink:#eef1f6;--muted:#b3bccb;--line:#2b3445;--accent:#8fb0ff;--accent-ink:#0d1118;--ok:#7be0a8;--okbg:#12301f;--warn:#f2c76f;--warnbg:#38290a;--bad:#ff9c9c;--badbg:#3a1616;--grey:#b3bccb;--greybg:#222a38;--shadow:none}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}body{margin:0;font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:var(--accent)}h1{font-size:1.35rem;margin:0}h2{font-size:1.2rem;margin:0 0 4px}h3{font-size:1rem;margin:0 0 8px}
header.top{background:linear-gradient(135deg,#102a6b,#1d4ed8);color:#fff;padding:18px 16px 14px}
header.top .sub{opacity:.9;font-size:.92rem;margin-top:2px}header.top details{margin-top:8px;font-size:.88rem}header.top summary{color:#fff;opacity:.95}header.top #legend{margin-top:6px;opacity:.95}
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:12px 16px 0}
@media (min-width:700px){.stats{grid-template-columns:repeat(5,minmax(0,1fr))}}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;box-shadow:var(--shadow)}.stat b{display:block;font-size:1.4rem;line-height:1.2}.stat span{font-size:.82rem;color:var(--muted)}
.bar{display:flex;flex-wrap:wrap;gap:8px;padding:12px 16px;align-items:center}.bar label{font-size:.85rem;color:var(--muted)}
input,select,button{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-height:44px}
input[type=search]{flex:1 1 220px}button{cursor:pointer}button.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:600}button.ghost{background:transparent}
button:hover{filter:brightness(.97)}:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
main{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;padding:0 16px 24px}main>section{min-width:0}
@media (min-width:900px){main{grid-template-columns:minmax(320px,400px) minmax(0,1fr);align-items:start}#list{max-height:calc(100vh - 120px);overflow:auto;position:sticky;top:8px;padding-right:4px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:0 0 10px;box-shadow:var(--shadow);min-width:0}
.cardtop{display:flex;gap:8px;justify-content:space-between;align-items:flex-start}.name{font-weight:650}.meta{color:var(--muted);font-size:.88rem}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0}.lbl{font-size:.8rem;color:var(--muted)}
.badge{display:inline-flex;align-items:center;gap:2px;border-radius:999px;padding:1px 9px;font-size:.78rem;font-weight:600;white-space:nowrap;border:1px solid currentColor}
.badge.available{color:var(--ok);background:var(--okbg)}.badge.not_available,.badge.not_applicable{color:var(--grey);background:var(--greybg)}.badge.ambiguous,.badge.blocked{color:var(--warn);background:var(--warnbg)}.badge.failed{color:var(--bad);background:var(--badbg)}
.prog{height:6px;border-radius:99px;background:var(--greybg);overflow:hidden;margin:6px 0 2px}.prog i{display:block;height:100%;background:var(--accent)}
.chk{display:inline-flex;padding:11px;margin:-11px -11px 0 0;cursor:pointer}.sel{outline:2px solid var(--accent)}.openbtn{width:100%;margin-top:6px}.more{width:100%;margin:2px 0 12px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}@media (max-width:480px){.tabs button{flex:1 1 auto;padding-left:10px;padding-right:10px}}.tabs button{border-radius:999px;white-space:nowrap}.tabs button[aria-selected=true]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:600}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.actions button,.actions a{min-height:40px;padding:8px 12px;font-size:.9rem;display:inline-flex;align-items:center;text-decoration:none;border:1px solid var(--line);border-radius:10px;color:var(--ink);background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:.93rem}th,td{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600;font-size:.82rem;text-transform:uppercase;letter-spacing:.03em}
.scroll{overflow-x:auto}details{margin:4px 0}summary{cursor:pointer;color:var(--accent)}code{word-break:break-all;font-size:.82rem}
.sent{margin:0 0 10px}.src{font-size:.86rem;color:var(--muted)}.empty{color:var(--muted);padding:18px;text-align:center}.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;background:var(--card);padding:8px;z-index:9}.back{display:none}
@media (max-width:899px){.back{display:inline-block;margin-bottom:8px}}
@media (max-width:700px){table.facts thead{display:none}table.facts tr{display:block;border-bottom:1px solid var(--line);padding:8px 0}table.facts td{display:block;border:0;padding:2px 0}table.facts td:first-child{font-weight:650}}
@media print{header.top,.stats,.bar,#list,.tabs,.actions{display:none}main{display:block}.card{box-shadow:none;break-inside:avoid}[hidden]{display:block!important}}
</style>
</head>
<body>
<a class="skip" href="#detail">Skip to company details</a>
<header class="top"><h1 id="title"></h1><div class="sub">Evidence-first company profiles from Norwegian organisation numbers</div><div class="sub" id="runmeta"></div><details><summary>What do the states mean?</summary><div id="legend"></div></details></header>
<div class="stats" id="stats" aria-label="Run summary"></div>
<div class="bar" role="search">
<label for="q">Find</label><input id="q" type="search" placeholder="Name or organisation number" autocomplete="off">
<label for="f">Show</label>
<select id="f"><option value="all">All companies</option><option value="site">With a verified website</option><option value="nosite">Without a verified website</option><option value="jobs">With active job ads</option><option value="attention">Ambiguous, blocked or failed</option><option value="changed">With changes</option></select>
<button id="cmpbtn" class="primary" type="button">Compare selected (0)</button><button id="clr" type="button" class="ghost">Clear</button><button id="csv" type="button" class="ghost">Export CSV</button>
</div>
<main>
<section id="list" aria-label="Companies" role="list"></section>
<section id="detail" aria-live="polite" tabindex="-1"></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
var $=function(id){return document.getElementById(id)};
function el(tag,attrs,kids){var n=document.createElement(tag);attrs=attrs||{};Object.keys(attrs).forEach(function(k){if(k==="class")n.className=attrs[k];else if(k==="text")n.textContent=attrs[k];else n.setAttribute(k,attrs[k])});(kids||[]).forEach(function(c){if(c==null)return;n.appendChild(typeof c==="string"?document.createTextNode(c):c)});return n}
var STATES={available:["\u2713","available"],not_available:["\u2013","not available"],blocked:["!","blocked"],not_applicable:["\u2013","not applicable"],ambiguous:["?","ambiguous"],failed:["\u00d7","failed"]};
var FIELD={legal_name:"Legal name",legal_form:"Legal form",municipality:"Municipality",industry:"Industry",employees:"Employees",financials_latest:"Latest annual accounts",role_holders:"Role holders",registered_locations:"Subunits",official_website:"Official website",registered_website:"Website in registry",website_title:"Website title",social_links:"Social profiles",business_address:"Business address",postal_address:"Postal address",founded:"Founded",registered_on:"Entered in register",vat_registered:"VAT registered",sector:"Institutional sector",secondary_industries:"Secondary industries",legal_status:"Legal status",annual_account_years:"Filed annual accounts",business_activity:"Registered business activity",registered_purpose:"Registered purpose",registry_contact_email:"Registry contact email",job_postings:"Active job ads",careers_page:"Careers page",news_page:"News page",contact_page:"Contact page",contact_email:"Contact email",parent_unit:"Parent unit",registered_in_business_register:"In Foretaksregisteret",last_submitted_annual_accounts:"Last accounts submitted",vat_registered_on:"VAT registered on",recent_registry_changes:"Recent register updates"};
function badge(state){var s=STATES[state]||["",state];return el("span",{class:"badge "+state},[el("span",{"aria-hidden":"true",text:s[0]+" "}),el("span",{text:s[1]})])}
function safeUrl(u){return typeof u==="string"&&/^https?:\/\//i.test(u)}
function link(u,t){return safeUrl(u)?el("a",{href:u,rel:"noopener noreferrer",target:"_blank",text:t||u}):el("span",{text:String(u)})}
function fmtNum(v){return typeof v==="number"?v.toLocaleString("en-US").replace(/,/g," "):String(v)}
function claimOf(c,f){for(var i=0;i<c.claims.length;i++)if(c.claims[i].field===f)return c.claims[i];return null}
function ok(c,f){var x=claimOf(c,f);return !!x&&x.availability==="available"}
function valueText(f,v){
 if(v==null)return "";
 if(f==="vat_registered"||f==="registered_in_business_register")return v?"Yes":"No";
 if(f==="job_postings"&&v&&Array.isArray(v.postings))return v.active_count+" active: "+v.postings.slice(0,4).map(function(x){return x.title+(x.published?" ("+x.published+")":"")}).join("; ");
 if(f==="recent_registry_changes"&&v&&typeof v==="object")return v.update_count+" since "+v.since+", latest "+v.latest_update+" ("+v.latest_type+(v.changed_fields&&v.changed_fields.length?": "+v.changed_fields.join(", "):"")+")";
 if(f==="annual_account_years"&&Array.isArray(v))return v.length+" year(s): "+v.join(", ");
 if(f==="role_holders"&&Array.isArray(v))return v.length+" active: "+v.slice(0,6).map(function(r){return (r.role||"role")+(r.name?" - "+r.name:"")}).join("; ")+(v.length>6?" ...":"");
 if(f==="registered_locations"&&Array.isArray(v))return v.length+" subunit(s)";
 if(f==="financials_latest"&&typeof v==="object"){var p=v.period||{};return ["period "+(p.fraDato||"?")+" to "+(p.tilDato||"?"),v.revenue!=null?"revenue "+fmtNum(v.revenue):null,v.annual_result!=null?"annual result "+fmtNum(v.annual_result):null,v.assets!=null?"assets "+fmtNum(v.assets):null].filter(Boolean).join(", ")+(v.currency?" ("+v.currency+")":"")}
 if(Array.isArray(v))return v.map(function(x){return typeof x==="object"?(x.url||JSON.stringify(x)):String(x)}).join(", ");
 if(typeof v==="object")return JSON.stringify(v);
 return typeof v==="number"?fmtNum(v):String(v)}
function evOf(c,id){for(var i=0;i<c.evidence.length;i++)if(c.evidence[i].id===id)return c.evidence[i];return null}
function attention(c){return Object.keys(c.modules).some(function(k){var s=c.modules[k];return s==="ambiguous"||s==="blocked"||s==="failed"})}
function completeness(c){var n=0;c.claims.forEach(function(x){if(x.availability==="available")n++});return [n,c.claims.length]}
var sel={},tab="summary",PAGE=25,shown=PAGE;
function renderStats(){var facts=0,sites=0,jobs=0,changed=0;D.companies.forEach(function(c){facts+=completeness(c)[0];if(ok(c,"official_website"))sites++;if(ok(c,"job_postings"))jobs++;if(c.changes.length)changed++});
 var box=$("stats");box.textContent="";[[D.companies.length,"companies"],[facts,"facts published, each with a source"],[sites,"verified websites"],[jobs,"with active job ads"],[changed,"with changes since last run"]].forEach(function(t){box.appendChild(el("div",{class:"stat"},[el("b",{text:fmtNum(t[0])}),el("span",{text:t[1]})]))})}
function filtered(){var q=$("q").value.trim().toLowerCase(),f=$("f").value;return D.companies.filter(function(c){
 if(q&&c.name.toLowerCase().indexOf(q)<0&&String(c.org).indexOf(q.replace(/\s/g,""))<0)return false;
 if(f==="site")return ok(c,"official_website");if(f==="nosite")return !ok(c,"official_website");if(f==="jobs")return ok(c,"job_postings");if(f==="attention")return attention(c);if(f==="changed")return c.changes.length>0;return true})}
function renderList(reset){if(reset!==false)shown=PAGE;var box=$("list");box.textContent="";var rows=filtered();
 if(!rows.length){box.appendChild(el("div",{class:"empty",text:"No company matches this search."}));return}
 box.appendChild(el("div",{class:"meta",style:"margin:0 2px 8px",text:"Showing "+Math.min(shown,rows.length)+" of "+rows.length}));
 rows.slice(0,shown).forEach(function(c){
  var cb=el("input",{type:"checkbox","aria-label":"Select "+c.name+" for comparison",style:"min-height:auto;width:22px;height:22px;flex:none"});cb.checked=!!sel[c.org];
  cb.addEventListener("change",function(){if(cb.checked)sel[c.org]=1;else delete sel[c.org];$("cmpbtn").textContent="Compare selected ("+Object.keys(sel).length+")";card.className="card"+(sel[c.org]?" sel":"")});
  var b=el("button",{type:"button",class:"openbtn","aria-label":"Open "+c.name,text:"Open"});b.addEventListener("click",function(){show(c.org,true)});
  var cp=completeness(c);
  var card=el("div",{class:"card"+(sel[c.org]?" sel":""),role:"listitem"},[
   el("div",{class:"cardtop"},[el("span",{class:"name",text:c.name}),el("label",{class:"chk"},[cb])]),
   el("div",{class:"meta",text:"Org. "+c.org}),
   el("div",{class:"prog",role:"img","aria-label":cp[0]+" of "+cp[1]+" facts published"},[el("i",{style:"width:"+Math.round(100*cp[0]/Math.max(1,cp[1]))+"%"})]),
   el("div",{class:"meta",text:cp[0]+" of "+cp[1]+" facts published"}),
   el("div",{class:"chips"},[el("span",{class:"lbl",text:"Website"}),badge(c.modules.website||"not_available"),el("span",{class:"lbl",text:"Jobs"}),badge(c.modules.jobs||"not_applicable")]),b]);
  box.appendChild(card)});
 if(rows.length>shown){var m=el("button",{type:"button",class:"more",text:"Show more ("+(rows.length-shown)+" left)"});m.addEventListener("click",function(){shown+=PAGE;renderList(false)});box.appendChild(m)}}
function srcBlock(c,cl){if(!cl.evidence_ids||!cl.evidence_ids.length)return el("span",{class:"src",text:"No source (not published)"});
 var d=el("details",{},[el("summary",{text:"Source ("+cl.evidence_ids.length+")"})]);
 cl.evidence_ids.forEach(function(id){var e=evOf(c,id);if(!e)return;d.appendChild(el("div",{class:"src"},[link(e.source_url),el("div",{text:"Retrieved "+(e.retrieved_at||"unknown")+" | "+(e.source_class||"source")}),el("div",{},[el("span",{text:"SHA-256 "}),el("code",{text:e.content_sha256||"n/a"})]),el("div",{text:"Evidence: "+(e.claim_span||"")})]))});return d}
function download(name,text,type){try{var u=URL.createObjectURL(new Blob([text],{type:type}));var a=el("a",{href:u,download:name});document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(u)},1000)}catch(e){}}
function csvCell(v){var s=v==null?"":String(v);return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s}
function exportCsv(){var rows=[["organisation_number","company","fact","value","state","source_url","retrieved_at","content_sha256"]];
 filtered().forEach(function(c){c.claims.forEach(function(cl){var e=cl.evidence_ids&&cl.evidence_ids.length?evOf(c,cl.evidence_ids[0]):null;rows.push([c.org,c.name,FIELD[cl.field]||cl.field,cl.availability==="available"?valueText(cl.field,cl.value):"",cl.availability,e?e.source_url:"",e?e.retrieved_at:"",e?e.content_sha256:""])})});
 download("signalpost-facts.csv",rows.map(function(r){return r.map(csvCell).join(",")}).join("\n"),"text/csv")}
function show(org,focus){var c=D.companies.filter(function(x){return x.org===org})[0];var box=$("detail");box.textContent="";if(!c)return;
 try{history.replaceState(null,"","#"+org)}catch(e){}
 var bk=el("button",{type:"button",class:"back",text:"Back to list"});bk.addEventListener("click",function(){$("list").scrollIntoView({block:"start"})});
 var cp=completeness(c);
 var copy=el("button",{type:"button",text:"Copy link"});copy.addEventListener("click",function(){try{navigator.clipboard.writeText(location.href);copy.textContent="Link copied"}catch(e){}});
 var dj=el("button",{type:"button",text:"Download JSON"});dj.addEventListener("click",function(){download("signalpost-"+c.org+".json",JSON.stringify(c,null,2),"application/json")});
 var reg=el("a",{href:"https://data.brreg.no/enhetsregisteret/api/enheter/"+c.org,rel:"noopener noreferrer",target:"_blank",text:"Open in the register"});
 box.appendChild(el("div",{class:"card"},[bk,el("h2",{text:c.name}),el("div",{class:"meta",text:"Organisation number "+c.org+" | "+cp[0]+" of "+cp[1]+" facts published"}),el("div",{class:"actions"},[copy,dj,reg])]));
 var panels={},tabbar=el("div",{class:"tabs",role:"tablist","aria-label":"Company sections"});
 [["summary","Summary"],["facts","Facts and sources"],["gaps","Changes and gaps"]].forEach(function(t){var b=el("button",{type:"button",role:"tab","aria-selected":t[0]===tab?"true":"false",text:t[1]});b.addEventListener("click",function(){tab=t[0];Object.keys(panels).forEach(function(k){panels[k].hidden=k!==tab});Array.prototype.forEach.call(tabbar.children,function(x,i){x.setAttribute("aria-selected",(["summary","facts","gaps"][i]===tab)?"true":"false")})});tabbar.appendChild(b)});
 box.appendChild(tabbar);
 var s=el("div",{class:"card",role:"tabpanel"},[el("h3",{text:"Summary"})]);c.synthesis.sentences.forEach(function(x){s.appendChild(el("p",{class:"sent",text:x.text}))});s.appendChild(el("div",{class:"src",text:"Built only from the published facts, each with its source; no language model."}));panels.summary=s;
 var t=el("table",{class:"facts"},[el("thead",{},[el("tr",{},[el("th",{text:"Fact"}),el("th",{text:"Value"}),el("th",{text:"State"}),el("th",{text:"Source"})])])]);var tb=el("tbody");
 c.claims.forEach(function(cl){tb.appendChild(el("tr",{},[el("td",{text:FIELD[cl.field]||cl.field}),el("td",{text:cl.availability==="available"?valueText(cl.field,cl.value):"-"}),el("td",{},[badge(cl.availability)]),el("td",{},[srcBlock(c,cl)])]))});
 t.appendChild(tb);var f=el("div",{class:"card",role:"tabpanel"},[el("h3",{text:"Facts and sources"}),el("div",{class:"scroll"},[t])]);panels.facts=f;
 var g=el("div",{class:"card",role:"tabpanel"},[el("h3",{text:"What changed"})]);
 if(c.changes.length)c.changes.forEach(function(x){g.appendChild(el("p",{class:"sent",text:(x.field||"field")+": "+(x.change_type||"changed")}))});else g.appendChild(el("p",{class:"sent",text:c.refresh&&c.refresh.compared_with_previous?"No material change since the previous run.":"First run: nothing to compare with yet."}));
 g.appendChild(el("h3",{text:"Not published and why",style:"margin-top:14px"}));
 if(c.synthesis.unknown.length)c.synthesis.unknown.forEach(function(x){g.appendChild(el("p",{class:"sent"},[badge(x.availability),el("span",{text:" "+x.label+": "+x.meaning})]))});else g.appendChild(el("p",{class:"sent",text:"Every listed fact was found and verified."}));
 c.errors.forEach(function(x){g.appendChild(el("p",{class:"src",text:(x.field||"")+": "+(x.note||"")}))});panels.gaps=g;
 Object.keys(panels).forEach(function(k){panels[k].hidden=k!==tab;box.appendChild(panels[k])});
 if(focus&&window.matchMedia&&!window.matchMedia("(min-width:900px)").matches){box.scrollIntoView({block:"start"})}}
function compare(){var keys=Object.keys(sel);var box=$("detail");box.textContent="";
 if(keys.length<2){box.appendChild(el("div",{class:"card empty",text:"Tick two to four companies in the list, then press Compare."}));return}
 keys=keys.slice(0,4);var cs=keys.map(function(k){return D.companies.filter(function(x){return x.org===k})[0]}).filter(Boolean);
 var t=el("table",{},[el("thead",{},[el("tr",{},[el("th",{text:"Fact"})].concat(cs.map(function(c){return el("th",{text:c.name})})))])]);var tb=el("tbody");
 var rows=[];D.fields.forEach(function(f){var texts=cs.map(function(c){var cl=claimOf(c,f);return cl&&cl.availability==="available"?valueText(f,cl.value):"state:"+(cl?cl.availability:"not_available")});var same=texts.every(function(x){return x===texts[0]});
  var tr=el("tr",{"data-same":same?"1":"0"},[el("td",{text:FIELD[f]||f})].concat(cs.map(function(c){var cl=claimOf(c,f);return el("td",{},cl&&cl.availability==="available"?[el("div",{text:valueText(f,cl.value)}),srcBlock(c,cl)]:[badge(cl?cl.availability:"not_available")])})));rows.push(tr);tb.appendChild(tr)});
 t.appendChild(tb);var dl=el("label",{class:"chk"});var dc=el("input",{type:"checkbox",id:"diffonly"});dl.appendChild(dc);dl.appendChild(document.createTextNode(" Show only facts that differ"));
 dc.addEventListener("change",function(){rows.forEach(function(r){r.hidden=dc.checked&&r.getAttribute("data-same")==="1"})});
 box.appendChild(el("div",{class:"card"},[el("h2",{text:"Compare"}),dl,el("div",{class:"scroll"},[t]),el("div",{class:"src",text:"Each published value has its own Source link: open it to see the URL, retrieval time and content hash."})]));box.scrollIntoView&&!wide&&box.scrollIntoView({behavior:"smooth"})}
$("title").textContent=D.title;
$("runmeta").textContent="Run "+(D.run.run_id||"")+" | one result per input company";
$("legend").textContent="available = found and sourced | not available = looked, nothing there | ambiguous = could not confirm it is this company | blocked = the source refused | failed = the lookup broke | not applicable = does not apply";
$("q").addEventListener("input",function(){renderList()});$("f").addEventListener("change",function(){renderList()});$("cmpbtn").addEventListener("click",compare);$("csv").addEventListener("click",exportCsv);
$("clr").addEventListener("click",function(){sel={};$("q").value="";$("f").value="all";$("cmpbtn").textContent="Compare selected (0)";renderList();$("detail").textContent=""});
renderStats();renderList();var h=(location.hash||"").replace("#",""),wide=window.matchMedia&&window.matchMedia("(min-width:900px)").matches;
if(h&&D.companies.some(function(x){return x.org===h}))show(h,false);else if(wide&&D.companies.length)show(D.companies[0].org,false);else $("detail").appendChild(el("div",{class:"card empty",text:"Choose a company from the list to see its summary, facts and sources."}));
})();
</script>
</body>
</html>
"""
