#!/usr/bin/env python3
"""S3 Vectors のメタデータを確認するスクリプト。

使い方:
  # バケット一覧
  python3 inspect_s3vectors.py

  # 特定バケットのインデックス一覧
  python3 inspect_s3vectors.py --bucket qerag-s3v-s3v-bucket

  # インデックスのベクターとメタデータを表示
  python3 inspect_s3vectors.py --bucket qerag-s3v-s3v-bucket --index qerag-s3v-s3v-index

  # AWS プロファイル指定
  python3 inspect_s3vectors.py --profile myprofile --bucket qerag-s3v-s3v-bucket --index qerag-s3v-s3v-index

  # 件数制限・ベクター値を非表示
  python3 inspect_s3vectors.py --bucket qerag-s3v-s3v-bucket --index qerag-s3v-s3v-index --limit 20 --no-vectors
"""

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError


def make_client(profile: str | None, region: str) -> boto3.client:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client("s3vectors", region_name=region)


# ──────────────────────────────────────────────
# バケット一覧
# ──────────────────────────────────────────────
def list_buckets(client) -> None:
    print("=== Vector Buckets ===")
    paginator = client.get_paginator("list_vector_buckets")
    buckets = []
    for page in paginator.paginate():
        buckets.extend(page.get("vectorBuckets", []))

    if not buckets:
        print("  (バケットなし)")
        return

    for b in buckets:
        print(f"  • {b['vectorBucketName']}")
        if "creationTime" in b:
            print(f"      作成日時: {b['creationTime']}")
        if "encryptionConfiguration" in b:
            enc = b["encryptionConfiguration"]
            print(f"      暗号化: {enc.get('sseType', '-')}  KMS: {enc.get('kmsKeyArn', '-')}")
    print(f"\n合計 {len(buckets)} バケット")


# ──────────────────────────────────────────────
# インデックス一覧
# ──────────────────────────────────────────────
def list_indexes(client, bucket: str) -> None:
    print(f"=== Indexes in '{bucket}' ===")
    paginator = client.get_paginator("list_indexes")
    indexes = []
    for page in paginator.paginate(vectorBucketName=bucket):
        indexes.extend(page.get("indexes", []))

    if not indexes:
        print("  (インデックスなし)")
        return

    for idx in indexes:
        name = idx["indexName"]
        print(f"\n  ▸ {name}")
        for key in ("dimension", "dataType", "distanceMetric"):
            if key in idx:
                print(f"      {key}: {idx[key]}")
        if "metadataConfiguration" in idx:
            mc = idx["metadataConfiguration"]
            print(f"      非フィルタキー: {mc.get('nonFilterableMetadataKeys', [])}")
        if "creationTime" in idx:
            print(f"      作成日時: {idx['creationTime']}")

    print(f"\n合計 {len(indexes)} インデックス")


# ──────────────────────────────────────────────
# ベクター一覧（メタデータ付き）
# ──────────────────────────────────────────────
def list_vectors(client, bucket: str, index: str, limit: int, show_vectors: bool) -> None:
    print(f"=== Vectors in '{bucket}/{index}' ===")

    # インデックス設定を先に表示
    try:
        idx = client.get_index(vectorBucketName=bucket, indexName=index)
        print(f"  次元数: {idx.get('dimension', '-')}  距離: {idx.get('distanceMetric', '-')}  型: {idx.get('dataType', '-')}")
        if "metadataConfiguration" in idx:
            mc = idx["metadataConfiguration"]
            nf = mc.get("nonFilterableMetadataKeys", [])
            print(f"  非フィルタキー: {nf}")
    except ClientError as e:
        print(f"  (インデックス情報取得失敗: {e})")

    print()

    total = 0
    next_token = None
    keys_seen: set[str] = set()

    while True:
        kwargs: dict = {
            "vectorBucketName": bucket,
            "indexName": index,
            "returnData": show_vectors,
            "returnMetadata": True,
        }
        if next_token:
            kwargs["nextToken"] = next_token

        resp = client.list_vectors(**kwargs)
        vectors = resp.get("vectors", [])

        for v in vectors:
            total += 1
            if total > limit:
                break

            vid = v.get("key", "-")
            metadata = v.get("metadata", {})
            keys_seen.update(metadata.keys())

            print(f"[{total}] key: {vid}")
            if metadata:
                for k, val in metadata.items():
                    print(f"      {k}: {val}")
            else:
                print("      (メタデータなし)")

            if show_vectors and "data" in v:
                data = v["data"]
                if isinstance(data, dict) and "float32" in data:
                    vec = data["float32"]
                    preview = vec[:4]
                    print(f"      vector[{len(vec)}]: {preview}…")

            print()

        if total >= limit:
            print(f"  ※ --limit {limit} で打ち切り")
            break

        next_token = resp.get("nextToken")
        if not next_token:
            break

    print(f"合計 {total} ベクター表示")
    if keys_seen:
        print(f"メタデータキー一覧: {sorted(keys_seen)}")


# ──────────────────────────────────────────────
# エントリポイント
# ──────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="S3 Vectors のバケット / インデックス / メタデータを確認する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--profile", help="AWS プロファイル名")
    parser.add_argument("--region", default="ap-northeast-1", help="AWSリージョン (デフォルト: ap-northeast-1)")
    parser.add_argument("--bucket", help="Vector Bucket 名 (省略時はバケット一覧)")
    parser.add_argument("--index", help="Index 名 (省略時はインデックス一覧)")
    parser.add_argument("--limit", type=int, default=50, help="表示件数上限 (デフォルト: 50)")
    parser.add_argument("--no-vectors", action="store_true", help="ベクター値を取得しない")
    args = parser.parse_args()

    try:
        client = make_client(args.profile, args.region)

        if not args.bucket:
            list_buckets(client)
        elif not args.index:
            list_indexes(client, args.bucket)
        else:
            list_vectors(client, args.bucket, args.index, args.limit, not args.no_vectors)

    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        print(f"AWS エラー [{code}]: {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
