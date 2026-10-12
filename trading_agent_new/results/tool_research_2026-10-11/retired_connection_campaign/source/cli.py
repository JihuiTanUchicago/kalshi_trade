"""CLI entry points for operator setup, research, evidence, evaluation and paper."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import argparse
import json
import os
import sys

from .agent import ResearchAgent
from .common import AgentError, GateError, canonical, digest, file_hash, utcnow
from .contracts import ModelRequest,ResearchSpec
from .configuration import load_model_environment
from .data import Dataset, qualify
from .doctor import readiness
from .evaluation import benchmark_preflight, prepare_suite, run_benchmark
from .fixtures import make_fixture
from .memory import Memory
from .models import Budget, HTTPModel, MeteredModel, ReplayModel
from .report import write_report
from .store import Store


def load(path): return json.loads(Path(path).read_text())
def emit(value): print(json.dumps(value,indent=2,allow_nan=False))


def demo(store: Store, output: Path) -> dict:
    data_dir = output/"synthetic_data"
    dataset = Dataset(data_dir) if (data_dir/"manifest.json").exists() else make_fixture(data_dir)
    spec = ResearchSpec("A fixed two-percentage-point buffer reduces notional turnover without violating preregistered performance gates.",
                        dataset.id,"equal_weight",dataset.days[20],dataset.days[-1],bootstrap_samples=500)
    actions = [{"tool":"freeze_spec","arguments":asdict(spec)},
               {"tool":"register_strategy","arguments":{"kind":"builtin","name":"equal_weight","lookback":20,"buffer":0.02}},
               *[{"tool":name,"arguments":{}} for name in ("evaluate","challenge","decide")],
               {"tool":"remember","arguments":{"procedure":"cost_attribution","claims":[{"pointer":"/paper_eligible","equals":False}]}},
               {"tool":"finish","arguments":{}}]
    goal = "Compare notional turnover and order counts; challenge cost attribution and retain rejected findings."
    key = store.new_run(goal)
    agent = ResearchAgent(store,dataset,ReplayModel(actions))
    agent.execute(key)
    report = write_report(store,key,output/"research")
    transfer = Memory(store).retrieve("cost attribution research")
    summary = {"mode":"scripted engineering demonstration","run":key,"report":str(report.resolve()),
               "verified_memory_records":len(transfer),"retrieved_evidence":[r["evidence"] for r in transfer],
               "new_task":"Determine whether a new strategy's net improvement comes from modeled trading costs or signal quality.",
               "memory_procedure_transferred":bool(transfer),"paid_model_calls":0,"broker_orders":0,
               "learning_improvement_measured":False,"alpha_evidence":False}
    output.mkdir(parents=True,exist_ok=True)
    (output/"DEMO.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary


def seed_legacy(store: Store, root: Path) -> dict:
    baseline = load(root/"results/agent_v1/legacy_baseline.json")
    needed = ["results/experiments_2026-10-07/experiment_summary.json","results/experiments_2026-10-07/verification.json"]
    for name in needed:
        if file_hash(root/name)!=baseline[name]: raise GateError("Existing ETF evidence changed after the preservation baseline")
    summary,verification = [load(root/name) for name in needed]
    if verification["status"]!="passed" or summary["formal_data_gate_passed"]:
        raise GateError("Legacy evidence needs the preserved passed verifier and explicit proxy qualification")
    key = store.put("legacy_observation",{"quality":"proxy","source_hashes":{name:baseline[name] for name in needed},
                                         "qualified_alpha":False,"verification_status":"passed",
                                         "failed_practical_gates":summary["failed_practical_gates"],
                                         "primary_gain":summary["trials"]["primary_B2"]["net_sharpe"]-summary["trials"]["primary_B0"]["net_sharpe"],
                                         "notional_turnover_before":summary["trials"]["primary_B0"]["annual_turnover"],
                                         "notional_turnover_after":summary["trials"]["primary_B2"]["annual_turnover"],
                                         "filled_orders_before":summary["trials"]["primary_B0"]["orders_filled"],
                                         "filled_orders_after":summary["trials"]["primary_B2"]["orders_filled"]})
    memory = Memory(store)
    records = [memory.add(key,[{"pointer":"/qualified_alpha","equals":False}],procedure,
                          {"market":"US","frequency":"daily","quality":"proxy"}) for procedure in ("cost_attribution","notional_turnover","retain_rejections")]
    return {"evidence":key,"memory_records":records,"source":"preserved exploratory ETF research; not qualified alpha"}


def model_from_config(store,config,run_id):
    if not os.environ.get(config.get("api_key_env","")) and not config.get("local_no_auth",False):
        raise GateError("Model credential is missing; configure its named environment variable locally")
    if min(config.get("input_per_million",0),config.get("output_per_million",0))<=0 and not config.get("local_no_auth",False):
        raise GateError("Configure verified input/output prices before hosted model calls")
    identity = digest(config)
    previous = store.control(f"model_configuration:{run_id}")
    if previous and previous != identity: raise GateError("Resume must retain the pinned model/price configuration; use a new run for a change")
    store.set_control(f"model_configuration:{run_id}",identity)
    budget = Budget(store,"v1-research-demo",10)
    return MeteredModel(HTTPModel(config),budget,config["input_per_million"],config["output_per_million"],episode_id=run_id)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="quant-agent",description="Evidence-based research with verified memory and protected paper execution")
    parser.add_argument("--store",default=".quant-agent",help="Persistent SQLite/evidence directory")
    parser.add_argument("--model-env",type=Path,help="Load only the configured model key from a private local env file")
    sub = parser.add_subparsers(dest="command",required=True)
    p = sub.add_parser("doctor");p.add_argument("--config")
    p = sub.add_parser("model-smoke");p.add_argument("--model-config",required=True)
    p.add_argument("--case",choices=["json","workflow"],default="json")
    p = sub.add_parser("first-episode");p.add_argument("action",choices=["prepare","status","run","transfer","benchmark","paper-gate"])
    p.add_argument("--dataset");p.add_argument("--run");p.add_argument("--model-config");p.add_argument("--image")
    p.add_argument("--output",default="results/ordered_integration_2026-10-10/research")
    p = sub.add_parser("demo");p.add_argument("--output",default="results/agent_v1/demo")
    p = sub.add_parser("import-data");p.add_argument("directory")
    p = sub.add_parser("qualify-data");p.add_argument("directory");p.add_argument("--attestation",required=True);p.add_argument("--evidence-root",required=True)
    p = sub.add_parser("source-add");p.add_argument("path");p.add_argument("--title",required=True)
    p = sub.add_parser("memory");p.add_argument("query",nargs="?",default="research costs timing");p.add_argument("--seed-legacy",action="store_true")
    for name in ("research","work"):
        p = sub.add_parser(name);p.add_argument("--dataset",required=True);p.add_argument("--model-config",required=True)
        p.add_argument("--goal",required=True);p.add_argument("--image");p.add_argument("--resume");p.add_argument("--runs",type=int,default=1)
        p.add_argument("--output",default="results/agent_v1/research");p.add_argument("--paper-config")
    p = sub.add_parser("report");p.add_argument("run");p.add_argument("--output",default="results/agent_v1/research")
    p = sub.add_parser("runs")
    p = sub.add_parser("backup");p.add_argument("destination")
    p = sub.add_parser("benchmark");p.add_argument("action",choices=["prepare","preflight","run"]);p.add_argument("--suite");p.add_argument("--model-config");p.add_argument("--seed",type=int,default=20261009)
    p = sub.add_parser("learning-revision");p.add_argument("action",choices=["consolidate","prepare","preflight","run","status"])
    p.add_argument("--run");p.add_argument("--plan");p.add_argument("--model-config");p.add_argument("--seed",type=int,default=20261011)
    p.add_argument("--output",default="results/learning_revision_2026-10-11/campaign")
    p = sub.add_parser("research-task");p.add_argument("action",choices=["prepare","run","status"])
    p.add_argument("--input");p.add_argument("--session");p.add_argument("--model-config")
    p = sub.add_parser("tool-study");p.add_argument("action",choices=["prepare-training","train","prepare","preflight","run","status"])
    p.add_argument("--training");p.add_argument("--plan");p.add_argument("--model-config");p.add_argument("--dataset")
    p.add_argument("--output",default="results/tool_research_2026-10-11/campaign")
    p = sub.add_parser("paper-audit");p.add_argument("statement");p.add_argument("--source-file",required=True);p.add_argument("--dataset",required=True);p.add_argument("--paper-account",required=True)
    p = sub.add_parser("paper");p.add_argument("action",choices=["status","activate","cycle","pause","resume","watch","record-close","control"]);p.add_argument("--config",required=True)
    p.add_argument("--run");p.add_argument("--dataset");p.add_argument("--image")
    p.add_argument("--interval",type=int,default=30);p.add_argument("--iterations",type=int,default=0)
    p.add_argument("--asset-id");p.add_argument("--target-shares",type=int,choices=[-1,0,1],default=1)
    args = parser.parse_args(argv)
    store = None
    try:
        if args.model_env:
            configuration = getattr(args,"model_config",None) or getattr(args,"config",None)
            if not configuration:
                raise GateError("--model-env requires a model configuration")
            load_model_environment(args.model_env, load(configuration))
        if args.command=="doctor": emit(readiness(load(args.config) if args.config else None));return 0
        store = Store(args.store)
        if args.command=="model-smoke":
            config=load(args.model_config)
            if not config.get("local_no_auth",False) and (not os.environ.get(config.get("api_key_env","")) or min(config.get("input_per_million",0),config.get("output_per_million",0))<=0):
                raise GateError("Adapter validation requires a configured credential and verified positive token prices")
            model=MeteredModel(HTTPModel(config),Budget(store,"v1-smoke",5),config["input_per_million"],config["output_per_million"],max_decisions=1)
            expected={"adapter_ok":True} if args.case=="json" else {"tool":"finish","arguments":{}}
            response=model.generate(ModelRequest([{"role":"user","content":"Reply with exactly the JSON object "+canonical(expected)+", without any other text."}],300))
            try: passed=json.loads(response.content)==expected
            except ValueError: passed=False
            key=store.put("adapter_smoke",{"passed":passed,"case":args.case,"configuration":digest(config),
                    "model":config["model"],"adapter":config["adapter"],"input_tokens":response.input_tokens,
                    "output_tokens":response.output_tokens,"real_request":True,"created_at":utcnow(),
                    "served_model":response.metadata.get("served_model"),"request_id":response.metadata.get("request_id")})
            emit({"passed":passed,"receipt":key})
            return 0 if passed else 2
        elif args.command=="first-episode":
            from . import first_episode
            if args.action=="prepare":
                if not args.dataset: raise GateError("Provide --dataset for first-episode preparation")
                emit(first_episode.prepare(store,Dataset(args.dataset),Path(args.output)))
            else:
                if not args.run: raise GateError("Provide the preregistered first-episode --run")
                plan=first_episode.resolve_plan(store,args.run)
                if args.action=="status":emit(first_episode.status(store,plan))
                elif args.action=="paper-gate":emit(first_episode.paper_gate(store,plan))
                else:
                    if not args.model_config: raise GateError("Provide a pinned model configuration")
                    config=load(args.model_config)
                    first_episode.require_smokes(store,config)
                    if args.action=="benchmark":
                        emit(first_episode.benchmark(store,plan,config))
                        return 0
                    model=model_from_config(store,config,args.run if args.action=="run" else args.run+":transfer")
                    if args.action=="run":
                        if not args.dataset: raise GateError("Provide the exact preregistered --dataset")
                        emit(first_episode.execute(store,plan,Dataset(args.dataset),config,model,args.image))
                    else:emit(first_episode.transfer(store,plan,model))
        elif args.command=="learning-revision":
            from . import learning_revision
            if args.action=="status":
                if not args.plan:raise GateError("Provide the frozen revision --plan")
                emit(learning_revision.status(store,args.plan))
            else:
                if not args.model_config:raise GateError("Provide the same pinned model configuration")
                config=load(args.model_config)
                if args.action=="consolidate":
                    if not args.run:raise GateError("Provide a completed source research --run")
                    from .first_episode import require_smokes
                    from .memory_consolidation import consolidate
                    require_smokes(store,config)
                    model=model_from_config(store,config,args.run+":consolidation:v2")
                    emit(consolidate(store,args.run,model))
                elif args.action=="prepare":
                    if not args.run:raise GateError("Provide the source research --run")
                    emit(learning_revision.prepare(store,args.run,config,args.output,args.seed))
                elif args.action=="preflight":
                    if not args.plan:raise GateError("Provide the frozen revision --plan")
                    emit(learning_revision.preflight(store,args.plan,config))
                else:
                    if not args.plan:raise GateError("Provide the frozen revision --plan")
                    result=learning_revision.run(store,args.plan,config)
                    emit({k:result[k] for k in ("receipt","episodes","success_rates","semantic_rates","gates","learning_demonstrated","cost","paper_eligible")})
        elif args.command=="research-task":
            from .task_agent import prepare_session,execute_session
            from .procedural_memory import task_context,remember_trace
            if args.action=='prepare':
                if not args.input:raise GateError('Provide an immutable analytical --input JSON job')
                job=load(args.input);session=prepare_session(store,job,task_context(store,job))
                emit({'session':session,'job':store.control('tool_task_session:'+session)['job'],'model_calls':0})
            else:
                if not args.session:raise GateError('Provide the prepared --session')
                state=store.control('tool_task_session:'+args.session)
                if state is None:raise GateError('Unknown analytical session')
                if args.action=='status':emit(state)
                elif state['status']=='finished':emit({'receipt':state['result'],**store.get(state['result'])})
                else:
                    if not args.model_config:raise GateError('Provide --model-config for task execution')
                    from .first_episode import require_smokes
                    from .tool_evaluation import metered,check_budget
                    config=load(args.model_config);require_smokes(store,config)
                    pin='analytical_model:'+args.session
                    if store.control(pin,digest(config))!=digest(config):raise GateError('Task resume retains its model/prices')
                    if not check_budget(store,config,'v1-research-demo',1)['can_run']:raise GateError('Task does not fit remaining original caps')
                    store.set_control(pin,digest(config))
                    result=execute_session(store,args.session,metered(store,HTTPModel(config),config,'v1-research-demo',args.session))
                    memory=remember_trace(store,result['receipt']);emit({**result,'verified_procedural_memory':memory})
        elif args.command=="tool-study":
            from . import tool_evaluation
            if args.action=='status':
                if not args.plan:raise GateError('Provide frozen --plan')
                emit(tool_evaluation.status(store,args.plan))
            else:
                if not args.model_config:raise GateError('Provide the pinned --model-config')
                config=load(args.model_config)
                if args.action=='prepare-training':emit(tool_evaluation.prepare_training(store,config,args.output,args.dataset))
                elif args.action=='train':
                    if not args.training:raise GateError('Provide declared --training plan')
                    emit(tool_evaluation.train(store,args.training,config))
                elif args.action=='prepare':
                    if not args.training:raise GateError('Provide completed --training plan')
                    emit(tool_evaluation.prepare(store,args.training,config,args.output))
                elif args.action=='preflight':
                    if not args.plan:raise GateError('Provide frozen --plan')
                    emit(tool_evaluation.preflight(store,args.plan,config))
                else:
                    if not args.plan:raise GateError('Provide frozen --plan')
                    result=tool_evaluation.run(store,args.plan,config)
                    emit({k:result[k] for k in ('receipt','episodes','model_calls','success_rates','tool_completion_rates','gates','learning_demonstrated','cost','paper_eligible')})
        elif args.command=="demo": emit(demo(store,Path(args.output)))
        elif args.command=="import-data":
            dataset = Dataset(args.directory)
            key = store.put("data_audit",dataset.audit())
            store.set_control(f"dataset:{dataset.id}",str(dataset.directory))
            emit({"dataset_id":dataset.id,"audit":key,"qualification":dataset.qualification(store)})
        elif args.command=="qualify-data":
            attestation = load(args.attestation)
            docs = {name:Path(args.evidence_root)/path for name,path in attestation.pop("document_paths").items()}
            emit({"receipt":qualify(store,Dataset(args.directory),attestation,docs)})
        elif args.command=="source-add":
            text = Path(args.path).read_text()
            if len(text.encode())>100_000: raise GateError("Import a focused source excerpt <=100 KB")
            emit({"source":store.put("source",{"title":args.title,"text":text,"file_sha256":file_hash(Path(args.path)),"trust":"untrusted source material"})})
        elif args.command=="memory":
            emit(seed_legacy(store,Path.cwd()) if args.seed_legacy else Memory(store).retrieve(args.query))
        elif args.command in {"research","work"}:
            if not 1<=args.runs<=20: raise GateError("Bound each work invocation to 1–20 research runs")
            dataset = Dataset(args.dataset);config = load(args.model_config)
            results = []
            for index in range(args.runs):
                run = args.resume if index==0 and args.resume else store.new_run(args.goal)
                model = model_from_config(store,config,run)
                outcome = ResearchAgent(store,dataset,model,args.image).execute(run)
                report = write_report(store,run,Path(args.output)/run)
                result = {"run":run,"state":outcome["state"],"report":str(report.resolve())}
                if args.paper_config and store.get(outcome["decision"])["paper_eligible"]:
                    from .paper import PaperController
                    broker_config = load(args.paper_config)
                    controller = PaperController(store,None,broker_config["paper_account"],args.image)
                    release = controller.qualify_release(run)
                    store.set_control("paper_pending_release",release)
                    result["paper_release_queued"] = release
                results.append(result)
            emit(results)
        elif args.command=="report": emit({"report":str(write_report(store,args.run,args.output).resolve())})
        elif args.command=="runs": emit([dict(r) for r in store.db.execute("SELECT id,goal,state,created FROM runs ORDER BY created")])
        elif args.command=="backup": emit(store.backup(args.destination))
        elif args.command=="benchmark":
            if args.action=="prepare": emit({"suite":prepare_suite(store,args.seed),"episodes":240,"paid_calls":0})
            else:
                if not args.suite or not args.model_config: raise GateError("Provide the frozen suite and model configuration")
                config = load(args.model_config)
                emit(benchmark_preflight(store,args.suite,config) if args.action=="preflight" else {"evaluation":run_benchmark(store,args.suite,config)})
        elif args.command=="paper-audit":
            from .operations import audit_statement
            emit({"receipt":audit_statement(store,load(args.statement),Path(args.source_file),Dataset(args.dataset),args.paper_account)})
        else:
            from .ibkr import IBKRPaperBroker
            from .paper import PaperController
            config = load(args.config);broker = IBKRPaperBroker(config)
            try:
                controller = PaperController(store,broker,config["paper_account"],args.image)
                if args.action=="status":
                    if args.dataset: controller.refresh_actions(Dataset(args.dataset))
                    emit(controller.poll())
                elif args.action=="pause": controller.pause("Operator pause");emit({"paused":True})
                elif args.action=="resume": controller.resume();emit({"paused":False})
                elif args.action=="activate":
                    if not args.run: raise GateError("Provide the research run ID")
                    release = controller.qualify_release(args.run);controller.activate(release);emit({"release":release,"active":True})
                elif args.action=="control":
                    if not args.dataset or not args.asset_id: raise GateError("Engineering controls need qualified inputs and a stable security ID")
                    release=controller.engineering_control(Dataset(args.dataset),args.asset_id,args.target_shares)
                    controller.activate(release);emit({"release":release,"engineering_only":True,"alpha_claim":False})
                else:
                    if not args.dataset: raise GateError("Provide fresh qualified daily inputs")
                    if args.action=="record-close":
                        from .operations import record_close
                        emit({"close_receipt":record_close(controller,Dataset(args.dataset))})
                    elif args.action=="watch":
                        from .worker import watch
                        emit(watch(controller,args.dataset,args.interval,args.iterations))
                    else: emit(controller.cycle(Dataset(args.dataset)))
            finally: broker.close()
        return 0
    except (AgentError,OSError,ValueError,KeyError,TypeError) as exc:
        # Raw provider bodies, credential values and arbitrary code traces are
        # intentionally excluded from operator error reports.
        emit({"status":"blocked_or_failed","error":str(exc) if isinstance(exc,AgentError) else type(exc).__name__})
        return 2
    finally:
        if store: store.close()


if __name__=="__main__": raise SystemExit(main())
