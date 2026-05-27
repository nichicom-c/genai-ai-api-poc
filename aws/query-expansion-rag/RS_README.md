# Query Expansion RAG — S3 Vectors デプロイ手順

## 概要

このドキュメントは、ベクトルストアに **Amazon S3 Vectors** を使用して Query Expansion RAG API をデプロイする手順をまとめたものです。

### OpenSearch Serverless との違い

| 項目 | OpenSearch Serverless | S3 Vectors |
|------|----------------------|------------|
| 設定キー | `qeRagAppNames` / `qeRagAppNamesWithSharedCmek` | `qeRagAppNamesWithS3Vectors` |
| 共通 CMEK | 対応 | 非対応（個別 CMEK のみ） |
| インデックス管理 | CDK カスタムリソース（Lambda）が作成 | CDK が直接作成 |
| メタデータ上限 | なし | **1KB**（ユーザー定義分） |

---

## アーキテクチャ

```
Client → API Gateway → Lambda → Bedrock Converse API（クエリ拡張・回答生成）
                               → Bedrock Knowledge Base → S3 Vectors（ベクトル検索）
                                                        → S3（ドキュメントソース）
```

---

## 前提条件

- AWS CLI（設定済み）
- Node.js v22.x
- AWS CDK
- `jq`（API 呼び出しスクリプト用）
- CDK Bootstrap 実行済み（初回のみ）

---

## IAM ユーザー権限

### カスタマー管理ポリシー（3つ作成してユーザーにアタッチ）

| ファイル | ポリシー名（例） | 内容 |
|---------|----------------|------|
| `iam-deploy-policy.json` | `QERagDeploy-1` | CloudFormation / IAM / KMS |
| `iam-deploy-policy-2.json` | `QERagDeploy-2` | S3 / Lambda / CloudWatch Logs |
| `iam-deploy-policy-3.json` | `QERagDeploy-3` | API Gateway / WAF / Bedrock / S3 Vectors / CDK Bootstrap |

> **注意**: インラインポリシーは 2,048 bytes 上限のため使用不可。IAM コンソールの「ポリシー」ページからカスタマー管理ポリシーとして作成すること。

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

for i in "" "-2" "-3"; do
  aws iam create-policy \
    --policy-name "QERagDeploy${i//-/_}" \
    --policy-document file://iam-deploy-policy${i}.json
done

for i in "" "-2" "-3"; do
  aws iam attach-user-policy \
    --user-name <USER_NAME> \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/QERagDeploy${i//-/_}"
done
```

---

## 設定変更

### `parameter.ts`

```typescript
const deploy_envs: Record<string, Partial<StackInput>> = {
  "-dev": {
    // S3 Vectors バックエンドを使用
    "qeRagAppNamesWithS3Vectors": [
      {"appName": "qerag-s3v", "appParamFile": "qerag.toml"}
    ],

    // 社内 IP アドレス制限
    allowedIpV4AddressRanges: [
      "92.203.119.64/27",
      "133.114.249.89/32",
      "182.169.72.149/32",
      "182.169.24.85/32",
      "210.139.176.226/32",
      "150.249.214.152/29"
    ],

    // SSO を使わず IAM ユーザーで運用する場合
    switchRoleName: "",
    iamPrincipalArns: ["arn:aws:iam::<ACCOUNT_ID>:user/<USER_NAME>"],

    // API Gateway タイムアウト（標準上限: 29秒）
    apiLambdaIntegrationTimeout: 29,

    logLevel: "DEBUG",
  },
};
```

> **`apiLambdaIntegrationTimeout` について**: API Gateway REST API の標準上限は 29 秒。AWS サポートへ申請することで最大 300 秒まで引き上げ可能。

---

## デプロイ手順

```bash
# 1. 依存パッケージのインストール
npm ci

# 2. CDK Bootstrap（初回のみ）
cdk bootstrap

# 3. デプロイ
source .venv/bin/activate
export AWS_PROFILE=hp-user
cdk deploy --all -c env=-dev
```

### 作成されるスタック（appName: `qerag-s3v` の場合）

| スタック名 | 内容 |
|-----------|------|
| `ApiWafStack` | WAF WebACL（IP 制限） |
| `qerag-s3v-SwitchRoleStack` | 開発者用 IAM スイッチロール |
| `qerag-s3v-qeRagKB` | S3 Vector Bucket / Knowledge Base / データソース S3 |
| `qerag-s3v-qeRagApi` | API Gateway / Lambda |

---

## ドキュメントの登録

### 1. PDF → Markdown 変換（推奨）

PDFを直接 Knowledge Base に取り込むと、テキスト抽出時の不要な改行・余白がチャンクに混入し、検索品質が低下します。事前に Markdown に変換してから登録することを推奨します。

```bash
# 依存パッケージのインストール
pip install -r tools/add_metadata_json/py/requirements.txt

# PDF → Markdown 変換（doc/ → doc_md/）
python tools/add_metadata_json/py/03_pdf_to_markdown.py \
  --src tools/add_metadata_json/doc \
  --dst tools/add_metadata_json/doc_md
```

- 変換後の `.md` ファイルには、元の `.pdf.metadata.json` が自動でコピーされます
- `file_name` メタデータは元の PDF ファイル名のまま保持されるため、引用リンクに影響しません

### 2. メタデータ JSON を生成（URL 付与する場合）

URL リンクを参考情報に表示したい場合は、変換前に以下の手順でメタデータを付与します。

```bash
# ① ファイル名一覧を出力
python tools/add_metadata_json/py/01_write_filepath.py --dir /path/to/docs

# ② url_list.xlsx に URL を記入してから実行
#    --s3vectors で 1KB 制限チェックを有効化
python tools/add_metadata_json/py/02_add_metadata_json.py \
  --dir /path/to/docs \
  --excel tools/add_metadata_json/url_list.xlsx \
  --s3vectors
```

> **S3 Vectors のメタデータ上限**: Bedrock 内部フィールド（`AMAZON_BEDROCK_TEXT` / `AMAZON_BEDROCK_METADATA`）を含めて 1KB。URL やファイル名は短く保つこと。

### 3. S3 にアップロード

```bash
# Markdown 変換済みディレクトリを指定
./upload-docs.sh tools/add_metadata_json/doc_md

# （変換しない場合）
./upload-docs.sh tools/add_metadata_json/doc
```

### 4. Bedrock インジェストジョブを実行

```bash
./start-ingestion.sh
```

完了まで自動で待機し、`COMPLETE` になると終了します。

---

## 相談記録ファイルの配置（まとめて要約・構造化サマリー用）

`summarize_structured` モードおよび `まとめて要約` 機能では、PDF を Knowledge Base 経由ではなく Claude に直接読み込ませます。対象 PDF は以下に配置してください。

```
tools/add_metadata_json/records/
  ├── case_001.pdf
  ├── case_002.pdf
  └── ...
```

Web UI の `records/` API がこのディレクトリを一覧表示します。Knowledge Base への登録は不要です。

---

## Web UI

ブラウザからチャット形式で RAG API を利用できます。

```bash
cd webui
pip install -r requirements.txt
AWS_PROFILE=hp-user APP_NAME="qerag-s3v" python app.py
```

ブラウザで `http://localhost:5000` を開いてください。

### 機能一覧

| 機能 | 説明 |
|------|------|
| Q&A チャット | クエリ拡張 + Knowledge Base 検索による回答生成 |
| 政策支援 | 過去ケースを参照した対応方針提案 |
| 相談記録一覧 | `records/` ディレクトリの PDF 一覧表示 |
| まとめて要約 | 複数 PDF を並列処理し、構造化テーブル・全体サマリー・3D ワードクラウドを生成 |

### まとめて要約の処理フロー

```
1. records/ から対象ファイルを選択
2. ファイルごとに summarize_structured モードで並列 API 呼び出し
   → 実施日 / 相談方法 / サマリ内容 / 支援時期 を JSON で抽出（PDF を Claude に直接添付）
3. 全ファイル完了後、multi_summarize_final モードで集約 API 呼び出し
   → 全体サマリー生成
4. サマリ内容からキーワード抽出 → 3D 球体ワードクラウド描画
```

> **タイムアウト対策**: 1 回の API 呼び出しを 1 ファイルに分割することで、Lambda の 29 秒制限に対応しています。

### ドキュメント配信

Flask が `/nck-portal/<ファイル名>` で PDF を直接配信します。

```
http://<host>:5000/nck-portal/example.pdf
```

回答の引用リンクをクリックするとドキュメントが開きます。

---

## API の実行

```bash
# 事前: jq のインストール
sudo apt install jq

# 基本
./invoke-api.sh "QUESTについて教えてください"

# 詳細モード（引用元を含む）
./invoke-api.sh "フレックスタイム制について" --detail

# クエリ拡張数を変更（デフォルト: 3）
./invoke-api.sh "フレックスタイム制について" --queries 5

# 別の appName を使う場合
APP_NAME="my-app-s3v" ./invoke-api.sh "質問文"
```

### リクエスト・レスポンス仕様

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `inputs.question` | string | mode 依存 | 質問テキスト（`summarize` / `multi_summarize` / `summarize_structured` は省略可） |
| `inputs.mode` | string | | 動作モード（下表参照、デフォルト: `qa`） |
| `inputs.n_queries` | number | | クエリ拡張数（デフォルト: 3） |
| `inputs.output_in_detail` | boolean | | 詳細回答モード（デフォルト: false） |
| `inputs.file_name` | string | summarize / summarize_structured | 対象ファイル名 |
| `inputs.file_names` | string[] | multi_summarize | 対象ファイル名リスト（2件以上） |
| `inputs.max_chars` | number | | サマリ内容の最大文字数（0 = 制限なし） |
| `inputs.tags` | string | | KB 検索時のメタデータフィルタ（カンマ区切りで複数指定可、OR 条件） |
| `inputs.files` | object[] | | 添付ファイル（Base64 エンコード PDF） |
| `inputs.systemPromptForAnswerGeneration` | string | | システムプロンプトの上書き |

#### mode 一覧

| mode | 説明 | KB 検索 | 参考情報 |
|------|------|--------|--------|
| `qa` | 汎用 Q&A | あり | あり |
| `policy_assist` | 政策支援・対応方針提案 | あり | あり |
| `summarize` | 単一ファイルの要約（KB 経由） | あり | なし |
| `multi_summarize` | 複数ファイルの要約（KB 経由） | あり | なし |
| `summarize_structured` | 単一 PDF の構造化情報抽出（PDF 直接添付） | なし | なし |
| `multi_summarize_final` | 収集済みサマリーの集約・全体要約 | なし | なし |

---

## トラブルシューティング

| エラー | 原因 | 対処 |
|-------|------|------|
| `Cannot find module 'aws-cdk-lib'` | 依存パッケージ未インストール | `npm ci` を実行 |
| `Invalid principal in policy: DummyRole` | `switchRoleName` に未存在のロール名が設定されている | `parameter.ts` で `switchRoleName: ""` を設定 |
| `The parameter contains formatting that is not valid` (WAF) | `0.0.0.0/0` は WAF IP セットで使用不可 | 実際の IP または `null` を設定 |
| `Timeout should be between 50 ms and 29000 ms` | `apiLambdaIntegrationTimeout` が 29 秒超 | `parameter.ts` で `apiLambdaIntegrationTimeout: 29` を設定 |
| `idcUserNames and switchRoleName must be set` | SSO 設定なし、かつ IAM 設定もなし | `iamPrincipalArns` に IAM ユーザー ARN を設定 |
| `Unable to delete data from vector store` (destroy 失敗) | DataSource 削除時に S3 Vectors のデータ削除が失敗 | DataSource を手動削除してから再度 destroy |
| 引用ファイルが一部の参考情報にしか表示されない | S3 Vectors KB は URL なしで `file_name` のみ返すことがある | `reference_generation.py` で `file_name` のみでも表示するよう修正済み |
| 参考情報に「。」だけの引用文が表示される | PDF チャンキングの境界が文中に入り句点のみのチャンクが生成された | PDF → Markdown 変換後に再インジェスト、または `reference_generation.py` の `MIN_CITATION_LEN` フィルタで対応済み |

### `cdk destroy` が DataSource 削除で失敗した場合

```bash
aws bedrock-agent delete-data-source \
  --knowledge-base-id <KB_ID> \
  --data-source-id <DS_ID> \
  --region ap-northeast-1

cdk destroy --all -c env=-dev
```
