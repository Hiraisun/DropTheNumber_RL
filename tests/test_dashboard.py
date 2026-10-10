import http.client
import json
import threading
from pathlib import Path

import pytest

from drop_the_number.dashboard.manager import Manager, check_config
from drop_the_number.dashboard.server import make_server
from drop_the_number.bridge import dispatch
from drop_the_number.agents.baselines import GreedyAgent
from drop_the_number.agents.evaluation import episode, evaluate

ROOT = Path(__file__).resolve().parents[1]


def config():
    return {**json.loads((ROOT / "configs/ppo.json").read_text()), "timesteps":128,"n_envs":1,"n_steps":32,
            "batch_size":32,"n_epochs":1,"hidden":[8],"checkpoint_steps":64,"eval_episodes":2,"threads":1,"max_steps":30}


def test_authenticated_api_and_request_retries(tmp_path):
    manager=Manager(tmp_path,start=False)
    manager.environment=lambda: {"ready":True}
    server=make_server(tmp_path,0,manager=manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    connection=http.client.HTTPConnection("127.0.0.1",server.server_port)
    def request(path, data=None, headers=None):
        connection.request("POST" if data is not None else "GET",path,json.dumps(data) if data is not None else None,headers or {})
        response=connection.getresponse();body=response.read()
        return response.status,dict(response.getheaders()),body
    try:
        assert request("/api/state")[0]==403
        status,headers,_=request("/");assert status==200
        cookie=headers["Set-Cookie"].split(";")[0]
        auth={"Cookie":cookie,"X-DTN-Token":cookie.split("=")[1],"Content-Type":"application/json"}
        payload={"request_id":"repeat-request-1","name":"test","config":config(),"auto_evaluate":False}
        assert request("/api/train",payload,{"Cookie":cookie})[0]==403
        assert request("/api/train",payload,{**auth,"Origin":"https://evil.example"})[0]==403
        status,_,body=request("/api/train",payload,auth);assert status==200
        first=json.loads(body)
        assert json.loads(request("/api/train",payload,auth)[2])==first
        assert len(manager.items("job"))==1
        assert request("/api/stop",{"id":"../external"},auth)[0]==400
        assert request("/api/state",headers={"Cookie":cookie,"Host":"evil.example"})[0]==403
        assert request("/../pyproject.toml")[0]==404
    finally:
        connection.close();server.shutdown();server.server_close();manager.close();manager.db.close()


def test_queue_cancel_reorder_and_crash_recovery(tmp_path):
    manager=Manager(tmp_path,start=False);manager.environment=lambda: {"ready":True}
    a=manager.enqueue_train({"config":config(),"auto_evaluate":False})["id"]
    b=manager.enqueue_train({"config":config(),"auto_evaluate":False})["id"]
    manager.reorder([b,a]);assert manager.get("job",b)["order"]==0
    manager.stop(a);assert manager.get("job",a)["status"]=="canceled"
    job=manager.get("job",b);job["status"]="running";manager.put("job",job)
    manager.db.close()
    restored=Manager(tmp_path,start=False)
    assert restored.get("job",b)["status"]=="interrupted"
    restored.db.close()


def test_final_conditions_reject_used_seeds_and_unknown_models(tmp_path):
    manager=Manager(tmp_path,start=False)
    data=json.loads((ROOT / "web/public/ai/ppo.json").read_text())
    model=manager.import_policy(data)["id"]
    used=data["metadata"]["training_seeds"][0]
    with pytest.raises(ValueError,match="使用済み"):
        manager.condition({"episodes":1,"seed_start":used,"max_steps":10,"purpose":"final"})
    condition=manager.condition({"episodes":1,"seed_start":used,"max_steps":10,"purpose":"comparison"})["id"]
    with pytest.raises(ValueError,match="重複"):
        manager.enqueue_evaluation({"models":[model],"condition":condition})
    with pytest.raises(ValueError):manager.safe_path("../outside.zip")
    manager.db.close()


def test_replay_seek_matches_every_prefix_and_is_transactional():
    _,session=episode(GreedyAgent(),789,max_steps=20)
    from drop_the_number.replay import reconstruct
    for index in (0,1,7,19,20):
        partial={**session,"actions":session["actions"][:index]};partial.pop("final")
        game,_=reconstruct(partial)
        result=json.loads(dispatch(json.dumps({"command":"seek","session":session,"index":index})))
        assert result["state"]==game.snapshot() and result["diagnostic"]
    before=json.loads(dispatch('{"command":"export"}'))
    with pytest.raises(ValueError):dispatch(json.dumps({"command":"seek","session":session,"index":21}))
    assert json.loads(dispatch('{"command":"export"}'))==before


def test_partial_evaluation_reports_actual_completed_count():
    rows=[]
    report=evaluate(lambda seed:GreedyAgent(),[1,2,3],max_steps=5,on_episode=lambda i,row,session:rows.append(row),stopped=lambda:len(rows)==1)
    assert not report["complete"] and len(report["episodes"])==1
    assert report["median_score"]==int(rows[0]["score"])
    assert report["reach_rates"]["128"] in (0,1)


def test_atomic_write_survives_a_concurrent_windows_reader(tmp_path):
    from drop_the_number.agents.files import atomic_json
    path=tmp_path / "status.json"
    atomic_json(path,{"phase":"old"})
    reader=path.open("rb")
    release=threading.Timer(.15,reader.close)
    release.start()
    try:
        atomic_json(path,{"phase":"new"})
        assert json.loads(path.read_text(encoding="utf-8"))=={"phase":"new"}
    finally:
        release.join()
        reader.close()


@pytest.mark.parametrize("key,value",[("learning_rate",float("nan")),("n_envs",True),("hidden",[999]),("max_steps",0)])
def test_config_rejects_invalid_inputs(key,value):
    with pytest.raises(ValueError):check_config({**config(),key:value})


def test_training_stop_at_update_boundary_and_continue(tmp_path):
    pytest.importorskip("stable_baselines3")
    from drop_the_number.agents.training import train
    from drop_the_number.agents.policy import Policy
    stop=False
    def progress(row):
        nonlocal stop
        if row["phase"]=="更新完了":stop=True
    output=tmp_path / "first"
    train(config(),output,stopped=lambda:stop,progress_callback=progress,reserved_seeds=[config()["seed"]])
    data=json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert data["metadata"]["timesteps"]==32
    assert config()["seed"] not in data["metadata"]["training_seeds"]
    assert not (output / "best.json").exists()
    continued=tmp_path / "continued"
    train({**config(),"seed":456,"timesteps":32},continued,resume=output / "latest.zip",parent_metadata={**data["metadata"],"model_id":"parent"})
    result=json.loads((continued / "best.json").read_text(encoding="utf-8"))
    assert result["metadata"]["initial_timesteps"]==32 and result["metadata"]["timesteps"]==64
    assert result["metadata"]["parent"]=="parent"
    assert set(data["metadata"]["training_seeds"]) <= set(result["metadata"]["training_seeds"])
    Policy(result)
    baselines=json.loads((continued / "baselines.json").read_text(encoding="utf-8"))
    assert baselines["seeds"]==result["metadata"]["validation_seeds"]
    assert all(report["complete"] for report in baselines["agents"].values())
