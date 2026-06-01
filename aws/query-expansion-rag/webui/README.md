# RAG Chat Web UI

Query Expansion RAG API をブラウザから利用するためのシンプルな Web インターフェースです。

## 画面

- 質問を入力して送信すると AI が回答を返します
- クエリ拡張数（1 / 3 / 5）と詳細モードを切り替えられます

## 前提条件

- Python 3.x
- AWS 認証情報が設定済み（`~/.aws/credentials` または環境変数）
- `qerag-s3v-qeRagApi` スタックがデプロイ済み

## セットアップ

```bash
cd webui
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 起動

```bash
AWS_PROFILE=hp-user APP_NAME="qerag-s3v" .venv/bin/python app.py
```

バックグラウンドで起動する場合：

```bash
AWS_PROFILE=hp-user APP_NAME="qerag-s3v" nohup .venv/bin/python app.py &> /tmp/qerag-webui.log &
```

停止する場合：

```bash
kill $(lsof -ti :5000)
```

ブラウザで `http://localhost:5000` を開いてください。

別の appName を使う場合：

```bash
APP_NAME="my-app-s3v" python app.py
```

## 環境変数

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `APP_NAME` | `qerag-s3v` | CDK でデプロイした appName |
| `AWS_DEFAULT_REGION` | `ap-northeast-1` | AWS リージョン |
| `AWS_PROFILE` | （未設定） | AWS プロファイル名 |

## ファイル構成

```
webui/
├── app.py               # Flask バックエンド
├── requirements.txt     # 依存パッケージ
└── templates/
    └── index.html       # チャット UI
```

## 動作の仕組み

1. 起動時に CloudFormation スタック出力から API エンドポイントと API キーを自動取得
2. ブラウザからの質問を `/ask` エンドポイント経由で RAG API に転送
3. 回答をチャット形式で表示
