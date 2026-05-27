# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### CDK (TypeScript)
```bash
npm ci                          # install dependencies
npm run build                   # compile TypeScript
npm run lint                    # ESLint (enforces --max-warnings 0)
npm test                        # Jest unit tests
cdk list                        # list stacks
cdk deploy --all -c env=-dev    # deploy all stacks (env: -dev / -stg / -prd)
cdk destroy --all -c env=-dev   # destroy all stacks
```

### Python Lambda tests
```bash
cd lib/constructs/rag-lambda/invokeModel
pip install -r requirements.txt
pytest tests/
```

### Web UI
```bash
cd webui
pip install -r requirements.txt
AWS_PROFILE=<profile> APP_NAME=qerag-s3v python app.py
# → http://localhost:5000
```
The Web UI reads the API endpoint and API key automatically from the deployed CloudFormation stack outputs.

## Architecture

### Request flow
```
Client
  → API Gateway (REST, x-api-key, WAF IP filtering)
  → Lambda (Python)
      1. parse_input()            — validate inputs, resolve mode
      2. expand_query()           — Bedrock Converse: 1–5 search queries
      3. invoke_retrives()        — Bedrock KB retrieve × n_queries, LLM relevance rating (parallel)
      4. generate_answer()        — Bedrock Converse: answer from top-rated context chunks
      5. generate_reference()     — format citation list  [skipped in summarize modes]
  → { outputs, usageMetadata }
```

### CDK stacks (one set per app, created in `bin/qe-rag-apis.ts`)
| Stack | Purpose |
|---|---|
| `APIWafStack` | Shared WAF WebACL (IP allow-list, country filtering) |
| `SwitchRoleStack` | Developer IAM role (assume via SSO or direct ARN) |
| `RagS3VectorsKbStack` | S3 Vectors Knowledge Base + S3 data source bucket |
| `RagKnowledgeBaseStack` | OpenSearch Serverless Knowledge Base (alternative) |
| `RagLambdaApiStack` | API Gateway + Lambda + CloudWatch + KMS CMEK |

App names are declared in `cdk.json` under `qeRagAppNames`, `qeRagAppNamesWithSharedCmek`, and `qeRagAppNamesWithS3Vectors`. Environment-specific parameter overrides live in `parameter.ts` and are validated with a Zod schema in `lib/stack-input.ts`.

### Lambda pipeline modules (`lib/constructs/rag-lambda/invokeModel/`)
| File | Role |
|---|---|
| `app.py` | Handler entry point; parses inputs, routes modes, assembles response |
| `core/query_expansion.py` | Generates multiple search queries via Bedrock Converse |
| `core/kb_retrieve_and_rating.py` | Parallel KB retrieval + LLM relevance scoring |
| `core/answer_generation.py` | Final answer generation; injects context and char-limit constraint |
| `core/reference_generation.py` | Formats citation markdown from KB response metadata |
| `config/config_manager.py` | Loads and merges TOML config layers |
| `services/bedrock_usage_tracker.py` | Accumulates token usage across all Bedrock calls |

### Request modes
| `mode` | Description |
|---|---|
| `qa` (default) | General Q&A with query expansion |
| `policy_assist` | Policy/response recommendation using past cases as context |
| `summarize` | Summarize a single document (`file_name` required) |
| `multi_summarize` | Summarize multiple documents (`file_names` list, min 2) |

In `summarize`/`multi_summarize` modes, query expansion is skipped (fixed query used instead) and references/footer are omitted from the response.

## Configuration system

Inference behaviour is controlled by a three-layer TOML system:

1. **Default per-phase configs** — `config/defaults/<phase>.toml`  
   Defines `modelId`, `maxTokens`, `temperature`, and `systemPrompt` for each inference phase (`answer_generation`, `query_expansion`, `relevance_rating`, `summarize`, `multi_summarize`, `policy_assist`, etc.).

2. **App-specific overrides** — `config/apps/<APP_PARAM_FILE>`  
   Sections like `[answer_generation]` override only the keys that differ from defaults. The file to load is specified via the Lambda environment variable `APP_PARAM_FILE`.

3. **Request-level override** — `systemPromptForAnswerGeneration` field in the API request body overrides the system prompt at runtime.

`ConfigManager` merges these layers at runtime: app config wins over defaults, request override wins over app config.

### Key Lambda environment variables
| Variable | Purpose |
|---|---|
| `KNOWLEDGE_BASE_ID` | Bedrock Knowledge Base ID |
| `KB_NUM_RESULTS` | Chunks retrieved per query (default: 10) |
| `APP_NAME` | Application identifier |
| `APP_PARAM_FILE` | TOML filename under `config/apps/` (e.g. `qerag.toml`) |
| `LOG_LEVEL` | Powertools log level |

## CDK deployment notes

- Lambda is bundled locally (no Docker): `pip install -r requirements.txt -t <output>`. Config TOML files are hashed to trigger re-bundling when prompts change.
- KMS keys use `RemovalPolicy.RETAIN` — they are never deleted by `cdk destroy`.
- S3 Vectors stacks require manual data source deletion before `cdk destroy`:
  ```bash
  aws bedrock-agent delete-data-source --knowledge-base-id <KB_ID> --data-source-id <DS_ID>
  ```
- OpenSearch Serverless stacks use a CDK custom resource Lambda to create the vector index on first deploy.
- CloudFormation outputs include `ApiEndpoint` and `ApiKeyId`; retrieve the key value with:
  ```bash
  aws apigateway get-api-key --api-key <ApiKeyId> --include-value
  ```
