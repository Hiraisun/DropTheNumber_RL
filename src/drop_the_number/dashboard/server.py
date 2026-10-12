"""Authenticated loopback HTTP service; training never runs in the API process."""
import argparse
import csv
import html
import io
import json
import mimetypes
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .manager import Manager, identifier, integer, read


def make_server(root, port=8765, *, manager=None):
    manager = manager or Manager(root)
    root = Path(root).resolve()
    token = secrets.token_hex(32)
    built = root / "web" / "dist-local"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data, mime="application/json; charset=utf-8", status=200, filename=None, cookie=False):
            if isinstance(data,(dict,list)):
                data=json.dumps(data,ensure_ascii=False,allow_nan=False)
            if isinstance(data,str):
                data=data.encode("utf-8")
            self.send_response(status)
            for key,value in {"Content-Type":mime,"Content-Length":str(len(data)),"Cache-Control":"no-store",
                              "X-Content-Type-Options":"nosniff","X-Frame-Options":"SAMEORIGIN","Referrer-Policy":"same-origin"}.items():
                self.send_header(key,value)
            if cookie:
                self.send_header("Set-Cookie",f"dtn_session={token}; HttpOnly; SameSite=Strict; Path=/")
            if filename:
                self.send_header("Content-Disposition",f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self, mutation=False):
            expected=f"127.0.0.1:{self.server.server_port}"
            origin=self.headers.get("Origin")
            return (self.headers.get("Host")==expected and (not origin or origin=="http://"+expected)
                    and f"dtn_session={token}" in self.headers.get("Cookie","").split("; ")
                    and (not mutation or secrets.compare_digest(self.headers.get("X-DTN-Token",""),token)))

        def replay(self, query):
            key=identifier(query["job"][0]);agent=identifier(query["agent"][0])
            index=integer(int(query["episode"][0]),0,999,"ゲーム番号")
            job=manager.get("job",key)
            if agent not in job.get("models",[]):
                raise ValueError("検証対象が不正です。")
            session=read(manager.runs / key / f"replay-{agent}-{index}.json")
            if session is None:
                raise ValueError("完了したプレイ記録がありません。")
            return session

        def do_GET(self):
            try:
                parts=urlsplit(self.path);path=parts.path;query=parse_qs(parts.query)
                if self.headers.get("Host")!=f"127.0.0.1:{self.server.server_port}":
                    self.send({"error":"接続先が不正です。"},status=403);return
                if path.startswith("/api/"):
                    if not self.authorized():
                        self.send({"error":"管理画面を開き直してください。"},status=403);return
                    if path=="/api/state":
                        self.send(manager.state())
                    elif path=="/api/defaults":
                        self.send(read(root / "configs" / "ppo.json"))
                    elif path.startswith("/api/job/"):
                        self.send(manager.detail(path.split("/")[-1]))
                    elif path=="/api/view":
                        if "model" in query:
                            model=manager.get("model",query["model"][0])
                            seed=integer(int(query.get("seed",["2000000000"])[0]),0,2**32-1,"seed")
                            self.send({"policy":manager.model_data(model),"seed":seed})
                        else:
                            self.send({"session":self.replay(query)})
                    elif path=="/api/export/replay":
                        self.send(self.replay(query),filename="replay.json")
                    elif path.startswith("/api/export/model/"):
                        model=manager.get("model",path.split("/")[-1])
                        self.send(manager.model_data(model),filename=model["id"]+".json")
                    elif path.startswith("/api/export/report/"):
                        key=identifier(path.split("/")[-1]);report=manager.detail(key)["report"]
                        if report is None:
                            raise ValueError("検証結果がありません。")
                        format_=query.get("format",["json"])[0]
                        if format_=="csv":
                            stream=io.StringIO();writer=csv.writer(stream)
                            fields=("seed","score","merged_max","moves","terminated","truncated","inference_ms_per_move")
                            writer.writerow(["agent",*fields])
                            for agent,result in report["agents"].items():
                                for row in result["episodes"]:
                                    writer.writerow([agent,*[row[k] for k in fields]])
                            self.send("\ufeff"+stream.getvalue(),"text/csv; charset=utf-8",filename=key+".csv")
                        elif format_=="html":
                            condition=report["condition"]
                            rows="".join("<tr>"+"".join("<td>"+html.escape(str(value))+"</td>" for value in (
                                result["name"],len(result["episodes"]),result["mean_score"],result.get("median_score"),
                                str(round(result["score_15000_rate"]*100,2))+"%" if result.get("score_15000_rate") is not None else "—",result.get("score_p10"),
                                result["score_std"],result["mean_moves"],result["max_merged"],"完了" if result["complete"] else "途中結果"))+"</tr>"
                                for result in report["agents"].values())
                            content=('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                                '<title>検証結果</title><style>body{font:14px system-ui;max-width:1200px;margin:40px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
                                '<h1>検証結果</h1><p>'+html.escape(condition["name"])+f' / {len(condition["seeds"])}ゲーム / 上限{condition["max_steps"]}手 / '+('完了' if report["complete"] else '途中結果')+'</p>'
                                '<table><thead><tr><th>対象</th><th>ゲーム数</th><th>平均得点</th><th>中央値</th><th>15,000点以上</th><th>下位10%点</th><th>標準偏差</th><th>平均手数</th><th>最大値</th><th>状態</th></tr></thead><tbody>'+rows+'</tbody></table><details><summary>条件・全結果JSON</summary><pre>'+html.escape(json.dumps(report,ensure_ascii=False,indent=2))+"</pre></details></html>")
                            self.send(content,"text/html; charset=utf-8",filename=key+".html")
                        else:
                            self.send(report,filename=key+".json")
                    else:
                        self.send({"error":"APIがありません。"},status=404)
                    return
                relative="dashboard.html" if path=="/" else path.lstrip("/")
                resolved=(built / relative).resolve()
                if not resolved.is_relative_to(built) or not resolved.is_file():
                    if relative=="dashboard.html":
                        self.send(setup_page(token),"text/html; charset=utf-8",cookie=True)
                    else:
                        self.send({"error":"ファイルがありません。環境準備を実行してください。"},status=404)
                    return
                if resolved.suffix==".html":
                    content=resolved.read_text(encoding="utf-8").replace("</head>",f'<meta name="dtn-token" content="{token}"></head>')
                    self.send(content,"text/html; charset=utf-8",cookie=True)
                else:
                    mime={".js":"text/javascript",".mjs":"text/javascript",".wasm":"application/wasm"}.get(resolved.suffix,mimetypes.guess_type(str(resolved))[0] or "application/octet-stream")
                    self.send(resolved.read_bytes(),mime)
            except (ValueError,KeyError,TypeError) as error:
                self.send({"error":str(error)},status=400)
            except Exception as error:
                self.send({"error":str(error)},status=500)

        def do_POST(self):
            if not self.authorized(mutation=True):
                self.send({"error":"操作の認証に失敗しました。管理画面を開き直してください。"},status=403);return
            try:
                length=integer(int(self.headers.get("Content-Length","0")),2,4*1024*1024,"入力サイズ")
                data=json.loads(self.rfile.read(length));path=urlsplit(self.path).path
                if not isinstance(data,dict):
                    raise ValueError("入力はJSONオブジェクトです。")
                if path=="/api/train":
                    count=integer(data.get("repeats",1),1,3,"繰り返し数")
                    def enqueue():
                        config=data["config"];integer(config["seed"],0,2**32-count,"seed")
                        ids=[]
                        for index in range(count):
                            ids.append(manager.enqueue_train({**data,"name":str(data.get("name") or "PPO")+(f" / seed {config['seed']+index}" if count>1 else ""),
                                                              "config":{**config,"seed":config["seed"]+index}})["id"])
                        return {"ids":ids}
                    result=manager.deduplicate(data.get("request_id"),enqueue)
                elif path=="/api/evaluate":
                    result=manager.deduplicate(data.get("request_id"),lambda:manager.enqueue_evaluation(data))
                elif path=="/api/condition":
                    result=manager.deduplicate(data.get("request_id"),lambda:manager.condition(data))
                elif path=="/api/stop":
                    result=manager.stop(data.get("id"),data.get("force") is True)
                elif path=="/api/reorder":
                    result=manager.reorder(data.get("ids"))
                elif path=="/api/edit":
                    job=manager.get("job",data.get("id"));job["name"]=str(data.get("name") or job["name"])[:100];job["note"]=str(data.get("note") or "")[:10000]
                    manager.put("job",job);result={"ok":True}
                elif path=="/api/import":
                    result=manager.import_existing(data.get("name"))
                elif path=="/api/import-policy":
                    result=manager.import_policy(data.get("policy"))
                elif path=="/api/setup":
                    result=manager.setup()
                elif path=="/api/shutdown":
                    manager.close();threading.Thread(target=self.server.shutdown,daemon=True).start();result={"ok":True}
                else:
                    self.send({"error":"APIがありません。"},status=404);return
                self.send(result)
            except (ValueError,KeyError,TypeError) as error:
                self.send({"error":str(error)},status=400)
            except Exception as error:
                self.send({"error":str(error)},status=500)
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.manager=manager
    return server


def setup_page(token):
    return '''<!doctype html><html lang="ja"><meta charset="utf-8"><title>学習・検証</title><style>body{font:16px system-ui;max-width:800px;margin:60px auto;padding:20px}button{padding:12px}pre{white-space:pre-wrap}</style>
<h1>環境準備</h1><p>Python 3.12以上、uv、Node.js 22.12以上を先に導入してください。固定済みの依存を導入し、ローカル画面をビルドします。</p>
<button id="setup">環境を準備</button><button onclick="location.reload()">画面を更新</button><pre id="status"></pre><script>const token="'''+token+'''";let active=false;
document.querySelector('#setup').onclick=async()=>{try{let r=await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json','X-DTN-Token':token},body:'{}'});let d=await r.json();if(!r.ok)throw Error(d.error);active=true}catch(e){document.querySelector('#status').textContent=e.message}};
setInterval(async()=>{try{let d=await(await fetch('/api/state')).json();document.querySelector('#status').textContent=JSON.stringify(d.environment,null,2)+'\\n'+d.jobs.map(j=>j.name+' : '+j.status+' '+(j.progress.phase||'')+' '+(j.error||'')).join('\\n');if(active&&d.environment.ready)location.reload()}catch(e){document.querySelector('#status').textContent=e.message}},1000);</script></html>'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=8765);parser.add_argument("--no-browser",action="store_true")
    args=parser.parse_args();root=Path(__file__).resolve().parents[3];server=make_server(root,args.port)
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/")
    print(f"GUI: http://127.0.0.1:{server.server_port}/",flush=True)
    try:
        server.serve_forever()
    finally:
        server.manager.close()
        process=server.manager.process
        if process:
            process.wait()
        server.server_close()


if __name__=="__main__":
    main()
