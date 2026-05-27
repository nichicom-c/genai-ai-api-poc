"""
PDF → Markdown 変換スクリプト

デジタルPDFをMarkdownに変換してKnowledge Base登録用ディレクトリに出力する。
変換後のMarkdownファイルには元のPDFの .metadata.json をコピーする。

Usage:
    python 03_pdf_to_markdown.py --src <pdf_dir> --dst <md_output_dir>
    python 03_pdf_to_markdown.py --src doc --dst doc_md
"""

import argparse
import json
import os
import shutil

import pymupdf4llm

parser = argparse.ArgumentParser(description="Convert PDFs to Markdown for Bedrock Knowledge Base ingestion")
parser.add_argument("--src", required=True, help="Source directory containing PDF files")
parser.add_argument("--dst", required=True, help="Destination directory for Markdown output")
args = parser.parse_args()

src_dir = os.path.abspath(args.src)
dst_dir = os.path.abspath(args.dst)

if not os.path.isdir(src_dir):
    raise SystemExit(f"Error: source directory not found: {src_dir}")

os.makedirs(dst_dir, exist_ok=True)

converted = 0
skipped = 0

for root, _dirs, files in os.walk(src_dir):
    rel_root = os.path.relpath(root, src_dir)
    out_root = os.path.join(dst_dir, rel_root) if rel_root != "." else dst_dir
    os.makedirs(out_root, exist_ok=True)

    for filename in files:
        if not filename.lower().endswith(".pdf"):
            continue

        pdf_path = os.path.join(root, filename)
        md_filename = filename[:-4] + ".md"  # case_001.pdf → case_001.md
        md_path = os.path.join(out_root, md_filename)

        print(f"Converting: {filename} → {md_filename}")
        try:
            md_text = pymupdf4llm.to_markdown(pdf_path)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_text)
        except Exception as e:
            print(f"  ERROR: {e}")
            skipped += 1
            continue

        # .metadata.json の処理
        src_meta = pdf_path + ".metadata.json"
        dst_meta = md_path + ".metadata.json"

        if os.path.isfile(src_meta):
            # 既存のメタデータをコピー（file_name は元のPDF名のままにする）
            shutil.copy2(src_meta, dst_meta)
            print(f"  Copied metadata: {os.path.basename(src_meta)}")
        else:
            # メタデータがない場合は file_name だけ設定
            meta = {"metadataAttributes": {"file_name": filename}}
            with open(dst_meta, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=4, ensure_ascii=False)
            print(f"  Created metadata: {os.path.basename(dst_meta)}")

        converted += 1

print(f"\nDone. Converted: {converted}, Skipped: {skipped}")
print(f"Output directory: {dst_dir}")
print(f"\nNext step: upload to S3")
print(f"  ./upload-docs.sh {args.dst}")
