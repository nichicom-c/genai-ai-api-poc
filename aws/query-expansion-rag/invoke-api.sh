#!/bin/bash
set -euo pipefail

# -------------------------------------------------------
# Usage:
#   ./invoke-api.sh "質問文"
#   ./invoke-api.sh "質問文" --detail     # 詳細モード
#   ./invoke-api.sh "質問文" --queries 5  # クエリ拡張数指定
# -------------------------------------------------------

APP_NAME="${APP_NAME:-qerag-s3v}"
ENV="${ENV:--dev}"
STACK_NAME="${APP_NAME}-qeRagApi"

# --- 引数パース ---
QUESTION="${1:?Usage: $0 <question> [--detail] [--queries N]}"
shift

OUTPUT_IN_DETAIL=false
N_QUERIES=3

while [[ $# -gt 0 ]]; do
  case "$1" in
    --detail)   OUTPUT_IN_DETAIL=true; shift ;;
    --queries)  N_QUERIES="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# --- CDK スタック出力からエンドポイントと API Key ID を取得 ---
echo "Fetching stack outputs from: ${STACK_NAME}"

API_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text)

API_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiKeyId'].OutputValue" \
  --output text)

if [[ -z "${API_ENDPOINT}" || -z "${API_KEY_ID}" ]]; then
  echo "Error: Could not retrieve stack outputs. Is the stack deployed?" >&2
  exit 1
fi

# --- API キーの値を取得 ---
API_KEY=$(aws apigateway get-api-key \
  --api-key "${API_KEY_ID}" \
  --include-value \
  --query "value" \
  --output text)

# --- API 呼び出し ---
echo "Endpoint : ${API_ENDPOINT}"
echo "Question : ${QUESTION}"
echo "N_Queries: ${N_QUERIES}, Detail: ${OUTPUT_IN_DETAIL}"
echo "---"

curl -s -X POST "${API_ENDPOINT}" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${API_KEY}" \
  -d "$(jq -n \
    --arg q "${QUESTION}" \
    --argjson n "${N_QUERIES}" \
    --argjson d "${OUTPUT_IN_DETAIL}" \
    '{inputs: {question: $q, n_queries: $n, output_in_detail: $d}}')" \
  | jq .
