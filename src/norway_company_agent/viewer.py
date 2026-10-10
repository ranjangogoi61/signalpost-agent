"""Single-file, offline HTML viewer for Signalpost envelopes (find, compare, verify)."""
from __future__ import annotations

import copy
import json
from typing import Any

FIELDS = ["legal_name", "legal_form", "municipality", "industry", "employees", "financials_latest", "role_holders", "registered_locations", "official_website"]


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
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--muted:#4a5565;--line:#d5dae2;--accent:#123eaa;--ok:#0b6b3a;--warn:#8a5a00;--bad:#9b1c1c;--grey:#4a5565}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#181d26;--ink:#eef1f6;--muted:#b3bccb;--line:#2e3746;--accent:#8fb0ff;--ok:#6fdc9e;--warn:#f0c36a;--bad:#ff9c9c;--grey:#b3bccb}}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:var(--accent)}header{padding:16px;border-bottom:1px solid var(--line);background:var(--card)}
h1{font-size:1.25rem;margin:0 0 4px}h2{font-size:1.1rem;margin:16px 0 8px}h3{font-size:1rem;margin:12px 0 6px}
.meta{color:var(--muted);font-size:.9rem}.bar{display:flex;flex-wrap:wrap;gap:8px;padding:12px 16px;background:var(--card);border-bottom:1px solid var(--line)}
input,select,button{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-height:44px}
input[type=search]{flex:1 1 220px}button{cursor:pointer}button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
main{display:grid;grid-template-columns:1fr;gap:12px;padding:12px 16px}
@media (min-width:900px){main{grid-template-columns:minmax(300px,380px) 1fr;align-items:start}#list{max-height:calc(100vh - 150px);overflow:auto;position:sticky;top:8px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin:0 0 8px}
.row{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}.name{font-weight:600}
.badge{display:inline-block;border:1px solid currentColor;border-radius:999px;padding:1px 8px;font-size:.78rem;white-space:nowrap}
.available{color:var(--ok)}.not_available,.not_applicable{color:var(--grey)}.ambiguous,.blocked{color:var(--warn)}.failed{color:var(--bad)}
.sel{outline:2px solid var(--accent)}table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.scroll{overflow-x:auto}details{margin:4px 0}summary{cursor:pointer;color:var(--accent)}code{word-break:break-all;font-size:.82rem}
.sent{margin:0 0 8px}.src{font-size:.85rem;color:var(--muted)}.empty{color:var(--muted);padding:16px}.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;background:var(--card);padding:8px;z-index:9}
</style>
</head>
<body>
<a class="skip" href="#detail">Skip to company details</a>
<header><h1 id="title"></h1><div class="meta" id="runmeta"></div><div class="meta" id="legend"></div></header>
<div class="bar" role="search">
<label class="meta" for="q" style="align-self:center">Find</label><input id="q" type="search" placeholder="Name or organisation number" autocomplete="off">
<label class="meta" for="f" style="align-self:center">Show</label>
<select id="f"><option value="all">All companies</option><option value="site">With a verified website</option><option value="nosite">Without a verified website</option><option value="attention">Ambiguous, blocked or failed</option><option value="changed">With changes</option></select>
<button id="cmpbtn" class="primary" type="button">Compare selected (0)</button><button id="clr" type="button">Clear</button>
</div>
<main>
<section id="list" aria-label="Companies"></section>
<section id="detail" aria-live="polite" tabindex="-1"></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
var $=function(id){return document.getElementById(id)};
function el(tag,attrs,kids){var n=document.createElement(tag);attrs=attrs||{};Object.keys(attrs).forEach(function(k){if(k==="class")n.className=attrs[k];else if(k==="text")n.textContent=attrs[k];else n.setAttribute(k,attrs[k])});(kids||[]).forEach(function(c){if(c==null)return;n.appendChild(typeof c==="string"?document.createTextNode(c):c)});return n}
var LABEL={available:"available",not_available:"not available",blocked:"blocked",not_applicable:"not applicable",ambiguous:"ambiguous",failed:"failed"};
var FIELD={legal_name:"Legal name",legal_form:"Legal form",municipality:"Municipality",industry:"Industry",employees:"Employees",financials_latest:"Latest annual accounts",role_holders:"Role holders",registered_locations:"Subunits",official_website:"Official website",registered_website:"Website in registry",website_title:"Website title",social_links:"Social profiles"};
function badge(state){return el("span",{class:"badge "+state,text:LABEL[state]||state})}
function safeUrl(u){return typeof u==="string"&&/^https?:\/\//i.test(u)}
function link(u,t){return safeUrl(u)?el("a",{href:u,rel:"noopener noreferrer",target:"_blank",text:t||u}):el("span",{text:String(u)})}
function fmtNum(v){return typeof v==="number"?v.toLocaleString("en-US").replace(/,/g," "):String(v)}
function claimOf(c,f){for(var i=0;i<c.claims.length;i++)if(c.claims[i].field===f)return c.claims[i];return null}
function valueText(f,v){
 if(v==null)return "";
 if(f==="role_holders"&&Array.isArray(v))return v.length+" active: "+v.slice(0,6).map(function(r){return (r.role||"role")+(r.name?" - "+r.name:"")}).join("; ")+(v.length>6?" ...":"");
 if(f==="registered_locations"&&Array.isArray(v))return v.length+" subunit(s)";
 if(f==="financials_latest"&&typeof v==="object"){var p=v.period||{};return ["period "+(p.fraDato||"?")+" to "+(p.tilDato||"?"),v.revenue!=null?"revenue "+fmtNum(v.revenue):null,v.annual_result!=null?"annual result "+fmtNum(v.annual_result):null,v.assets!=null?"assets "+fmtNum(v.assets):null].filter(Boolean).join(", ")+(v.currency?" ("+v.currency+")":"")}
 if(Array.isArray(v))return v.map(function(x){return typeof x==="object"?(x.url||JSON.stringify(x)):String(x)}).join(", ");
 if(typeof v==="object")return JSON.stringify(v);
 return typeof v==="number"?fmtNum(v):String(v)}
function evOf(c,id){for(var i=0;i<c.evidence.length;i++)if(c.evidence[i].id===id)return c.evidence[i];return null}
function hasSite(c){var x=claimOf(c,"official_website");return !!x&&x.availability==="available"}
function attention(c){return Object.keys(c.modules).some(function(k){var s=c.modules[k];return s==="ambiguous"||s==="blocked"||s==="failed"})}
var sel={},open=null;
function filtered(){var q=$("q").value.trim().toLowerCase(),f=$("f").value;return D.companies.filter(function(c){
 if(q&&c.name.toLowerCase().indexOf(q)<0&&String(c.org).indexOf(q.replace(/\s/g,""))<0)return false;
 if(f==="site")return hasSite(c);if(f==="nosite")return !hasSite(c);if(f==="attention")return attention(c);if(f==="changed")return c.changes.length>0;return true})}
function renderList(){var box=$("list");box.textContent="";var rows=filtered();
 if(!rows.length){box.appendChild(el("div",{class:"empty",text:"No company matches this search."}));return}
 rows.forEach(function(c){
  var cb=el("input",{type:"checkbox","aria-label":"Select "+c.name+" for comparison",style:"min-height:auto;width:20px;height:20px"});cb.checked=!!sel[c.org];
  cb.addEventListener("change",function(){if(cb.checked)sel[c.org]=1;else delete sel[c.org];$("cmpbtn").textContent="Compare selected ("+Object.keys(sel).length+")";card.className="card"+(sel[c.org]?" sel":"")});
  var b=el("button",{type:"button","aria-label":"Open "+c.name,text:"Open"});b.addEventListener("click",function(){show(c.org)});
  var card=el("div",{class:"card"+(sel[c.org]?" sel":""),role:"listitem"},[
   el("div",{class:"row"},[el("span",{class:"name",text:c.name}),cb]),
   el("div",{class:"meta",text:"Org. "+c.org}),
   el("div",{class:"row"},[el("span",{},[badge(c.modules.website||"not_available"),el("span",{text:" website "}),badge(c.modules.financials||"not_available"),el("span",{text:" accounts"})]),b])]);
  box.appendChild(card)})}
function srcBlock(c,cl){if(!cl.evidence_ids||!cl.evidence_ids.length)return el("span",{class:"src",text:"No source (not published)"});
 var d=el("details",{},[el("summary",{text:"Source ("+cl.evidence_ids.length+")"})]);
 cl.evidence_ids.forEach(function(id){var e=evOf(c,id);if(!e)return;d.appendChild(el("div",{class:"src"},[link(e.source_url),el("div",{text:"Retrieved "+(e.retrieved_at||"unknown")+" | "+(e.source_class||"source")}),el("div",{},[el("span",{text:"SHA-256 "}),el("code",{text:e.content_sha256||"n/a"})]),el("div",{text:"Evidence: "+(e.claim_span||"")})]))});return d}
function show(org){open=org;var c=D.companies.filter(function(x){return x.org===org})[0];var box=$("detail");box.textContent="";if(!c){return}
 try{history.replaceState(null,"","#"+org)}catch(e){}
 box.appendChild(el("div",{class:"card"},[el("h2",{text:c.name}),el("div",{class:"meta",text:"Organisation number "+c.org})]));
 var s=el("div",{class:"card"},[el("h3",{text:"Summary"})]);c.synthesis.sentences.forEach(function(x){s.appendChild(el("p",{class:"sent",text:x.text}))});
 s.appendChild(el("div",{class:"src",text:"Built only from the published facts below; no language model."}));box.appendChild(s);
 var t=el("table",{},[el("thead",{},[el("tr",{},[el("th",{text:"Fact"}),el("th",{text:"Value"}),el("th",{text:"State"}),el("th",{text:"Source"})])])]);var tb=el("tbody");
 c.claims.forEach(function(cl){tb.appendChild(el("tr",{},[el("td",{text:FIELD[cl.field]||cl.field}),el("td",{text:cl.availability==="available"?valueText(cl.field,cl.value):"-"}),el("td",{},[badge(cl.availability)]),el("td",{},[srcBlock(c,cl)])]))});
 t.appendChild(tb);box.appendChild(el("div",{class:"card"},[el("h3",{text:"Facts and sources"}),el("div",{class:"scroll"},[t])]));
 var ch=el("div",{class:"card"},[el("h3",{text:"What changed"})]);
 if(c.changes.length)c.changes.forEach(function(x){ch.appendChild(el("p",{class:"sent",text:(x.field||"field")+": "+(x.change_type||"changed")}))});else ch.appendChild(el("p",{class:"sent",text:c.refresh&&c.refresh.compared_with_previous?"No material change since the previous run.":"First run: nothing to compare with yet."}));
 box.appendChild(ch);
 var u=el("div",{class:"card"},[el("h3",{text:"Not published and why"})]);
 if(c.synthesis.unknown.length)c.synthesis.unknown.forEach(function(x){u.appendChild(el("p",{class:"sent"},[badge(x.availability),el("span",{text:" "+x.label+": "+x.meaning})]))});else u.appendChild(el("p",{class:"sent",text:"Every listed fact was found and verified."}));
 c.errors.forEach(function(x){u.appendChild(el("p",{class:"src",text:(x.field||"")+": "+(x.note||"")}))});box.appendChild(u);
 if(window.matchMedia&&!window.matchMedia("(min-width:900px)").matches)box.focus()}
function compare(){var keys=Object.keys(sel);var box=$("detail");box.textContent="";
 if(keys.length<2){box.appendChild(el("div",{class:"empty",text:"Tick two to four companies in the list, then press Compare."}));return}
 keys=keys.slice(0,4);var cs=keys.map(function(k){return D.companies.filter(function(x){return x.org===k})[0]}).filter(Boolean);
 var t=el("table",{},[el("thead",{},[el("tr",{},[el("th",{text:"Fact"})].concat(cs.map(function(c){return el("th",{text:c.name})})))])]);var tb=el("tbody");
 D.fields.forEach(function(f){tb.appendChild(el("tr",{},[el("td",{text:FIELD[f]||f})].concat(cs.map(function(c){var cl=claimOf(c,f);return el("td",{},cl&&cl.availability==="available"?[valueText(f,cl.value)]:[badge(cl?cl.availability:"not_available")])}))))});
 t.appendChild(tb);box.appendChild(el("div",{class:"card"},[el("h2",{text:"Compare"}),el("div",{class:"scroll"},[t]),el("div",{class:"src",text:"Open each company for its sources."})]))}
$("title").textContent=D.title;
var tot=D.run.availability_totals||{};
$("runmeta").textContent="Run "+(D.run.run_id||"")+" | "+D.companies.length+" companies | one result per input company";
$("legend").textContent="States: available = found and sourced; not available = looked, nothing there; ambiguous = could not confirm it is this company; blocked = source refused; failed = lookup broke; not applicable = does not apply.";
$("q").addEventListener("input",renderList);$("f").addEventListener("change",renderList);$("cmpbtn").addEventListener("click",compare);
$("clr").addEventListener("click",function(){sel={};$("q").value="";$("f").value="all";$("cmpbtn").textContent="Compare selected (0)";renderList();$("detail").textContent=""});
renderList();var h=(location.hash||"").replace("#","");if(h&&D.companies.some(function(x){return x.org===h}))show(h);else if(D.companies.length)show(D.companies[0].org);
})();
</script>
</body>
</html>
"""
