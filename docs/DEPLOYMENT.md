# ブラウザー公開

更新日: 2026-10-10。Web実装と静的ビルド、手動実行のPages公開ワークフローを用意した。GitHubリモートと公開URLはまだない。

## GitHub Pagesで公開できる構成

GitHub PagesはHTML・CSS・JavaScriptなどの静的ファイルを配信する。ブラウザー内でゲーム処理を実行すれば、手動プレイに常駐サーバーは必要ない。[GitHub公式説明](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

本プロジェクトではTypeScriptの画面と、Pythonをブラウザーで動かすPyodide、共通Pythonエンジンを静的ファイルとして配信する。Pyodideの公式資料にもGitHub Pagesによる配信が記載されている。[Pyodideの配信資料](https://pyodide.org/en/stable/usage/downloading-and-deploying.html)

ゲームの保存は端末内、リプレイはファイルとして読み込み・書き出しを行う。学習はローカルのCPythonで実行する。PagesでPythonサーバーや学習ジョブを動かす構成ではない。オンラインランキングや端末間同期を追加する場合は別のサービスが必要になる。

## リポジトリとURL

GitHub Freeでは公開リポジトリのPagesを利用できる。非公開リポジトリからの利用可否はプランによる。[GitHubの利用条件](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

所有者とリポジトリ名は未設定。プロジェクト用URLの形式は `https://<owner>.github.io/<repository>/`。ローカルの名前を採用する場合、ベースパスは `/DropTheNumber_RL/` になる。実際のGitHub名を確定してから設定する。

試作はViteの相対 `base: './'` を使用し、Workerへ公開ディレクトリの絶対URLを渡す。Worker・ランタイム・Pythonソースの取得はそのURLを基準にする。ホストのルートを前提にした `/runtime/...` のようなURLを使わない。[Vite公式の公開手順](https://vite.dev/guide/static-deploy.html#github-pages)

初期画面は単一ページとし、複雑な履歴型ルーティングを導入しない。公開URLの再読み込みでゲームを開けるようにする。

## ランタイム配布

- Pyodideは固定版を採用し、開発版や変動する最新版のURLへ依存しない。
- ランタイムの必要なファイルをビルドで準備し、同じ公開先から配信する方針。全追加パッケージを含む配布物を無条件に読み込まない。
- 同一コミットの共通エンジンのPythonソースを `engine/source.json` に梱包し、Workerで仮想ファイルシステムへ配置する。
- WASMなどの配信形式と、取得先・必要なCORS条件が正しいことを公開URLで確認する。
- ブラウザーには学習用ライブラリを配布しない。

配布物の構成は固定するPyodideの版に合わせて実装する。[ランタイム配布の公式資料](https://pyodide.org/en/stable/usage/downloading-and-deploying.html)、[自作Pythonコードの読み込み](https://pyodide.org/en/stable/usage/loading-custom-python-code.html)

初回アクセスはランタイムの転送・初期化が必要になる。キャッシュによる再訪時との差も測定する。PCとスマートフォンで転送量、操作開始までの時間、1手の応答、操作中の描画停止を記録する。測定前に高速・軽量と断定しない。

## ビルドと公開の予定手順

ローカルの準備・検証・ビルドは[実装手順](IMPLEMENTATION.md)に記載。公開時は次を行う。

1. GitHubリポジトリを作成し、ローカルGitにリモートを設定する。
2. PythonとWebの依存、Pyodideの版を固定する。
3. 共通エンジンの検証とCPython・Pyodideの出力照合を実行する。
4. ランタイム・エンジンを配布用ディレクトリへ準備する。
5. Webの型確認、ブラウザー内のエンジン比較、操作確認を行う。
6. Viteで `web/dist/` に静的ファイルをビルドする。
7. リポジトリのPagesの公開元をGitHub Actionsに設定する。
8. Actionsで静的配布物をアップロードし、Pagesへデプロイする。
9. 実際の公開URLで下記の確認を行う。

`.github/workflows/pages.yml` を追加済み。GitHubでPagesのSourceをGitHub Actionsにして、Actionsの「Publish manual game」を手動実行する。自動検証とビルドが成功した配布物だけを公開する。配布対象は `web/dist/` のみ。動画・観察画像・学習ログ・モデルは含めない。[GitHub ActionsによるPages公開](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

## 公開確認

- PCのChrome・Edgeと、AndroidのChrome・iOSのSafariを初期確認対象にする。利用できた端末・バージョンと未確認の対象を記録する。
- 初回アクセス、再訪、再読み込みで盤面とランタイムを取得できる。
- マウス、キーボード、タッチで列を選び、入力が二重に受理されない。
- 縦横・画面サイズ・画素密度が変わっても操作位置と描画位置が一致する。
- 保存・再開、ゲーム終了・再スタート、リプレイの読み込み・書き出しが動作する。
- 非表示タブや画面ロックから戻ったときの時間進行が設計どおりになる。
- 読み込み失敗時に理由と再試行を表示する。
- 診断パネルからルール設定版とエンジン版を確認できる。
- 公開版とローカル版の共通データによる遷移比較が一致する。

公開と公式との挙動検証は別の完了条件。試作を先に公開する場合は、未検証のルールを含むことを表示する。第一段階の標準計画は、基本ゲームの比較後に公開する。
