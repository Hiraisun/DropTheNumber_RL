# DropTheNumber_RL

パズルゲーム「Drop The Number」の基本ゲームを再現し、その環境でプレイするAIを開発するプロジェクト。

開発は次の2段階で進める。

1. **ブラウザーで手動操作できるゲームを実装し、公式アプリとの挙動を比較して公開する。**
2. **第一段階の検証後、AIの学習・評価を実装する。**

現在はリポジトリとドキュメントを準備した段階。ゲーム、実行コマンド、学習コードは未実装。

## ドキュメント

| 文書 | 内容 |
| --- | --- |
| [開発計画](docs/ROADMAP.md) | 段階ごとの作業、成果物、完了条件 |
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

第一段階で比較する範囲は、通常プレイの盤面遷移、ブロック生成、進行による消去、得点、終了条件。ブースター・復活の存在と仕様は調査項目に残すが、初期実装と同一性判定の対象から外す。広告、課金、ランキングは開発範囲に含めない。

## 技術構成の方針

ゲームエンジンを標準ライブラリ中心のPythonで作り、ブラウザーではPyodideのWeb Worker内で実行する。画面はTypeScript・Vite・Canvas 2DとHTMLで作り、静的ファイルとしてGitHub Pagesへ公開する。PCのマウス・キーボードとスマートフォンのタッチ操作に対応する。

第二段階では同じPythonエンジンをローカルのCPython・Gymnasiumから直接操作し、PyTorchとStable-Baselines3を使ってAIを比較する。初回読み込みと操作応答は、実装初期の小さな試作で測定する。

この構成は開発方針であり、依存パッケージのインストールやバージョン固定はまだ行っていない。実装開始時に `pyproject.toml`・`uv.lock`、Web用の `package.json`・`package-lock.json` を追加する。

## 直近の作業

1. 比較対象の実機バージョンとモードを決めて記録する。
2. [ゲームルール調査](docs/GAME_RULES.md)のP0項目を優先して観察する。
3. 共通Pythonエンジンをブラウザーで動かす試作を作り、読み込みと操作応答を測定する。
4. 未確認項目を明記した暫定ルールでブラウザーの手動プレイを実装する。
5. 実機の観察記録から期待結果を作り、相違を修正して公開する。

Gitはローカルの `main` ブランチで初期化する。リモートリポジトリと公開範囲は未設定。
