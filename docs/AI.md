# AIの学習・評価とブラウザー観戦

更新日: 2026-10-10。ローカルでPPOを学習し、同じモデルをGitHub Pagesのブラウザー内で実行する初期版を実装した。ルールは手動版と共通の `prototype-v2`。公式との完全一致は未検証なので、このルールで学習した結果として扱う。

## ブラウザーで使う

右側（スマートフォンではゲームの下）のAI欄でプレイヤーと速度を選び、「AIで新規開始」を押す。PPO、1手先の評価、ランダムの3種類。停止・再開ができ、タブ非表示時も停止する。速度は手の間の待ち時間であり、1手の合体・重力は最後まで解決する。

AIは自然落下OFFのターン制。AI中は手動投入を受け付けない。通常の「新しいゲーム」で手動に戻る。AIは診断プレイ扱いで、手動の保存データとBESTを更新しない。「記録を書き出す」でAIの操作を保存でき、既存の記録読み込み・再生に対応する。

「モデルを読み込む」でローカルの `best.json` / `latest.json` を読み込める。2MB以下の `drop-number/policy-v1` のJSONのみ対応。重み・サイズ・有限数・観測形式・ルールを検証し、学習ルールと盤面ルールが異なる場合は推論を拒否する。ブラウザー内で処理し、ファイルをサーバーへ送信しない。

## ローカルで学習する

通常の操作は[学習・検証GUI](GUI.md)から行える。以下は開発・自動化向けのCLI。GUIでも同じ学習処理・エンジンを使用し、停止・追加学習・ジョブ管理をローカルサーバーで管理する。

リポジトリのルートで実行する。Python 3.12以上とuvを使用。

```powershell
uv sync --frozen --extra rl
uv run --extra rl python -m drop_the_number.ai train --config configs/ppo.json --output artifacts/rl/my-run
uv run --extra rl python -m drop_the_number.ai evaluate --model artifacts/rl/my-run/best.json --output artifacts/rl/my-evaluation
```

出力先は毎回新しい名前にする。既存の実験へ上書きしない。`configs/ppo.json` をコピーして `timesteps`・学習率などを変更し、`--config` に指定できる。初期設定はCPU向け。Windows/LinuxのTorchはCPU専用配布を明示的に使い、CUDAは不要。[uvのPyTorch設定](https://docs.astral.sh/uv/guides/integration/pytorch/)

学習の出力:

| ファイル | 内容 |
| --- | --- |
| `config.json` | 設定、設定ハッシュ、依存版、検証seed、ルール |
| `latest.zip` / `best.zip` | SB3の学習状態。ブラウザーへは読み込めない |
| `latest.json` / `best.json` | 推論用の重み。ブラウザーで読込可能 |
| `progress.json` | 各チェックポイントの手数、時間、検証結果 |
| `step-<手数>.zip` / `.json` | 保存時点ごとの学習状態・推論用重み |
| `updates.jsonl` | PPO更新完了ごとの内部指標・列選択頻度 |
| `validation.json` | 採用モデルを選んだ検証結果 |

`best` は検証seedの平均得点で選ぶ。ゲームの生成seedはエピソードごとに変わり、実際に使用したseedをモデルに保存する。131,072手は4環境の合計。エピソード上限は1,000手で、上限到達はゲームオーバーと区別する。

評価の出力は `evaluation.json` と各AIの最初の評価ゲームの `*-replay.json`。各エピソードの得点、合成最大値、手数、終了/打ち切り、推論時間を残す。リプレイはブラウザーで読込可能。学習・検証seedと評価seedの重複を検出すると拒否する。

評価seedの既定値は2,000,000,000から64個、検証seedは1,000,000,000から16個。複数モデルをこの評価結果で調整・選別した後は、そのseed群も検証用として扱い、別の未使用seedで最終評価する。GUIの繰り返し比較プリセットで3種類の学習seedを順番に実行できる。

## 環境とモデル

`DropNumberEnv.reset(seed=...)` / `step(action)` が共通の `Game` を直接操作する。[Gymnasiumのカスタム環境API](https://gymnasium.farama.org/introduction/create_custom_env/)

- 行動: 左から0～4の列、`Discrete(5)`。終了する手も合法な選択なので、列の高さによるマスクは設けない。
- 観測: 上から下・左から右の盤面30マス、現在、予告、過去の合成最大値、生成上限の34値。空は0、ブロックはlog2の指数を32で割る。クリップはしない。
- 観測に含めないもの: seed、乱数状態、内部の生成列、未表示の次々ブロック、時刻。
- 報酬: 初期実験は `log2(1 + 得点増分) / 16`。生存や終了への追加報酬はなし。設定で `score` を選ぶと得点増分/256。
- 終了: 合体・重力・連鎖の後に最上段が占有されたら `terminated=True`。実験上の手数上限は `truncated=True`。

PPOはSB3のMLP、隠れ層64×64、Tanh。学習時は確率的に行動し、評価・ブラウザーは出力が最大の列を選ぶ。同点は左の列。CPUを使う非CNNモデルとして実装した。[SB3 PPO](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)

SB3のactorのLinear/Tanhと出力層をJSONへ書き出す。推論には標準ライブラリのPythonだけを使い、Pyodide Worker内で実行する。PagesへTorchやGymnasiumは配布しない。学習用のvalue networkとoptimizerも推論JSONに含めない。[SB3のモデル書き出し](https://stable-baselines3.readthedocs.io/en/master/guide/export.html)

比較基準の「1手先の評価」は全5列をシミュレートし、終了回避、得点増分、空マス、最高列、隣列の高さ差で選ぶ。シミュレート用の乱数はゲーム本体と別で、新しい予告は評価に使わない。ランダムAIもゲーム本体と別の乱数を使う。

## 初回の結果

Windows / CPython 3.12.7、CPU、Torch 2.14.1+cpu、SB3 2.9.0。学習seed 20261010、131,072手、約109秒（検証とチェックポイント書き出しを含む）。検証平均得点は32768手:115.75 → 65536手:181.25 → 98304手:615 → 131072手:621。最後のチェックポイントを採用。

未使用の共通seed64個、上限1000手、決定的な推論での結果:

| AI | 平均得点 | 得点の標準偏差 | 平均手数 | 64回中の最大合成値 | 平均推論時間/手 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ランダム | 368.1 | 321.4 | 37.7 | 256 | 0.003ms |
| 1手先の評価 | 10,185.5 | 5,081.8 | 132.5 | 4,096 | 1.263ms |
| PPO（初期学習） | 618.6 | 459.3 | 47.7 | 512 | 1.426ms |

打ち切りは全AIで0回。推論時間はローカルの標準ライブラリ実装を測定し、描画やWorker往復を含めない。スマートフォンの速度を示す測定ではない。

この1回の学習ではPPOはランダムより平均得点が高いが、評価関数のAIに大きく劣る。強いモデルとは扱わない。追加学習、盤面の符号化、報酬、複数学習seed、探索との組み合わせが次の改善候補。

- [初期設定](../configs/ppo.json)
- [学習推移](experiments/ppo-initial-progress.json)
- [全評価データ](experiments/ppo-initial-evaluation.json)
- [公開する推論モデル](../web/public/ai/ppo.json)（約170KiB）

## 検証と更新

```powershell
uv run --extra rl pytest -q
cd web
npm run test:parity
npm run build
```

検証はエンジンの全fixtureとGym環境の遷移一致、終了/打ち切り、隠れ情報を使わないこと、PyTorchとJSON推論の出力・列の一致、AIリプレイの完全復元を含む。CPython/Pyodideの比較では公開モデルによる操作・比較AIの操作・全イベント・乱数状態も照合する。通常の依存だけで実行したpytestでは学習用テストをスキップし、CIの別ジョブで `--extra rl` を使って実行する。

モデルの更新は、検証済みの `best.json` を `web/public/ai/ppo.json` にコピーし、評価レポートも更新して通常のPages公開手順を実行する。ブラウザーには新規ゲーム開始時に必要ならモデルを取得する。個人のモデルを試すだけなら、公開を変更せず「モデルを読み込む」を使う。
