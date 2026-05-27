from typing import TYPE_CHECKING, Any

from aws_lambda_powertools import Logger
from config.config_manager import ConfigManager
from services.converse_helper import invoke_converse_simple
from services.kb_response_processor import KBResponse
from utils.utils import replacePlaceholders

if TYPE_CHECKING:
    from services.bedrock_usage_tracker import BedrockUsageTracker

# Set logger
SERVICE_NAME = "query-expansion-rag-lambda"
logger = Logger(service=SERVICE_NAME)


def generate_answer(
    user_question: str,
    output_in_detail: bool,
    kb_response: KBResponse,
    file_content_blocks: list[dict[str, Any]] | None = None,
    system_prompt_override: str | None = None,
    usage_tracker: BedrockUsageTracker | None = None,
    mode: str = "qa",
    max_chars: int = 0,
    file_names: list[str] | None = None,
) -> str:
    citations_texts = [citation.text for citation in kb_response.citations]
    logger.debug(f"Answer generation, citations texts: {citations_texts}")

    # 設定タイプを決定
    if mode == "multi_summarize":
        config_type = "multi_summarize"
    elif mode == "summarize":
        config_type = "summarize"
    elif mode == "summarize_structured":
        config_type = "summarize_structured"
    elif mode == "multi_summarize_final":
        config_type = "multi_summarize_aggregate"
    elif mode == "policy_assist":
        config_type = "policy_assist"
    elif output_in_detail:
        config_type = "answer_generation_detail"
    else:
        config_type = "answer_generation"

    # 設定マネージャーを初期化
    config = ConfigManager(config_type)

    # システムプロンプト取得（優先順位: リクエストBody > アプリ設定 > デフォルト設定）
    if system_prompt_override:
        system_prompt = system_prompt_override
        logger.info(f"Using system prompt from request body for {config_type}")
    else:
        system_prompt = config.get_system_prompt()
        if not system_prompt:
            logger.warning(f"No system prompt found for {config_type}, using default")
            system_prompt = "Please answer the question based on the provided context."

    # プロンプトにプレースホルダを適用
    placeholders: dict[str, str] = {
        "question": user_question,
        "context": "\n".join(citations_texts),
    }
    if mode == "multi_summarize" and file_names:
        placeholders["file_names"] = "\n".join(f"- {f}" for f in file_names)
    if mode == "summarize_structured":
        placeholders["max_chars"] = str(max_chars) if max_chars > 0 else "100"

    placeholder_replaced_prompt = replacePlaceholders(system_prompt, placeholders)

    # 文字数制限が指定されている場合はプロンプトに追記
    if max_chars > 0 and mode in ("summarize", "multi_summarize"):
        placeholder_replaced_prompt += f"\n\n出力は{max_chars}文字以内に収めてください。"
        logger.debug(f"Appended max_chars constraint: {max_chars}")

    # モデルID取得
    model_id = config.get_model_id()
    logger.debug(f"Using model: {model_id}")

    # 推論設定取得
    inference_config = config.get_inference_config()
    logger.debug(f"Inference config: {inference_config}")

    # 添付ファイルがある場合はログに記録
    if file_content_blocks:
        logger.info(f"Answer generation with {len(file_content_blocks)} file attachments")

    # モデル呼び出し
    # converse_helperを使用して、添付ファイルをサポート
    converse_resp_text, usage = invoke_converse_simple(
        model_id=model_id,
        user_message_text=placeholder_replaced_prompt,
        inference_config=inference_config,
        file_content_blocks=file_content_blocks,
    )

    # usage_trackerが渡されていれば記録
    if usage_tracker and usage:
        usage_tracker.add_usage(model_id, usage)

    logger.debug(f"Answer generation response: {converse_resp_text[:200]}...")

    return converse_resp_text
