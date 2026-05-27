#!/bin/bash
set -euo pipefail

# -------------------------------------------------------
# Usage:
#   ./upload-docs.sh <docs_dir>
#   ./upload-docs.sh doc
#   APP_NAME="my-app" ./upload-docs.sh doc
# -------------------------------------------------------

APP_NAME="${APP_NAME:-qerag-s3v}"
STACK_NAME="${APP_NAME}-qeRagKB"
DOCS_DIR="${1:?Usage: $0 <docs_directory>}"

if [[ ! -d "${DOCS_DIR}" ]]; then
  echo "Error: Directory '${DOCS_DIR}' not found." >&2
  exit 1
fi

echo "Fetching S3 bucket name from stack: ${STACK_NAME}"

BUCKET=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --region ap-northeast-1 \
  --query "Stacks[0].Outputs[?OutputKey=='DataSourceBucketName'].OutputValue" \
  --output text)

if [[ -z "${BUCKET}" ]]; then
  echo "Error: Could not retrieve bucket name. Is the stack deployed?" >&2
  exit 1
fi

echo "Uploading '${DOCS_DIR}/' → s3://${BUCKET}/docs/"
aws s3 cp "${DOCS_DIR}/" "s3://${BUCKET}/docs/" --recursive

echo "Done. Files uploaded to s3://${BUCKET}/docs/"
