"""Persistent serial queue and immutable model inventory."""
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from drop_the_number.agents.policy import Policy
from drop_the_number.agents.files import atomic_json as write


def read(path, fallback=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise ValueError("IDが不正です。")
    return value


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}は{low}～{high}の整数です。")
    return value


def check_config(config):
    # Keep API validation independent of optional scientific packages.
    if not isinstance(config, dict) or config.get("schema") != "drop-number/train-v1" or config.get("algorithm") != "ppo":
        raise ValueError("学習設定が不正です。")
    for key, low, high in (("timesteps",1,100_000_000),("n_envs",1,32),("n_steps",2,8192),
                          ("batch_size",2,8192),("n_epochs",1,100),("checkpoint_steps",1,10_000_000),
                          ("eval_episodes",1,1000),("threads",1,32),("max_steps",1,10000),("seed",0,2**32-1)):
        integer(config.get(key), low, high, key)
    integer(config.get("eval_seed_start"), 0, 2**32-config["eval_episodes"], "検証seed")
    if config["batch_size"] > config["n_steps"] * config["n_envs"]:
        raise ValueError("batch_sizeは環境数×ロールアウト手数以下にしてください。")
    for key, low, high in (("learning_rate",1e-7,.1),("gamma",.01,1),("ent_coef",0,1)):
        value = config.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key}の範囲が不正です。")
    hidden = config.get("hidden")
    if not isinstance(hidden,list) or not 1 <= len(hidden) <= 3 or any(type(n) is not int or not 1 <= n <= 128 for n in hidden):
        raise ValueError("隠れ層は1～3層、各1～128ユニットです。")
    if config.get("reward") not in ("log_score","score"):
        raise ValueError("報酬方式が不正です。")


class Manager:
    def __init__(self, root, *, start=True):
        self.root = Path(root).resolve()
        self.storage = self.root / "artifacts" / "gui"
        self.runs = self.storage / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.storage / "manager.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, kind TEXT, data TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, response TEXT)")
        self.process = None
        self.active_id = None
        self.closing = False
        self.wake = threading.Event()
        for job in self.items("job"):
            if job["status"] in ("running", "stopping"):
                job["status"] = "interrupted"
                job["error"] = "管理サーバーの終了で中断しました。保存済みモデルから追加学習できます。"
                self.put("job", job)
                self.scan_models(job)
        if not self.items("condition"):
            self.put("condition", {"id":"validation", "name":"定期検証", "purpose":"validation", "seeds":list(range(1_000_000_000,1_000_000_016)), "max_steps":1000})
            self.put("condition", {"id":"comparison", "name":"比較検証・64ゲーム", "purpose":"comparison", "seeds":list(range(2_000_000_000,2_000_000_064)), "max_steps":1000})
        if start:
            threading.Thread(target=self.loop, daemon=True).start()

    def put(self, kind, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?)", (data["id"], kind, json.dumps(data,ensure_ascii=False)))
            self.db.commit()

    def items(self, kind):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM items WHERE kind=? ORDER BY rowid", (kind,))]

    def get(self, kind, key):
        identifier(key)
        with self.lock:
            row = self.db.execute("SELECT data FROM items WHERE id=? AND kind=?",(key,kind)).fetchone()
        if row is None:
            raise ValueError("指定した記録がありません。")
        return json.loads(row[0])

    def deduplicate(self, key, action):
        if not isinstance(key,str) or not 8 <= len(key) <= 100:
            raise ValueError("要求IDが不正です。")
        with self.lock:
            previous = self.db.execute("SELECT response FROM requests WHERE key=?",(key,)).fetchone()
            if previous:
                return json.loads(previous[0])
            result = action()
            self.db.execute("INSERT INTO requests VALUES (?,?)",(key,json.dumps(result)))
            self.db.commit()
            return result

    def new_id(self, prefix):
        return prefix + "-" + secrets.token_hex(6)

    def safe_path(self, relative):
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root / "artifacts"):
            raise ValueError("管理対象外のファイルです。")
        return resolved

    def model_data(self, model):
        return read(self.safe_path(model["path"]))

    def reserved(self):
        return set(seed for condition in self.items("condition") for seed in condition["seeds"])

    def enqueue_train(self, data):
        if not self.environment()["ready"]:
            raise ValueError("先に環境を準備してください。")
        config = data.get("config")
        check_config(config)
        config = dict(config)
        parent = None
        if data.get("parent"):
            model = self.get("model", data["parent"])
            if not model.get("zip"):
                raise ValueError("追加学習には最適化状態付きモデルが必要です。推論用JSONでは追加学習できません。")
            metadata = self.model_data(model).get("metadata", {})
            original = metadata["config"]
            for key in original:
                if key not in ("timesteps","seed","eval_seed_start","eval_episodes","checkpoint_steps") and config.get(key) != original[key]:
                    raise ValueError("追加学習ではモデル構成・報酬・PPO設定を変更できません。設定を引き継いでください。")
            parent = {"zip":str(self.safe_path(model["zip"])), "metadata":{**metadata,"model_id":model["id"]}}
        name = str(data.get("name") or "PPO学習").strip()[:100]
        try:
            revision = subprocess.run(["git","rev-parse","HEAD"],cwd=self.root,capture_output=True,text=True,timeout=5).stdout.strip()
            dirty = subprocess.run(["git","status","--porcelain","--","src","configs"],cwd=self.root,capture_output=True,text=True,timeout=5).stdout.strip()
            if dirty:
                revision += "-dirty"
        except (OSError, subprocess.TimeoutExpired):
            revision = None
        reserved = self.reserved() | set(range(config["eval_seed_start"],config["eval_seed_start"]+config["eval_episodes"]))
        fingerprint=hashlib.sha256()
        for source in sorted((self.root / "src").rglob("*.py")):
            fingerprint.update(str(source.relative_to(self.root)).replace("\\","/").encode())
            fingerprint.update(source.read_bytes())
        parent_seeds = set((parent or {}).get("metadata",{}).get("training_seeds",[]))
        if parent_seeds & set(range(config["eval_seed_start"], config["eval_seed_start"]+config["eval_episodes"])):
            raise ValueError("親モデルの学習seedと定期検証seedが重複します。")
        config["seed"] = int(config["seed"])
        identifier_ = self.new_id("train")
        job = {"id":identifier_,"kind":"train","name":name,"status":"queued","created":time.time(),
               "config":config,"parent":data.get("parent"),"order":time.time(),"note":"",
               "auto_evaluate": bool(data.get("auto_evaluate",True))}
        directory = self.runs / identifier_
        directory.mkdir()
        write(directory / "job.json", {**job,"parent":parent,"reserved_seeds":sorted(reserved),"code_revision":revision,"code_sha256":fingerprint.hexdigest()})
        self.put("job",job)
        self.wake.set()
        return {"id":identifier_}

    def condition(self, data):
        count = integer(data.get("episodes"),1,1000,"ゲーム数")
        start = integer(data.get("seed_start"),0,2**32-count,"seed")
        limit = integer(data.get("max_steps"),1,10000,"手数上限")
        purpose = data.get("purpose")
        if purpose not in ("validation","comparison","final"):
            raise ValueError("検証の目的が不正です。")
        seeds = list(range(start,start+count))
        # Frozen job reservations cannot safely adopt new seed sets while a training job exists.
        if any(j["kind"]=="train" and j["status"] in ("queued","running","stopping") for j in self.items("job")):
            raise ValueError("学習ジョブが完了してから新しい検証条件を登録してください。既存条件は使えます。")
        if purpose == "final":
            if set(seeds) & self.reserved():
                raise ValueError("最終評価には登録済み条件と重複しないseedを指定してください。")
            for model in self.items("model"):
                metadata = self.model_data(model).get("metadata",{})
                if set(seeds) & set(metadata.get("training_seeds",[]) + metadata.get("validation_seeds",[])):
                    raise ValueError("使用済みseedです。最終評価には新しいseedを指定してください。")
        item = {"id":self.new_id("condition"),"name":str(data.get("name") or purpose)[:100],"purpose":purpose,
                "seeds":seeds,"max_steps":limit}
        self.put("condition", item)
        return {"id":item["id"]}

    def enqueue_evaluation(self, data):
        condition = self.get("condition",data.get("condition"))
        keys = data.get("models",[])
        if not isinstance(keys,list) or not 1 <= len(keys) <= 30 or len(set(keys)) != len(keys):
            raise ValueError("検証対象を1～30件選択してください。")
        agents = []
        for key in keys:
            if key in ("random","greedy"):
                agents.append({"id":key,"name":"ランダム" if key=="random" else "1手先評価"})
            else:
                model = self.get("model",key)
                metadata = self.model_data(model).get("metadata",{})
                history = metadata.get("training_seeds",[]) + (metadata.get("validation_seeds",[]) if condition["purpose"]=="final" else [])
                overlap = sorted(set(condition["seeds"]) & set(history))
                if overlap:
                    raise ValueError("対象モデルの使用seedと重複します。別の条件を選んでください。")
                agents.append({"id":key,"name":model["name"],"path":str(self.safe_path(model["path"])),"sha256":model["sha256"],
                               "seed_history_known":metadata.get("seed_history_known","training_seeds" in metadata),"overlapping_seeds":overlap})
        job = {"id":self.new_id("eval"),"kind":"evaluate","name":condition["name"],"condition":condition,
               "status":"queued","created":time.time(),"order":time.time(),"note":"","models":keys}
        directory = self.runs / job["id"]
        directory.mkdir()
        write(directory / "job.json", {**job,"agents":agents})
        self.put("job",job)
        self.wake.set()
        return {"id":job["id"]}

    def register_model(self, key, path, job_id, label, zip_path=None):
        data = read(path)
        Policy(data)
        metadata = data.get("metadata",{})
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        model = {"id":key,"job":job_id,"name":label,"path":str(path.relative_to(self.root)),
                 "zip":str(zip_path.relative_to(self.root)) if zip_path and zip_path.exists() else None,
                 "sha256":sha,"timesteps":metadata.get("timesteps",0),"created":path.stat().st_mtime,
                 "parent":metadata.get("parent"),"seed_history_known":metadata.get("seed_history_known","training_seeds" in metadata)}
        self.put("model",model)

    def scan_models(self, job):
        if job["kind"] != "train":
            return
        directory = self.runs / job["id"] / "training"
        if not directory.exists():
            return
        known={model["id"] for model in self.items("model")}
        for path in directory.glob("step-*.json"):
            if not re.fullmatch(r"step-\d+\.json",path.name):
                continue
            key = job["id"] + "-" + path.stem
            if key in known:
                continue
            self.register_model(key,path,job["id"],job["name"] + " / " + path.stem[5:] + "手",path.with_suffix(".zip"))
            known.add(key)
        progress = read(directory / "progress.json",[])
        if progress:
            job["latest"] = job["id"] + "-" + progress[-1]["checkpoint"]
            valid = [r for r in progress if r.get("validation_complete") and r.get("validation_mean_score") is not None]
            if valid:
                best = max(valid,key=lambda r:r["validation_mean_score"])
                job["best"] = job["id"] + "-" + best["checkpoint"]
                job["best_score"] = best["validation_mean_score"]
            self.put("job",job)

    def importable(self):
        directory = self.root / "artifacts" / "rl"
        if not directory.exists():
            return []
        return [p.name for p in directory.iterdir() if p.is_dir() and (p / "best.json").exists()]

    def import_existing(self, name):
        identifier(name)
        if name not in self.importable():
            raise ValueError("取込対象の実験がありません。")
        key = "import-" + hashlib.sha256(name.encode()).hexdigest()[:12]
        if any(j["id"]==key for j in self.items("job")):
            return {"id":key}
        source = self.root / "artifacts" / "rl" / name
        if not source.resolve().is_relative_to(self.root / "artifacts" / "rl"):
            raise ValueError("取込元は管理対象ディレクトリ内にしてください。")
        data = read(source / "best.json")
        Policy(data)
        metadata = data.get("metadata",{})
        job = {"id":key,"kind":"train","name":name,"status":"imported","created":time.time(),
               "config":metadata.get("config",{}),"note":"既存実験。保存されていない途中モデル・内部指標は記録なし。",
               "source":name,"order":0}
        directory = self.runs / key / "training"
        directory.mkdir(parents=True)
        import shutil
        for stem in ("best","latest"):
            if (source / f"{stem}.json").exists():
                shutil.copyfile(source / f"{stem}.json",directory / f"{stem}.json")
                checkpoint = source / f"{stem}.zip"
                if checkpoint.exists():
                    shutil.copyfile(checkpoint,directory / f"{stem}.zip")
                self.register_model(key+"-"+stem,directory / f"{stem}.json",key,name+" / "+stem,directory / f"{stem}.zip")
                job[stem] = key+"-"+stem
        for filename in ("config.json","progress.json","validation.json"):
            if (source / filename).exists():
                shutil.copyfile(source / filename,directory / filename)
        self.put("job",job)
        return {"id":key}

    def import_policy(self, data):
        Policy(data)
        key = self.new_id("actor")
        directory = self.runs / key
        directory.mkdir()
        write(directory / "actor.json",data)
        self.register_model(key,directory / "actor.json",None,str(data.get("name") or "取込モデル")[:100])
        return {"id":key}

    def stop(self, key, force=False):
        with self.lock:
            return self._stop_locked(key, force)

    def _stop_locked(self, key, force=False):
        job = self.get("job",key)
        if job["status"]=="queued":
            job["status"]="canceled"
        elif job["status"] in ("running","stopping"):
            (self.runs / key / "stop").touch()
            job["status"]="stopping"
            if force and self.process and self.active_id==key:
                self.process.terminate()
                job["forced"] = True
        self.put("job",job)
        return {"id":key}

    def reorder(self, keys):
        queued = [j for j in self.items("job") if j["status"]=="queued"]
        if not isinstance(keys,list) or set(keys)!=set(j["id"] for j in queued) or len(keys)!=len(queued):
            raise ValueError("キューの状態が変わりました。更新してください。")
        for index,key in enumerate(keys):
            job = self.get("job",key)
            job["order"]=index
            self.put("job",job)
        return {"ok":True}

    def environment(self):
        python = self.root / ".venv" / "Scripts" / "python.exe" if os.name=="nt" else self.root / ".venv" / "bin" / "python"
        # Distribution metadata presence avoids importing Torch into the API process.
        site = self.root / ".venv" / "Lib" / "site-packages" if os.name=="nt" else next((self.root / ".venv" / "lib").glob("python*/site-packages"),self.root / "missing")
        rl = site.exists() and all(any(site.glob(name+"-*.dist-info")) for name in ("torch","stable_baselines3","gymnasium","numpy"))
        built = (self.root / "web" / "dist-local" / "dashboard.html").exists()
        import shutil
        return {"python":python.exists(),"rl":rl,"built":built,"ready":python.exists() and rl and built,
                "uv": bool(shutil.which("uv")),"node":bool(shutil.which("node")),"npm":bool(shutil.which("npm.cmd" if os.name=="nt" else "npm"))}

    def setup(self):
        if any(j["kind"]=="setup" and j["status"] in ("running","queued") for j in self.items("job")):
            raise ValueError("環境準備は実行中です。")
        job={"id":self.new_id("setup"),"kind":"setup","name":"環境準備","status":"queued","created":time.time(),"order":time.time(),"note":""}
        (self.runs / job["id"]).mkdir()
        self.put("job",job)
        self.wake.set()
        return {"id":job["id"]}

    def loop(self):
        while not self.closing:
            queued = sorted([j for j in self.items("job") if j["status"]=="queued"],key=lambda j:j["order"])
            if not queued:
                self.wake.wait(1)
                self.wake.clear()
                continue
            with self.lock:
                job = self.get("job",queued[0]["id"])
                if job["status"] != "queued":
                    continue
                self.active_id=job["id"]
                job.update(status="running",started=time.time())
                self.put("job",job)
            directory=self.runs / job["id"]
            env=os.environ.copy()
            env["PYTHONPATH"]=str(self.root / "src")
            env["PYTHONUNBUFFERED"]="1"
            env["PYTHONIOENCODING"]="utf-8"
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
            try:
                with (directory / "worker.log").open("w",encoding="utf-8") as log:
                    if job["kind"]=="setup":
                        import shutil
                        commands=[([shutil.which("uv") or "uv","sync","--frozen","--extra","rl"],self.root),
                                  ([shutil.which("npm.cmd" if os.name=="nt" else "npm") or "npm","ci"],self.root / "web"),
                                  ([shutil.which("npm.cmd" if os.name=="nt" else "npm") or "npm","run","build:local"],self.root / "web")]
                        for command,cwd in commands:
                            if (directory / "stop").exists():
                                break
                            write(directory / "status.json",{"phase":" ".join(command[1:])})
                            # Only these fixed npm commands use cmd.exe on Windows;
                            # shell=True lets Python quote the space-containing npm.cmd path correctly.
                            shell = os.name=="nt" and str(command[0]).endswith(".cmd")
                            self.process=subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=creationflags,shell=shell)
                            if self.process.wait()!=0:
                                raise RuntimeError("環境準備に失敗しました。ログを確認してください。")
                        write(directory / "result.json",{"status":"stopped" if (directory / "stop").exists() else "completed"})
                    else:
                        python=self.root / ".venv" / ("Scripts/python.exe" if os.name=="nt" else "bin/python")
                        self.process=subprocess.Popen([str(python),"-m","drop_the_number.dashboard.worker",str(directory)],cwd=self.root,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=creationflags)
                        while self.process.poll() is None:
                            with self.lock:
                                current=self.get("job",job["id"])
                                self.scan_models(current)
                            time.sleep(.5)
                current=self.get("job",job["id"])
                result=read(directory / "result.json",{"status":"interrupted","error":"プロセスが終了しました。直近の正常保存を使用できます。"})
                current.update(result)
                current["ended"]=time.time()
                self.put("job",current)
                self.scan_models(current)
                if current["kind"]=="train" and current["status"]=="completed" and current.get("auto_evaluate") and current.get("best"):
                    self.enqueue_evaluation({"condition":"comparison","models":[current["best"],"random","greedy"]})
            except Exception as error:
                current=self.get("job",job["id"])
                current.update(status="failed",error=str(error),ended=time.time())
                self.put("job",current)
            finally:
                self.process=None
                self.active_id=None

    def state(self):
        jobs=self.items("job")
        for job in jobs:
            directory=self.runs / job["id"]
            job["progress"]=read(directory / "status.json",{})
            job["history"]=read(directory / "training" / "progress.json",[])
            baselines=read(directory / "training" / "baselines.json")
            if baselines:
                job["baselines"]={"seeds":baselines["seeds"],"max_steps":baselines["max_steps"],
                                  "agents":{key:{"mean_score":report["mean_score"],"complete":report["complete"]} for key,report in baselines["agents"].items()}}
        return {"environment":self.environment(),"jobs":jobs,"models":self.items("model"),"conditions":self.items("condition"),"importable":self.importable()}

    def detail(self, key):
        job=self.get("job",key)
        directory=self.runs / key
        log_path=directory / "worker.log"
        log=log_path.read_text(encoding="utf-8",errors="replace")[-20000:] if log_path.exists() else ""
        updates=directory / "training" / "updates.jsonl"
        metrics=[]
        if updates.exists():
            for line in updates.read_text(encoding="utf-8").splitlines()[-200:]:
                try:
                    metrics.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # The worker may currently be appending this last line.
        return {"job":job,"report":read(directory / "evaluation.json"),"log":log,"updates":metrics,
                "metadata":read(directory / "training" / "config.json")}

    def close(self):
        self.closing=True
        if self.active_id:
            self.stop(self.active_id)
        self.wake.set()
