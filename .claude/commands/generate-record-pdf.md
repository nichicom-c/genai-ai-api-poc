# generate-record-pdf

HTMLテンプレートから、1人の対象者に関する**5件の相談記録PDF**を時系列で生成し、`records/` フォルダに保存するコマンドです。各記録には何らかの問題が示唆される内容を含め、最後にデータ概要をまとめたREADMEも生成します。

## 使い方

```
/generate-record-pdf [テンプレートパス] [ケースID]
```

**引数:**
- `テンプレートパス`（省略可）: 使用するHTMLテンプレートのパス。省略時はデフォルト値を使用。
- `ケースID`（省略可）: 出力ファイル名のプレフィックス（例: `case_001`）。省略時は `case_001` を使用。

**出力先:** `aws/query-expansion-rag/tools/add_metadata_json/records/`

---

## 実行手順

引数 `$ARGUMENTS` を解析し、以下の手順で5件のPDFと1件のREADMEを生成してください。

### ステップ1: 引数の解析

`$ARGUMENTS` をスペース区切りで分割し：
- 第1引数 → テンプレートHTMLのパス（なければデフォルト値を使用）
- 第2引数 → ケースID（なければ `case_001` を使用）

デフォルト値：
- テンプレートパス: `/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/webui/record_templates/consultation_record.html`
- ケースID: `case_001`

### ステップ2: テンプレートの読み込み

指定されたHTMLテンプレートを Read ツールで読み込み、フォームの構造を把握する。

### ステップ3: ケースデザイン（生成前に設計する）

以下の要素を決定する（毎回ランダムに選ぶこと）：

**対象者プロフィール（架空）:**
- 氏名（例：山田 花子、鈴木 健一 など）
- 年齢・性別
- 家族構成
- 住所（架空の市区町村）
- 職業・生活状況

**問題シナリオ（以下からランダムに1つ選択）:**
1. **育児不安・虐待リスク** — 乳幼児の養育に悩む親。疲弊・孤立が深まり、子どもへの不適切な関わりが疑われるようになる
2. **精神的不調・社会的孤立** — うつ症状・引きこもり傾向。支援を拒みがちだが、徐々に状態が悪化する
3. **家庭内暴力（DV）** — パートナーからの暴力を示唆する発言が断片的に現れる。安全確保が課題となる
4. **介護疲れ・高齢者虐待リスク** — 介護者の疲弊が蓄積し、被介護者への不適切な対応が懸念される
5. **経済的困窮・生活崩壊** — 生活費・住居の問題が重なり、精神状態も悪化していく

**5回の相談の時系列（問題が徐々に示唆されるよう設計）:**
- 第1回: 表面上は軽微な相談、問題の芽が見え隠れする
- 第2回: やや深刻な状況が浮かび上がる
- 第3回: 問題が明確化し始める、保健師が懸念を持つ
- 第4回: 問題が顕在化、緊急性を帯びる
- 第5回: 支援方針が固まる、または状況が一段と複雑になる

日付は令和年号で、数週間〜数ヶ月の間隔で設定すること。

### ステップ4: 5件分のHTMLを生成・保存

テンプレートの構造を維持したまま、各セルにリアルなサンプルデータを日本語で記入したHTMLを5件作成する。

**各HTMLの記入方針:**
- `font-family` に `"Noto Sans CJK JP"` を先頭に追加してCJKフォントを確実に適用する
- 相談日時・対象者・相談方法・目的・主訴・状況（客観的）・状況（主観的）・分析・判断・対応・今後の計画 を各回のシナリオに沿って記入する
- 主訴・状況・対応などの本文はそれぞれ100〜200文字程度の具体的な内容にする
- 各記録が単独で読めるが、全体を通して読むと問題が浮かび上がる構成にする
- 問題の記述は断片的・間接的な表現にとどめ、相談記録らしいリアルさを保つ

生成した各HTMLを以下のパスに Write ツールで保存する：
```
/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/tools/add_metadata_json/records/{ケースID}_01.html
/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/tools/add_metadata_json/records/{ケースID}_02.html
/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/tools/add_metadata_json/records/{ケースID}_03.html
/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/tools/add_metadata_json/records/{ケースID}_04.html
/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/tools/add_metadata_json/records/{ケースID}_05.html
```

### ステップ5: weasyprint で5件分のPDF変換

weasyprint が未インストールの場合は先に `pip3 install weasyprint --break-system-packages` を実行する。

その後、以下のPythonスクリプトを Bash ツールで実行してPDFを一括生成する：

```bash
python3 -c "
import weasyprint, os
base = '/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/tools/add_metadata_json/records'
case_id = '{ケースID}'
for i in range(1, 6):
    suffix = f'{i:02d}'
    html_path = os.path.join(base, f'{case_id}_{suffix}.html')
    pdf_path  = os.path.join(base, f'{case_id}_{suffix}.pdf')
    weasyprint.HTML(filename=html_path).write_pdf(pdf_path)
    print('Generated:', pdf_path)
"
```

### ステップ6: READMEの生成

以下のパスに、生成したケースの概要をまとめたREADMEを Write ツールで作成する：
```
/home/dang/work/gen_ai/genai-ai-api/aws/query-expansion-rag/tools/add_metadata_json/records/{ケースID}_README.md
```

READMEには以下の情報を含める（Markdown形式）：
- **ケースID**
- **生成日時**（実行時の日付）
- **対象者プロフィール**（氏名・年齢・家族構成・住所・職業）
- **問題シナリオの種別**（選択したシナリオ名）
- **問題シナリオの概要**（2〜3文で説明）
- **各相談記録の概要**（No.・相談日時・相談方法・主な内容・保健師の懸念ポイントを表形式で）
- **RAGシステムでの利用想定**（このデータがどういうテスト用途に適するか1〜2文）
- **生成ファイル一覧**（ファイル名・サイズは後述の `ls` 結果から記載）

### ステップ7: 完了報告

生成されたPDF・HTMLおよびREADMEのファイル一覧を `ls -lh` で確認し、ユーザーに報告する。
