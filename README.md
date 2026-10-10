# DropTheNumber_RL

パズルゲーム「Drop The Number」の基本ゲームを再現し、その環境でプレイするAIを開発するプロジェクト。

開発は次の2段階で進める。

1. **ブラウザーで手動操作できるゲームを実装し、公式アプリとの挙動を比較して公開する。**
2. **第一段階の検証後、AIの学習・評価を実装する。**

ブラウザーでの手動プレイに加え、ローカルPPO学習・共通seedでの評価・学習済みAIのブラウザー観戦を実装した。自然落下の切替、保存・再開、リプレイ、任意盤面の診断にも対応する。公式との全ケース比較は未完了で、AIは暫定ルール `prototype-v2` を対象にする。

[ブラウザーでプレイ](https://hiraisun.github.io/DropTheNumber_RL/)

学習・検証をGUIで操作する場合は、ルートの **`Start GUI.cmd`をダブルクリック**する。学習設定、保存停止、追加学習、条件を固定したモデル比較、成績グラフ、観戦・リプレイの受け渡しに対応する。初回の環境準備と使い方は[学習・検証GUI](docs/GUI.md)。管理画面はローカル専用で、観戦には公開ゲームと共通の画面を使う。

## 起動

Node.js 22.12以上とuv・Python 3.12以上を使用する。

```powershell
uv sync --frozen
cd web
npm ci
npm run dev
```

表示されたLocal URLを開く。列のクリック・タップまたは1～5キーで操作できる。自然落下は初期OFF。詳しい使い方と検証コマンドは[実装と起動手順](docs/IMPLEMENTATION.md)を参照。

[提供された約74秒の録画の調査結果](docs/observations/VIDEO-0001-short-play.md)を追加した。基本合体・4個合体・重力・得点・上端での終了を記録し、未確定仕様と必要な追加場面を整理している。

## ドキュメント

| 文書 | 内容 |
| --- | --- |
| [開発計画](docs/ROADMAP.md) | 段階ごとの作業、成果物、完了条件 |
| [実装と起動手順](docs/IMPLEMENTATION.md) | 手動操作、診断、保存・リプレイ、検証コマンド、試作の暫定設定 |
| [AIの学習と観戦](docs/AI.md) | ローカルPPO学習、評価、モデル読込、初回の結果 |
| [学習・検証GUI](docs/GUI.md) | ダブルクリック起動、学習操作、実験・評価の管理 |
| [GUI仕様](docs/GUI_SPEC.md) | 共通観戦ビュー、保存・停止・seed管理、初期版の範囲 |
| [ゲームルール調査](docs/GAME_RULES.md) | 出典、確認状況、未確定仕様、暫定仕様の扱い |
| [公式との比較手順](docs/VALIDATION.md) | 確認する場面、証拠の記録、同一性の判定 |
| [環境と設計](docs/ARCHITECTURE.md) | 技術構成、共通エンジン、再現可能な記録 |
| [ブラウザー公開](docs/DEPLOYMENT.md) | GitHub Pagesでの構成、ビルド、公開確認 |
| [プレイ動画の解析](docs/VIDEO_ANALYSIS.md) | 撮影条件、フレームからの仕様確認、解析の限界 |
| [観察記録](docs/observations/README.md) | 実機観察と仕様変更の記録方法 |
| [観察テンプレート](docs/observations/TEMPLATE.md) | 1件の実機観察を記録する書式 |

## 対象とするゲーム

Android版のアプリID `com.superbox.aos.fire2048` を主な比較対象にする。

- [Google Play公式ページ](https://play.google.com/store/apps/details?id=com.superbox.aos.fire2048)
- [App Store公式ページ（補助資料）](https://apps.apple.com/in/app/drop-the-number-merge-puzzle/id1454637812)

同じ開発元の「Drop Merge」や、同名のブラウザーゲームの仕様は流用しない。比較対象の実機バージョン・ゲームモードは観察時に記録する。まだ実機でのルール検証は行っていない。

第一段階で比較する範囲は、通常プレイの盤面遷移、ブロック生成、進行による消去、得点、終了条件。手動プレイは自然落下をオン・オフ切り替えられ、AIは自然落下なしのターン制にする。合体後の重力は共通。コイン、広告、課金、報酬画面、ブースター、復活、ランキングは再現しない。予告はゲームの情報として表示し、購入・解放の仕組みは再現しない。

## 技術構成の方針

ゲームエンジンを標準ライブラリ中心のPythonで作り、ブラウザーではPyodideのWeb Worker内で実行する。画面はTypeScript・Vite・Canvas 2DとHTMLで作り、静的ファイルとしてGitHub Pagesへ公開する。PCのマウス・キーボードとスマートフォンのタッチ操作に対応する。

同じPythonエンジンをローカルのCPython・Gymnasiumから直接操作し、PyTorchとStable-Baselines3でPPOを学習する。推論重みをJSONに書き出し、公開ブラウザーのPyodide Worker内で実行する。AIでは自然落下を使わない。

`pyproject.toml`・`uv.lock`、`web/package.json`・`package-lock.json` で依存を固定した。Pyodide 314.0.7と標準ライブラリはゲームと同じホストから配信する。学習用ライブラリは `uv sync --frozen --extra rl` で追加する。詳細は[AIの手順](docs/AI.md)。初回モデルは131,072手の学習を実施し、64ゲームの平均得点はPPO 618.6、ランダム368.1、1手先の評価10,185.5。PPOは初期版で、まだ評価関数に劣る。

## 直近の作業

1. 手動プレイで操作感と挙動を確認する。
2. 比較対象の実機バージョン・モードを固定し、残る連鎖・生成・進行消去の仕様を確認する。
3. [比較手順](docs/VALIDATION.md)に沿って相違を修正する。
4. 公開版をスマートフォン実機でも確認する。更新時はActionsの「Publish manual game」を実行する。

Gitの `main` を公開リポジトリ [Hiraisun/DropTheNumber_RL](https://github.com/Hiraisun/DropTheNumber_RL) へpushしている。
