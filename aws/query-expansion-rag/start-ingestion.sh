#!/bin/bash
set -euo pipefail

# -------------------------------------------------------
# Usage:
#   ./start-ingestion.sh
#   APP_NAME="my-app" ./start-ingestion.sh
# -------------------------------------------------------

APP_NAME="${APP_NAME:-qerag-s3v}"
STACK_NAME="${APP_NAME}-qeRagKB"
REGION="ap-northeast-1"

echo "Fetching Knowledge Base info from stack: ${STACK_NAME}"

KB_ID=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --region "${REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='KnowledgeBaseId'].OutputValue" \
  --output text)

if [[ -z "${KB_ID}" ]]; then
  echo "Error: Could not retrieve Knowledge Base ID. Is the stack deployed?" >&2
  exit 1
fi

DS_ID=$(aws bedrock-agent list-data-sources \
  --knowledge-base-id "${KB_ID}" \
  --region "${REGION}" \
  --query "dataSourceSummaries[0].dataSourceId" \
  --output text)

echo "Knowledge Base ID : ${KB_ID}"
echo "Data Source ID    : ${DS_ID}"
echo "Starting ingestion job..."

JOB_ID=$(aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "${KB_ID}" \
  --data-source-id "${DS_ID}" \
  --region "${REGION}" \
  --query "ingestionJob.ingestionJobId" \
  --output text)

echo "Ingestion job started: ${JOB_ID}"
echo "Waiting for completion..."

while true; do
  STATUS=$(aws bedrock-agent get-ingestion-job \
    --knowledge-base-id "${KB_ID}" \
    --data-source-id "${DS_ID}" \
    --ingestion-job-id "${JOB_ID}" \
    --region "${REGION}" \
    --query "ingestionJob.status" \
    --output text)

  echo "  Status: ${STATUS}"

  if [[ "${STATUS}" == "COMPLETE" ]]; then
    echo "Ingestion completed successfully."
    break
  elif [[ "${STATUS}" == "FAILED" ]]; then
    echo "Error: Ingestion job failed." >&2
    exit 1
  fi

  sleep 10
done
