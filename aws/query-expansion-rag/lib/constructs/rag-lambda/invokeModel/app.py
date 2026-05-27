import json
import os
import uuid

from aws_lambda_powertools import Logger, Tracer
from config.config_manager import ConfigManager
from core.answer_generation import generate_answer
from core.kb_retrieve_and_rating import invoke_retrives
from core.query_expansion import expand_query
from core.reference_generation import generate_reference
from services.bedrock_usage_tracker import BedrockUsageTracker
from services.kb_response_processor import KBResponse
from utils.file_handler import FileValidationError, process_files, truncate_files_for_logging
from utils.utils import handleException

# Set logger and tracer
SERVICE_NAME = "query-expansion-rag-lambda"
logger = Logger(service=SERVICE_NAME)
tracer = Tracer(service=SERVICE_NAME)


def get_response_footer():
    """アプリケーション設定からレスポンスフッターを取得する関数"""
    # 環境変数からAPP_NAMEを取得
    app_name = os.environ.get("APP_NAME", "")
    response_footer = ""

    # アプリ設定が存在する場合はアプリ設定からレスポンスフッターを取得
    if app_name:
        try:
            # ConfigManagerを使用してアプリ設定を読み込む
            # どのタイプの設定でも共通項目は同じなので、answer_generationを指定
            config = ConfigManager("answer_generation")

            # アプリ設定からレスポンスフッターを取得
            if config.app_config and "responseFooter" in config.app_config:
                response_footer = config.app_config["responseFooter"]
                logger.debug(f"Response footer loaded from app config: {response_footer[:30]}...")
            else:
                logger.warning(f"Response footer not found in app config for {app_name}")
        except Exception as e:
            logger.error(f"Error loading response footer from app config: {str(e)}")

    # 取得できなかった場合はデフォルト値を使用
    if not response_footer:
        response_footer = "※ この回答は生成AIにより作成されています。"
        logger.debug("Using default response footer")

    return response_footer


def parse_input(event):
    # API Gatewayからのリクエストを解析
    body = json.loads(event.get("body", "{}"))
    inputs = body.get("inputs", {})

    # ログ出力用にファイル内容をトランケート
    truncated_inputs = truncate_files_for_logging(inputs)
    logger.debug(f"Inputs received: {truncated_inputs}")

    # modeを先に取得（バリデーションに使うため）
    mode = inputs.get("mode", "qa")
    if mode not in ("qa", "policy_assist", "summarize", "multi_summarize", "summarize_structured", "multi_summarize_final"):
        mode = "qa"

    # ユーザーの質問を取得（summarize系モードは空可）
    user_question = inputs.get("question", "")
    if not user_question and mode not in ("summarize", "multi_summarize", "summarize_structured"):
        raise ValueError("question is required")
    logger.debug(f"User question: {user_question}")

    # 添付ファイルの処理
    files_input = inputs.get("files", [])
    file_content_blocks = []
    if files_input:
        try:
            file_content_blocks = process_files(files_input)
            logger.info(f"Processed {len(file_content_blocks)} file attachments")
        except FileValidationError as e:
            logger.error(f"File validation error: {str(e)}")
            raise ValueError(f"File validation error: {str(e)}") from e

    # n_queriesのデフォルト値設定
    n_queries = inputs.get("n_queries", 3)
    if not isinstance(n_queries, int) or n_queries < 1:
        n_queries = 3
    logger.debug(f"n_queries: {n_queries}")

    # output_in_detailの取得
    output_in_detail = inputs.get("output_in_detail", False)
    logger.debug(f"output_in_detail: {output_in_detail}")

    logger.debug(f"mode: {mode}")

    # file_nameの取得（summarizeモード時に使用）
    file_name = inputs.get("file_name", "").strip()
    if mode in ("summarize", "summarize_structured") and not file_name:
        raise ValueError("file_name is required for summarize mode")
    logger.debug(f"file_name: {file_name}")

    # file_namesの取得（multi_summarizeモード時に使用）
    file_names = inputs.get("file_names", [])
    if mode == "multi_summarize":
        if not isinstance(file_names, list) or len(file_names) < 2:
            raise ValueError("file_names must be a list of at least 2 items for multi_summarize mode")
        file_names = [f.strip() for f in file_names if isinstance(f, str) and f.strip()]
    logger.debug(f"file_names: {file_names}")

    # アプリ設定からレスポンスフッターを取得
    response_footer = get_response_footer()

    # システムプロンプトのオーバーライド（オプション）
    system_prompt_override = inputs.get("systemPromptForAnswerGeneration", None)
    if system_prompt_override:
        logger.info("Using custom system prompt from request body")

    # ユーザーが指定したタグを取得
    user_tag = inputs.get("tags", "")

    # バリデーション: 文字列であることを確認
    if user_tag and not isinstance(user_tag, str):
        raise ValueError("tags must be a string")

    # 文字列をトリミング
    user_tag = user_tag.strip() if user_tag else ""
    logger.debug(f"User specified tag: {user_tag}")

    # 要約文字数制限の取得
    max_chars = inputs.get("max_chars", 0)
    if not isinstance(max_chars, int) or max_chars < 0:
        max_chars = 0
    logger.debug(f"max_chars: {max_chars}")

    return (
        user_question,
        n_queries,
        output_in_detail,
        response_footer,
        file_content_blocks,
        system_prompt_override,
        user_tag,
        mode,
        file_name,
        file_names,
        max_chars,
    )


def generate_metadata_filters(tag: str) -> dict | None:
    if not tag:
        return None

    # カンマで分割して複数タグを処理
    tags = [t.strip() for t in tag.split(",") if t.strip()]

    # 単一タグの場合
    if len(tags) == 1:
        return {"equals": {"key": "tags", "value": tags[0]}}

    # 複数タグの場合（OR条件）
    return {"orAll": [{"equals": {"key": "tags", "value": t}} for t in tags]}


def generate_file_name_filter(file_name: str) -> dict | None:
    if not file_name:
        return None
    return {"equals": {"key": "file_name", "value": file_name}}


def generate_multi_file_filter(file_names: list[str]) -> dict | None:
    if not file_names:
        return None
    if len(file_names) == 1:
        return {"equals": {"key": "file_name", "value": file_names[0]}}
    return {"orAll": [{"equals": {"key": "file_name", "value": f}} for f in file_names]}


def handler(event, context):
    try:
        # リクエスト開始をログに記録
        request_id = uuid.uuid4()
        logger.info(f"Request started: request_id={request_id}")

        # Usage trackerを初期化
        usage_tracker = BedrockUsageTracker()

        # API Gatewayからの入力を取得
        (
            user_question,
            n_queries,
            output_in_detail,
            response_footer,
            file_content_blocks,
            system_prompt_override,
            user_tag,
            mode,
            file_name,
            file_names,
            max_chars,
        ) = parse_input(event)

        # メタデータフィルタの生成（summarize_structured / multi_summarize_finalはKB不使用のためNone）
        if mode == "summarize":
            metadata_filters = generate_file_name_filter(file_name)
        elif mode == "multi_summarize":
            metadata_filters = generate_multi_file_filter(file_names)
        elif mode in ("summarize_structured", "multi_summarize_final"):
            metadata_filters = None
        else:
            metadata_filters = generate_metadata_filters(user_tag)
        logger.debug(f"Generated metadata filters: {metadata_filters}")

        # 添付ファイルが存在する場合はログに記録
        if file_content_blocks:
            logger.info(f"Processing request with {len(file_content_blocks)} file attachments")

        # summarize系モードはクエリ拡張をスキップして固定クエリを使用
        # summarize_structured / multi_summarize_finalはKB不要のためスキップ
        if mode == "summarize":
            queries = ["相談記録 主訴 状況 対応 計画"]
            logger.info(f"Summarize mode: using fixed query for file={file_name}")
        elif mode == "multi_summarize":
            queries = ["相談記録 主訴 状況 対応 計画"]
            logger.info(f"Multi-summarize mode: using fixed query for files={file_names}")
        else:
            queries = []
            if mode not in ("summarize_structured", "multi_summarize_final"):
                queries = expand_query(user_question, n_queries, file_content_blocks, usage_tracker)
        logger.debug(f"Expanded Queries: {queries}")

        # summarize_structured / multi_summarize_finalはKBを使用せず空のレスポンスを使用
        if mode in ("summarize_structured", "multi_summarize_final"):
            kb_responses_and_ratings = KBResponse()
            logger.info(f"{mode}: skipping KB retrieval, using empty KBResponse")
        else:
            # Knowledge Base からのretrieveとgenerateを実行し、LLMで評価する並列処理を実行
            logger.info("Knowledge base retrieve and relevance rating started")
            kb_responses_and_ratings = invoke_retrives(user_question, queries, usage_tracker, metadata_filters)
            logger.debug(f"kb_responses_and_ratings: {kb_responses_and_ratings}")

        # Knowledge Base から収集した関連情報をcontextして付与し回答を生成（添付ファイルとusage_trackerを渡す）
        logger.info("Answer generation started")
        answer_str = generate_answer(
            user_question,
            output_in_detail,
            kb_responses_and_ratings,
            file_content_blocks,
            system_prompt_override,
            usage_tracker,
            mode=mode,
            max_chars=max_chars,
            file_names=file_names if mode == "multi_summarize" else None,
        )

        # summarize系モードは参考情報・フッター不要
        if mode in ("summarize", "summarize_structured", "multi_summarize", "multi_summarize_final"):
            answer = answer_str
        else:
            reference_str = generate_reference(kb_responses_and_ratings)
            answer = answer_str + "\n\n" + response_footer + "\n\n" + reference_str
        logger.debug(f"Generated answer: {answer}")

        # usageMetadataを取得
        usage_metadata = usage_tracker.get_usage_summary()
        logger.debug(f"Usage metadata: {usage_metadata}")

        # リクエスト完了をログに記録
        logger.info(f"Request completed successfully: request_id={request_id}")

        # API Gateway Proxy形式のレスポンスを返す（usageMetadataを追加）
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"outputs": answer, "usageMetadata": usage_metadata}),
        }

    except ValueError as e:
        # バリデーションエラー
        logger.error(
            f"Request failed with validation error: request_id={request_id if 'request_id' in locals() else 'unknown'}, error={str(e)}"  # noqa: E501
        )
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": f"Invalid request: {str(e)}"}),
        }
    except Exception as e:
        print(f"Error in handler: {str(e)}")
        handleException(e, logger)
        logger.error(
            f"Request failed with internal error: request_id={request_id if 'request_id' in locals() else 'unknown'}"
        )
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Internal server error"}),
        }
