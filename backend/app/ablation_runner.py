"""One-call frontend baselines, deliberately separate from Advisor reasoning."""
from __future__ import annotations

import asyncio, copy, json, math, re, subprocess, sys, time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings
from .core.persona import Persona, PersonaRegistry
from .llm_log import LLMRunLog, bind_llm_persona, bind_llm_run_log, reset_llm_persona, reset_llm_run_log

INSTITUTIONS = (
    {"id":"bbc","name":"BBC","style":"BBC style","guide":"BBC.md"},
    {"id":"economist","name":"The Economist","style":"The Economist style","guide":"Economist.md"},
    {"id":"who","name":"WHO","style":"World Health Organization style","guide":"World Health Organization.md"},
    {"id":"ibm","name":"IBM","style":"IBM style","guide":"IBM.md"},
    {"id":"cfpb","name":"CFPB","style":"Consumer Financial Protection Bureau style","guide":"Consumer Financial Protection Bureau.md"},
    {"id":"cmu","name":"Carnegie Mellon University","style":"Carnegie Mellon University style","guide":"Carnegie Mellon Univeristy.md"},
    {"id":"ebay","name":"eBay","style":"eBay style","guide":"Ebay.md"},
    {"id":"shopify","name":"Shopify","style":"Shopify style","guide":"Shopify.md"},
)
_LABELS={"title":"Title and narrative","color":"Color and emphasis","axes":"Axes and scales","labels":"Labels and annotation","typography":"Typography","layout":"Layout and hierarchy","structure":"Chart composition and marks"}
_TOKENS=re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]")
_MAX_COMPILATION_ATTEMPTS=3
_MAX_RENDER_SPEC_CHARS=1_500_000
_MAX_RENDER_DIMENSION=8_192
_RENDER_TIMEOUT_SECONDS=20
_RENDER_PROBE="""import json,sys
try:
 import vl_convert as vlc
 spec=json.loads(sys.stdin.read())
 png=vlc.vegalite_to_png(vl_spec=json.dumps(spec,ensure_ascii=False),scale=1.0)
 print(json.dumps({'ok':bool(png and png[:8]==b'\\x89PNG\\r\\n\\x1a\\n'),'bytes':len(png or b'')}))
except Exception as exc:
 print(json.dumps({'ok':False,'error':f'{type(exc).__name__}: {exc}'}))
 sys.exit(1)
"""

def validate_baseline_spec(spec:Any)->list[str]:
    """Minimal, self-contained envelope check for an ablation candidate."""
    if not isinstance(spec,dict): return ["spec must be a JSON object"]
    if not any(key in spec for key in ("mark","layer","hconcat","vconcat","facet","spec","concat")):
        return ["spec has no Vega-Lite view definition"]
    return []

def normalize_baseline_context(context:Any)->dict:
    """Keep only the user-supplied goal; no Advisor context enrichment."""
    raw=context if isinstance(context,dict) else {}
    goal=raw.get("communication_goal",raw.get("user_intent",""))
    return {"communication_goal":str(goal).strip()[:2000]} if isinstance(goal,str) and goal.strip() else {}

def render_baseline_spec(spec:dict)->dict:
    """Compile-and-paint check only, isolated from the API process.

    A malformed LLM spec can imply an astronomically large raster canvas. The
    validation renderer must never be able to exhaust the server that is only
    trying to reject it, so it runs in a short-lived child process.
    """
    meta={"ok":False,"source":"ablation_render"}
    if not settings.vision_server_render:
        return {**meta,"error":"server_render_disabled"}
    started=time.perf_counter()
    try:
        payload=json.dumps(spec,ensure_ascii=False)
    except (TypeError,ValueError) as exc:
        return {**meta,"error":f"spec_serialization_failed: {exc}"}
    if len(payload)>_MAX_RENDER_SPEC_CHARS:
        return {**meta,"error":f"render_preflight_spec_too_large:{len(payload)}"}

    oversized=[]
    def walk(node:Any,path:str=""):
        if isinstance(node,dict):
            for key,value in node.items():
                child=f"{path}/{key}"
                if key in ("width","height") and isinstance(value,(int,float)) and not isinstance(value,bool) and (value<1 or value>_MAX_RENDER_DIMENSION):
                    oversized.append(f"{child}={value}")
                walk(value,child)
        elif isinstance(node,list):
            for index,value in enumerate(node): walk(value,f"{path}/{index}")
    walk(spec)
    if oversized:
        return {**meta,"error":"render_preflight_canvas_dimension:"+", ".join(oversized[:6])}

    try:
        result=subprocess.run(
            [sys.executable,"-c",_RENDER_PROBE], input=payload, text=True,
            capture_output=True, timeout=_RENDER_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
        )
        line=(result.stdout or "").strip().splitlines()[-1] if (result.stdout or "").strip() else ""
        report=json.loads(line) if line else {}
        if report.get("ok"):
            meta.update({"ok":True,"bytes":int(report.get("bytes") or 0)})
        else:
            detail=str(report.get("error") or result.stderr or f"renderer_exit_{result.returncode}").strip()
            meta["error"]="Vega-Lite to PNG conversion failed: "+detail[-2000:]
    except subprocess.TimeoutExpired:
        meta["error"]=f"render_timeout_after_{_RENDER_TIMEOUT_SECONDS}s"
    except Exception as exc:
        meta.update({"error":f"{type(exc).__name__}: {exc}","ms":round((time.perf_counter()-started)*1000,1)})
    meta["ms"]=round((time.perf_counter()-started)*1000,1)
    return meta

def _chunks(text: str) -> list[dict]:
    heading="Guide"; out=[]; part=[]
    def flush():
        nonlocal part
        value="\n".join(part).strip(); part=[]
        if value: out.append({"id":f"guide-{len(out)+1}","section":heading,"text":value[:1800]})
    for line in text.splitlines():
        if line.startswith("#"):
            flush(); heading=line.lstrip("#").strip() or heading
        else: part.append(line)
    flush(); return out

def _retrieve(chunks: list[dict], query: str, top_k: int=6) -> list[dict]:
    q=[t.lower() for t in _TOKENS.findall(query)]; docs=[[t.lower() for t in _TOKENS.findall(c["section"]+"\n"+c["text"])] for c in chunks]
    df=Counter(t for d in docs for t in set(d)); avg=sum(map(len,docs))/max(len(docs),1); scored=[]
    for chunk,doc in zip(chunks,docs):
        tf=Counter(doc); score=sum(math.log(1+(len(docs)-df[t]+.5)/(df[t]+.5))*((tf[t]*2.5)/(tf[t]+1.5*(.25+.75*len(doc)/max(avg,1)))) for t in set(q) if tf[t])
        if score: scored.append({**chunk,"score":round(score,6)})
    return sorted(scored,key=lambda x:-x["score"])[:top_k] or ([{**chunks[0],"score":0.0}] if chunks else [])

def _institution(pid:str)->dict|None:
    return next((item for item in INSTITUTIONS if item["id"]==pid),None)

def _guide_path(pid:str,persona:Persona|None)->Path|None:
    """Resolve the selected persona's own source guide, not a shared default."""
    inst=_institution(pid)
    guide=inst.get("guide") if inst else None
    if not guide and persona is not None:
        raw=persona.raw if isinstance(persona.raw,dict) else {}
        institution=raw.get("institution") if isinstance(raw.get("institution"),dict) else {}
        source=institution.get("source")
        if isinstance(source,str) and source.lower().endswith(".md"): guide=Path(source).name
    path=Path(settings.data_dir)/"Vizguide"/str(guide) if guide else None
    return path if path is not None and path.is_file() else None

def _system(method: str) -> str:
    if method == "rag":
        source = "Use the retrieved passages as additional design references."
    elif method == "persona_direct":
        source = "Use the supplied institutional persona as the design reference."
    else:
        source = "Use the requested style phrase as the design reference."
    rag_contract = ""
    persona_contract = ""
    prompt_contract = ""
    if method == "rag":
        rag_contract = """
Because this is a RAG run, every item in `changes` must include a non-empty `evidence` array. Each evidence item must contain the exact `chunk_id` of a supplied retrieved guide passage, a short verbatim `quote` from that passage, and `use`, explaining how that guidance produced this specific change. Also return `guideline_applications`: an array mapping each cited `chunk_id` to the change ids it informed and a brief application explanation. Do not cite a passage that was not supplied."""
    elif method == "persona_direct":
        persona_contract = """
Because this is a persona-without-reasoning run, report every persona guideline actually used. Every item in `changes` must include a non-empty `evidence` array. Each evidence item must contain the persona's exact `rule_id` or `persona_location`, a short verbatim `quote` from the supplied persona YAML, and `use`, explaining how that guideline produced this specific change. Also return `guideline_applications`: an array mapping every cited guideline to the change ids it informed and a brief application explanation. Do not claim a guideline was applied unless it caused a visible action in `improved_spec`."""
    else:
        prompt_contract = """
Because this is a prompt-only run, the requested style phrase is your only style evidence; do not invent institutional guidelines or quotes. Every item in `changes` must include a non-empty `evidence` array with the exact supplied `style_phrase` and `use`, explaining how that phrase produced this specific change. Also return `guideline_applications`: an array mapping that style phrase to the change ids it informed and a brief application explanation. Mark its source as `style prompt`."""
    return f"""You are directly modifying a Vega-Lite chart.
Make one independent design proposal from the supplied chart, user intention, and style/reference material. {source}
Use your own design judgment. You may change any part of the chart when it improves the result.
Your entire response must be exactly one valid, parseable JSON object—no Markdown fence, prose, preface, suffix, comments, or other characters outside the JSON. The object must contain `overall_rationale`, `improved_spec`, `changes`, and `text_changes`.
`improved_spec` must be a complete Vega-Lite specification. Before returning it, silently self-check the final chart: its data fields and transforms must resolve; marks must remain visible; Vega-Lite syntax and aggregation/expression usage must be valid; canvas dimensions must be reasonable; and titles, axes, labels, legends, annotations and source text must be readable, non-overlapping, unclipped, and placed near their intended chart components. Correct any problem you find before responding.
In `changes`, briefly describe the important changes you made and why.
{rag_contract}{persona_contract}{prompt_contract}"""

@dataclass
class Agent:
    persona_id:str; status:str="pending"; proposal:dict|None=None; error:str=""
    def payload(self): return {"persona_id":self.persona_id,"status":self.status,"progress":{"pending":.05,"reading":.25,"adjudicating":.7,"compiling":.9,"done":1,"error":1}.get(self.status,0),"proposal":self.proposal,"error":self.error or None}
@dataclass
class Run:
    run_id:str; method:str; spec:dict; context:dict; agents:dict[str,Agent]; order:list[str]; created_at:str; status:str="running"; replay_of:str|None=None; llm_log:LLMRunLog|None=field(default=None,repr=False); _supervisor:Any=field(default=None,repr=False)
    def payload(self):
        out={"run_id":self.run_id,"status":self.status,"created_at":self.created_at,"generation_method":self.method,"agents":[self.agents[i].payload() for i in self.order]}
        if self.replay_of: out.update({"replay_of":self.replay_of,"spec":self.spec,"context":self.context})
        return out
class AblationRunStore:
    def __init__(self): self.runs={}
    def get(self,key): return self.runs.get(key)
    def add(self, run:Run): self.runs[run.run_id]=run
    def snapshot(self, run:Run):
        directory=Path(settings.storage_dir)/"runs"; directory.mkdir(parents=True,exist_ok=True)
        document={"engine":"ablation","mode":run.method,"request":{"spec":run.spec,"persona_ids":run.order,"context":run.context,"generation_method":run.method},**run.payload()}
        path=directory/f"{run.run_id}.json"
        with path.open("w",encoding="utf-8") as handle:
            handle.write(json.dumps({"engine":"ablation","run_id":run.run_id,"mode":run.method},ensure_ascii=False)+"\n")
            json.dump(document,handle,ensure_ascii=False,indent=2); handle.write("\n")

def _text_value(value:Any)->str:
    if isinstance(value,dict): value=value.get("text")
    if isinstance(value,list): value=" ".join(str(part) for part in value)
    return str(value or "").strip()

def _first_description(node:Any)->str:
    """Depth-first first `description`, preserving the input spec's order."""
    if isinstance(node,dict):
        value=node.get("description")
        if isinstance(value,str) and value.strip(): return value.strip()
        for value in node.values():
            found=_first_description(value)
            if found: return found
    elif isinstance(node,list):
        for value in node:
            found=_first_description(value)
            if found: return found
    return ""

def _dataset_number(spec:dict)->str:
    """Return the two-digit dataset folder number only for an exact JSON match."""
    try: source=json.dumps(spec,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    except (TypeError,ValueError): return ""
    root=Path(settings.data_dir)/"dataset"
    if not root.is_dir(): return ""
    for folder in root.iterdir():
        if not folder.is_dir(): continue
        match=re.match(r"^(\d{2})",folder.name)
        if not match: continue
        for path in folder.rglob("*.json"):
            try: candidate=json.loads(path.read_text(encoding="utf-8"))
            except (OSError,json.JSONDecodeError): continue
            try: encoded=json.dumps(candidate,sort_keys=True,separators=(",",":"),ensure_ascii=False)
            except (TypeError,ValueError): continue
            if encoded==source: return match.group(1)
    return ""

def _title_for_run_id(spec:dict)->str:
    dataset_number=_dataset_number(spec)
    if dataset_number: return dataset_number
    title=spec.get("title") if isinstance(spec,dict) else None
    value=_text_value(title) or _first_description(spec) or "Untitled"
    # Keep the reader-facing title where Windows allows it; only remove path
    # separators, reserved filename characters and trailing dots/spaces.
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]+'," ",value)
    value=re.sub(r"\s+"," ",value).strip(". ")
    return (value or "Untitled")[:96]

def _method_for_run_id(method:str)->str:
    return {"prompt_only":"prompt","persona_direct":"persona","rag":"rag"}.get(method,method)

def _allocate_run_id(store:AblationRunStore,spec:dict,method:str)->str:
    directory=Path(settings.storage_dir)/"runs"; prefix=f"{_title_for_run_id(spec)}-{_method_for_run_id(method)}"
    matcher=re.compile(rf"^{re.escape(prefix)}-(\d+)$",re.I)
    numbers=[]
    if directory.is_dir():
        for path in directory.glob("*.json"):
            match=matcher.match(path.stem)
            if match: numbers.append(int(match.group(1)))
    for run_id in store.runs:
        match=matcher.match(run_id)
        if match: numbers.append(int(match.group(1)))
    return f"{prefix}-{max(numbers,default=0)+1}"

def _allocate_replay_id(store:AblationRunStore,source_run_id:str)->str:
    base=f"replay-{source_run_id}-{datetime.now().strftime('%H%M%S')}"; value=base; suffix=1
    while store.get(value) is not None:
        suffix+=1; value=f"{base}-{suffix}"
    return value

def _proposal(pid:str,name:str,method:str,source:dict,response:dict,retrieval:list[dict]|None,elapsed:float,render:dict|None=None,attempts:int=1,compile_errors:list[str]|None=None)->dict:
    candidate=response.get("improved_spec") if isinstance(response.get("improved_spec"),dict) else source
    changes=[]; retrieval_index={str(chunk.get("id")):chunk for chunk in (retrieval or []) if isinstance(chunk,dict) and chunk.get("id")}; applications={}; missing_evidence=[]
    for n,item in enumerate(response.get("changes") or []):
        if not isinstance(item,dict): continue
        scope=str(item.get("component") or "structure").lower(); scope=scope if scope in _LABELS else "structure"; supplied=next((x for x in item.get("evidence",[]) if isinstance(x,dict) and str(x.get("chunk_id") or "") in retrieval_index),{}); ev=supplied or next((x for x in item.get("evidence",[]) if isinstance(x,dict)),{})
        reason=(str(item.get("modification") or "Direct redesign.")+" "+str(item.get("reason") or "")).strip()
        change_id=f"{pid}:ablation:{method}:{item.get('id') or n+1}"
        if method=="rag" and supplied:
            chunk=retrieval_index[str(supplied["chunk_id"])]; quoted=str(supplied.get("quote") or "").strip(); text=str(chunk.get("text") or "")
            quote=quoted if quoted and quoted in text else text[:600]
            application=applications.setdefault(str(supplied["chunk_id"]),{"chunk_id":str(supplied["chunk_id"]),"section":str(chunk.get("section") or "Guide"),"quote":quote,"applied_change_ids":[],"applications":[]})
            application["applied_change_ids"].append(change_id); application["applications"].append(str(supplied.get("use") or reason))
            ev={**supplied,"quote":quote}
        elif method=="rag": missing_evidence.append(change_id)
        elif method=="persona_direct" and ev and (ev.get("rule_id") or ev.get("persona_location")):
            guideline_id=str(ev.get("rule_id") or ev.get("persona_location")); application=applications.setdefault(guideline_id,{"guideline_id":guideline_id,"persona_location":str(ev.get("persona_location") or guideline_id),"quote":str(ev.get("quote") or ""),"applied_change_ids":[],"applications":[],"source_file":"persona knowledge base"})
            application["applied_change_ids"].append(change_id); application["applications"].append(str(ev.get("use") or reason))
        elif method=="persona_direct": missing_evidence.append(change_id)
        elif method=="prompt_only" and ev and str(ev.get("style_phrase") or "").strip()==f"{name} style":
            style_phrase=f"{name} style"; guideline_id=f"style:{style_phrase}"; application=applications.setdefault(guideline_id,{"guideline_id":guideline_id,"style_phrase":style_phrase,"quote":style_phrase,"applied_change_ids":[],"applications":[],"source_file":"style prompt"})
            application["applied_change_ids"].append(change_id); application["applications"].append(str(ev.get("use") or reason))
        elif method=="prompt_only": missing_evidence.append(change_id)
        layer="RAG evidence" if method=="rag" else "Persona guideline" if method=="persona_direct" else "Direct prompt"
        source_file="retrieved guideline" if method=="rag" else "persona knowledge base" if method=="persona_direct" else "style prompt"
        evidence_id=str(ev.get("chunk_id") or ev.get("rule_id") or ev.get("persona_location") or (f"style:{name} style" if method=="prompt_only" else method))
        warrant_quote=str(ev.get("quote") or "") or (f"{name} style" if method=="prompt_only" else "")
        changes.append({"id":change_id,"rule_id":evidence_id,"scope":scope,"label":_LABELS[scope],"reason":reason,"prompt":reason,"layer":layer,"strength":"should","confidence":"medium","status":"applied","warrant":{"src":[evidence_id],"story_id":evidence_id,"story":str(ev.get("use") or ""),"quote":warrant_quote,"source_file":source_file,"derived":False},"component_detail":{"spec_paths":[x for x in item.get("spec_paths",[]) if isinstance(x,str)],"execution":"select_complete_candidate"},"ops":[{"action":"select_complete_candidate","candidate_spec":candidate}]})
    facts={"ablation_method":method,"candidate_validation_errors":validate_baseline_spec(candidate),"generation_attempts":attempts}
    if render is not None: facts["candidate_render"]=render
    if compile_errors: facts["prior_compile_errors"]=compile_errors
    if retrieval is not None: facts["retrieved_guide_passages"]=retrieval
    if applications: facts["guideline_applications"]=list(applications.values())
    if missing_evidence: facts["guideline_evidence_missing_for"]=missing_evidence
    retry_note="" if attempts==1 else f" Required {attempts} direct attempts after {attempts-1} compilation failure(s)."
    return {"persona_id":pid,"persona_name":name,"facts":facts,"original_spec":source,"modified_spec":candidate,"changes":changes,"guideline_applications":list(applications.values()),"rejected":[],"invariants":[],"trace":[{"beat":1,"lane":"slow","name":"Direct baseline generation","ms":round(elapsed,1),"summary":"Direct LLM generation with no advisor reasoning, review, repair, or composer."+retry_note}],"summary":str(response.get("overall_rationale") or "One direct baseline generation completed."),"elapsed_ms":round(elapsed,1)}

async def _agent(run:Run,pid:str,persona:Persona|None,llm):
    state=run.agents[pid]; started=time.perf_counter()
    log_token=bind_llm_run_log(run.llm_log) if run.llm_log is not None else None
    persona_token=bind_llm_persona(pid)
    try:
        state.status="reading"; intent=str(run.context.get("communication_goal") or ""); state.status="adjudicating"; retrieval=None
        if run.method=="persona_direct":
            if persona is None: raise ValueError(f"unknown persona: {pid}")
            payload={"persona":persona.raw,"user_communication_goal":intent or None,"source_vega_lite_spec":run.spec}; name=persona.name
        elif run.method=="prompt_only":
            # Prompt-only deliberately has no persona or guide content.  The
            # sole institution signal is exactly the name chosen in the UI.
            inst=_institution(pid)
            name=persona.name if persona is not None else (inst["name"] if inst else pid)
            payload={"requested_style":f"{name} style","user_communication_goal":intent or None,"source_vega_lite_spec":run.spec}
        else:
            guide_path=_guide_path(pid,persona)
            if guide_path is None: raise ValueError(f"No Markdown guide is available for selected persona: {pid}")
            inst=_institution(pid); name=persona.name if persona is not None else (inst["name"] if inst else pid)
            payload={"requested_style":f"{name} style","user_communication_goal":intent or None,"source_vega_lite_spec":run.spec}
            if run.method=="rag":
                chunks=_chunks(guide_path.read_text(encoding="utf-8")); retrieval=_retrieve(chunks,intent+name+json.dumps(run.spec,ensure_ascii=False)); payload["retrieved_guide_passages"]=retrieval
        # A baseline has no review or repair pipeline. The sole exception is a
        # bounded re-generation when its returned Vega-Lite code cannot pass
        # the compiler: the same agent receives that exact compiler error and
        # may try again, at most three total direct calls.
        response=None; render=None; compile_errors=[]
        for attempt in range(1,_MAX_COMPILATION_ATTEMPTS+1):
            attempt_payload=copy.deepcopy(payload)
            if compile_errors:
                attempt_payload["previous_compile_error"]=compile_errors[-1]
                attempt_payload["retry_instruction"]="Return a new complete improved_spec that fixes this Vega-Lite compiler error. Do not describe a repair; output the replacement JSON."
            response=await llm.chat_json(
                _system(run.method), json.dumps(attempt_payload,ensure_ascii=False),
                retries=0, reasoning_effort="minimal",
            )
            if not isinstance(response,dict): raise TypeError("LLM did not return a JSON object")
            candidate=response.get("improved_spec")
            if not isinstance(candidate,dict):
                failure="LLM response is missing a complete improved_spec"
            else:
                errors=validate_baseline_spec(candidate)
                if errors:
                    failure="Invalid Vega-Lite improved_spec: "+"; ".join(errors)
                else:
                    # Compilation/paint validation only—no programmatic code
                    # repair or design decision. The image is rendered again
                    # by the frontend for display.
                    render=render_baseline_spec(candidate)
                    render_error=str(render.get("error") or "")
                    failure="" if not render_error or render_error.startswith("ModuleNotFoundError:") or render_error=="server_render_disabled" else "Vega-Lite render failed: "+render_error
            if not failure: break
            compile_errors.append(failure)
            if attempt==_MAX_COMPILATION_ATTEMPTS: raise ValueError(failure)
        state.status="compiling"; state.proposal=_proposal(pid,name,run.method,run.spec,response,retrieval,(time.perf_counter()-started)*1000,render,attempt,compile_errors); state.status="done"
    except Exception as exc: state.status="error"; state.error=f"{type(exc).__name__}: {exc}"
    finally:
        reset_llm_persona(persona_token)
        if log_token is not None: reset_llm_run_log(log_token)

def start_ablation_run(store:AblationRunStore,registry:PersonaRegistry,llm,spec:dict,persona_ids:list[str],context:dict|None,method:str):
    order=list(dict.fromkeys(persona_ids)); persons={p:registry.get(p) for p in order}
    if not order: return None,"persona_ids 不能为空"
    if method=="persona_direct" and any(x is None for x in persons.values()): return None,"未知 persona"
    if method=="prompt_only":
        known={x["id"] for x in INSTITUTIONS}
        unknown=[pid for pid,persona in persons.items() if persona is None and pid not in known]
        if unknown: return None,f"未知机构: {', '.join(unknown)}"
    if method=="rag":
        unavailable=[pid for pid,persona in persons.items() if _guide_path(pid,persona) is None]
        if unavailable: return None,"所选 persona 缺少可检索的 Markdown 指南: "+", ".join(unavailable)
    run_id=_allocate_run_id(store,spec,method)
    run=Run(run_id,method,copy.deepcopy(spec),context or {},{p:Agent(p) for p in order},order,datetime.now(timezone.utc).isoformat(),llm_log=LLMRunLog(run_id=run_id,kind="advisor")); store.add(run)
    async def supervise():
        try: await asyncio.gather(*(_agent(run,p,persons.get(p),llm) for p in order))
        finally:
            # One direct baseline can be invalid while the other institutions
            # still have useful, independently generated candidates. Match the
            # regular Advisor delivery contract: agent-level errors remain
            # visible, but the completed run is delivered rather than leaving
            # the frontend polling an aggregate error forever.
            run.status="done"
            if run.llm_log is not None: run.llm_log.flush()
            try: store.snapshot(run)
            except OSError as exc: print(f"[ablation] 快照写入失败: {exc}",flush=True)
    run._supervisor=asyncio.create_task(supervise()); return run,""
async def wait_ablation_run(run:Run):
    if run._supervisor: await run._supervisor

def load_ablation_record(run_id:str)->tuple[dict|None,str]:
    name=str(run_id or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."): return None,"非法 run_id"
    path=Path(settings.storage_dir)/"runs"/f"{name}.json"
    try: raw=path.read_text(encoding="utf-8")
    except OSError: return None,f"未找到 ablation run 记录: {name}"
    for candidate in (raw,raw.split("\n",1)[-1]):
        try: document=json.loads(candidate)
        except (json.JSONDecodeError,IndexError): continue
        if isinstance(document,dict) and document.get("engine")=="ablation" and isinstance(document.get("agents"),list): return document,""
    return None,f"ablation run 记录无法解析: {name}"

def start_ablation_replay(store:AblationRunStore,run_id:str,persona_ids:list[str]|None=None,delay_ms:int|None=None)->tuple[Run|None,str]:
    document,error=load_ablation_record(run_id)
    if document is None: return None,error
    recorded={str(item.get("persona_id")):item.get("proposal") for item in document["agents"] if isinstance(item,dict) and item.get("persona_id") and isinstance(item.get("proposal"),dict)}
    wanted=[str(pid) for pid in persona_ids] if persona_ids else list(recorded)
    if not wanted: return None,"run 记录中没有可回放的提案"
    missing=[pid for pid in wanted if pid not in recorded]
    if missing: return None,"run 记录缺少这些机构的提案: "+", ".join(missing)
    request=document.get("request") if isinstance(document.get("request"),dict) else {}
    replay_id=_allocate_replay_id(store,run_id)
    run=Run(replay_id,str(document.get("mode") or request.get("generation_method") or "prompt_only"),copy.deepcopy(request.get("spec") if isinstance(request.get("spec"),dict) else {}),copy.deepcopy(request.get("context") if isinstance(request.get("context"),dict) else {}),{pid:Agent(pid) for pid in wanted},wanted,datetime.now(timezone.utc).isoformat(),replay_of=str(document.get("run_id") or run_id))
    store.add(run); delay=max(int(settings.replay_beat_delay_ms if delay_ms is None else delay_ms),0)/1000
    async def replay():
        async def replay_agent(pid:str):
            state=run.agents[pid]
            for stage in ("reading","adjudicating","compiling"):
                state.status=stage; await asyncio.sleep(delay) if delay else await asyncio.sleep(0)
            state.proposal=copy.deepcopy(recorded[pid]); state.status="done"
        await asyncio.gather(*(replay_agent(pid) for pid in wanted)); run.status="done"
    run._supervisor=asyncio.create_task(replay()); return run,""

def apply_ablation_candidate(source:dict, changes:list[dict], instructions:str="")->dict:
    """Deliver one chosen baseline candidate without invoking the composer.

    Baselines intentionally do not support cross-institution recomposition or
    free-text post-editing: selecting any change from one proposal selects its
    complete one-shot LLM result.
    """
    candidates=[]
    for change in changes:
        for op in change.get("ops") or []:
            if isinstance(op,dict) and op.get("action")=="select_complete_candidate" and isinstance(op.get("candidate_spec"),dict):
                candidates.append((str(change.get("id") or "baseline-candidate"),op["candidate_spec"]))
    if not candidates:
        return {"final_spec":source,"applied":[],"skipped":[],"conflicts":[],"notes":["No complete ablation candidate was selected."]}
    unique={json.dumps(candidate,sort_keys=True,ensure_ascii=False):candidate for _,candidate in candidates}
    if len(unique)!=1:
        return {"final_spec":source,"applied":[],"skipped":[{"id":cid,"reason":"A baseline can deliver only one institution's complete candidate."} for cid,_ in candidates],"conflicts":[],"notes":["Cross-institution composition is unavailable for ablation methods; select changes from one institution only."]}
    candidate=next(iter(unique.values()))
    errors=validate_baseline_spec(candidate)
    if errors:
        return {"final_spec":source,"applied":[],"skipped":[{"id":cid,"reason":"; ".join(errors)} for cid,_ in candidates],"conflicts":[],"notes":["Selected baseline candidate is not a valid Vega-Lite spec."]}
    render=render_baseline_spec(candidate); error=str(render.get("error") or "")
    if error and error not in ("server_render_disabled",) and not error.startswith("ModuleNotFoundError:"):
        return {"final_spec":source,"applied":[],"skipped":[{"id":cid,"reason":"Vega-Lite render failed: "+error} for cid,_ in candidates],"conflicts":[],"notes":["Selected baseline candidate could not be rendered."]}
    notes=["Delivered the selected one-shot ablation candidate directly; no Advisor composer was used."]
    if instructions.strip(): notes.append("Free-text composer instructions are intentionally ignored in ablation mode.")
    return {"final_spec":candidate,"applied":[cid for cid,_ in candidates],"skipped":[],"conflicts":[],"notes":notes}
