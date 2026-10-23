"""Full candidate schema/import/compiler child with quiet bounded DB connections."""
from __future__ import annotations

import json
import subprocess


CLASSES = {"OperationalError", "IntegrityError", "DataError", "ProgrammingError", "InterfaceError", "InternalError",
           "RuntimeError", "ValueError", "TypeError", "ImportError", "ModuleNotFoundError", "PermissionError",
           "OSError", "FileNotFoundError", "TimeoutError", "SyntaxError", "AssertionError", "OtherError"}


class SchemaError(RuntimeError):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details


def program(candidate, *, migrate):
    # This follows the reviewed 094382a wrapper, correcting CWD/module resolution
    # to the complete staged candidate rather than the installed old package.
    return '''import os,sys,json,pathlib,py_compile,socket
receipt_fd=os.dup(1);quiet=os.open(os.devnull,os.O_WRONLY)
os.dup2(quiet,1);os.dup2(quiet,2);os.close(quiet)
report={"ok":False,"stage":"bootstrap","exception_class":None,"mysql_code":None}
pymysql=None
try:
 root=pathlib.Path(CANDIDATE).resolve();sys.path.insert(0,str(root));sys.dont_write_bytecode=True
 if pathlib.Path.cwd().resolve()!=root:raise RuntimeError("CandidateCwdMismatch")
 if MIGRATE:
  import pymysql
  original=pymysql.connect
  def bounded(*a,**kw):
   if kw.get("init_command"):raise RuntimeError("UnexpectedInitializer")
   kw.update(connect_timeout=3,read_timeout=30,write_timeout=30,
             init_command="SET SESSION lock_wait_timeout=3, innodb_lock_wait_timeout=3")
   return original(*a,**kw)
  pymysql.connect=bounded
  report["stage"]="full_schema"
  from app import schema
  from data_pipeline import init_schema
  for module in (schema,init_schema):
   if not pathlib.Path(module.__file__).resolve().is_relative_to(root):raise RuntimeError("WrongSchemaSource")
  schema.main()
 else:
  report["stage"]="compile"
  sys.pycache_prefix=str(root.parent/"compiled")
  for package in ("app","data_pipeline"):
   for source in sorted((root/package).rglob("*.py")):
    py_compile.compile(str(source),doraise=True)
  report["stage"]="imports"
  def forbidden(*a,**kw):raise RuntimeError("NetworkForbiddenDuringImport")
  socket.socket.connect=forbidden;socket.socket.connect_ex=forbidden;socket.getaddrinfo=forbidden
  from app import server,worker,kalshi_perps_trading,kalshi_perps_orders_repository,kalshi_perps_trading_client
  for module in (server,worker,kalshi_perps_trading,kalshi_perps_orders_repository,kalshi_perps_trading_client):
   if not pathlib.Path(module.__file__).resolve().is_relative_to(root):raise RuntimeError("WrongImportSource")
 report["ok"]=True
except BaseException as exc:
 name=type(exc).__name__;report["exception_class"]=name if name in ALLOWED_CLASSES else "OtherError"
 if pymysql is not None and isinstance(exc,pymysql.err.Error) and exc.args and type(exc.args[0]) is int:
  report["mysql_code"]=exc.args[0] if 0<=exc.args[0]<=65535 else None
os.write(receipt_fd,(json.dumps(report,separators=(",",":"))+"\\n").encode());os.close(receipt_fd)
raise SystemExit(0 if report["ok"] else 1)
'''.replace("CANDIDATE", repr(str(candidate))).replace("MIGRATE", repr(migrate)).replace("ALLOWED_CLASSES", repr(sorted(CLASSES)))


def run(python, candidate, env, *, migrate):
    child_env = {name: env[name] for name in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE", "APP_SECRET_KEY") if name in env}
    child_env.update(PATH="/usr/bin:/bin", LANG="C.UTF-8", TZ="UTC", PYTHONDONTWRITEBYTECODE="1",
                     AWS_EC2_METADATA_DISABLED="true", AWS_SHARED_CREDENTIALS_FILE="/dev/null", AWS_CONFIG_FILE="/dev/null",
                     TAU_KALSHI_PERPS_ENABLED="0", TAU_KALSHI_PERPS_LIVE_ENABLED="0", APP_DEV_LOGIN="0")
    try:
        response = subprocess.run([python, "-I", "-B", "-c", program(candidate, migrate=migrate)], cwd=candidate,
                                  env=child_env, capture_output=True, timeout=120 if migrate else 60)
        if len(response.stdout) > 2048:
            raise ValueError()
        report = json.loads(response.stdout)
        if (set(report) != {"ok", "stage", "exception_class", "mysql_code"} or type(report["ok"]) is not bool
                or report["stage"] not in {"bootstrap", "full_schema", "compile", "imports"}
                or report["exception_class"] not in {None, *CLASSES}
                or report["mysql_code"] is not None and (type(report["mysql_code"]) is not int or not 0 <= report["mysql_code"] <= 65535)):
            raise ValueError()
        if response.returncode or not report["ok"]:
            raise SchemaError("full_schema_failed" if migrate else "candidate_validation_failed", report)
        return report
    except SchemaError:
        raise
    except subprocess.TimeoutExpired:
        raise SchemaError("schema_or_validation_timeout", {"stage": "child", "exception_class": "TimeoutError", "mysql_code": None}) from None
    except Exception:
        raise SchemaError("schema_or_validation_failed") from None
