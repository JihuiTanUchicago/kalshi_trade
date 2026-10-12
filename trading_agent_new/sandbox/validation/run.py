"""Run and persist authentic container checks against a pinned local image."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,importlib.util,json,os,subprocess,sys,time,unittest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--image',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    os.environ['QUANT_SANDBOX_IMAGE']=args.image
    project=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(project/'src'))
    path=project/'tests/test_sandbox_integration.py'
    spec=importlib.util.spec_from_file_location('actual_sandbox_tests',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Recorder(unittest.TextTestResult):
        def startTest(self,test): self.started=time.monotonic();super().startTest(test)
        def addSuccess(self,test):
            cases.append({'test':test.id(),'status':'passed','seconds':time.monotonic()-self.started});super().addSuccess(test)
        def addFailure(self,test,err):
            cases.append({'test':test.id(),'status':'failed','seconds':time.monotonic()-self.started});super().addFailure(test,err)
        def addError(self,test,err):
            cases.append({'test':test.id(),'status':'error','seconds':time.monotonic()-self.started});super().addError(test,err)
        def addSkip(self,test,reason): cases.append({'test':test.id(),'status':'skipped','reason':reason});super().addSkip(test,reason)
    cases=[]
    started=datetime.now(timezone.utc).isoformat()
    result=unittest.TextTestRunner(verbosity=2,resultclass=Recorder).run(unittest.defaultTestLoader.loadTestsFromModule(module))
    version=json.loads(subprocess.check_output(['docker','version','--format','{{json .}}'],text=True))
    image=json.loads(subprocess.check_output(['docker','image','inspect',args.image],text=True))[0]
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    payload={'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'image':args.image,
             'image_architecture':image['Architecture'],'docker_client':version['Client']['Version'],
             'docker_server':version['Server']['Version'],'tests_run':result.testsRun,'failures':len(result.failures),
             'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful() and not result.skipped,
             'cases':cases,'test_source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'actual_container_execution':True,'synthetic_inputs':True,'paid_model_calls':0,'broker_orders':0,
             'scope':'Declared container/API/resource/replay controls; not proof against all container/kernel exploits.'}
    output.write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps({'passed':payload['passed'],'tests':result.testsRun,'evidence':str(output.resolve())},indent=2))
    return 0 if payload['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
