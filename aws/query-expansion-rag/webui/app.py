import base64
import json
import os

import boto3
import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

app = Flask(__name__)

APP_NAME = os.environ.get("APP_NAME", "qerag-s3v")
REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")
DOC_DIR = os.environ.get("DOC_DIR", os.path.join(os.path.dirname(__file__), "../tools/add_metadata_json/doc"))
RECORDS_DIR = os.environ.get("RECORDS_DIR", os.path.join(os.path.dirname(__file__), "../tools/add_metadata_json/records"))

_api_endpoint = None
_api_key = None


def get_api_config():
    global _api_endpoint, _api_key
    if _api_endpoint and _api_key:
        return _api_endpoint, _api_key

    stack_name = f"{APP_NAME}-qeRagApi"
    cf = boto3.client("cloudformation", region_name=REGION)
    outputs = cf.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    output_map = {o["OutputKey"]: o["OutputValue"] for o in outputs}

    _api_endpoint = output_map["ApiEndpoint"]
    api_key_id = output_map["ApiKeyId"]

    apigw = boto3.client("apigateway", region_name=REGION)
    _api_key = apigw.get_api_key(apiKey=api_key_id, includeValue=True)["value"]

    return _api_endpoint, _api_key


@app.route("/nck-portal/<path:filename>")
def serve_doc(filename):
    return send_from_directory(os.path.abspath(DOC_DIR), filename)


@app.route("/api/records")
def list_records():
    records_path = os.path.abspath(RECORDS_DIR)
    files = sorted([f for f in os.listdir(records_path) if f.endswith(".pdf")])
    return jsonify(files)


@app.route("/records/<path:filename>")
def serve_record(filename):
    return send_from_directory(os.path.abspath(RECORDS_DIR), filename)


@app.route("/")
def index():
    return render_template("index.html", app_name=APP_NAME)


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    question = data.get("question", "").strip()
    n_queries = int(data.get("n_queries", 3))
    output_in_detail = bool(data.get("output_in_detail", False))
    mode = data.get("mode", "qa")
    if mode not in ("qa", "policy_assist", "summarize", "multi_summarize", "summarize_structured", "multi_summarize_final"):
        mode = "qa"
    file_name = data.get("file_name", "").strip()
    file_names = data.get("file_names", [])

    if mode not in ("summarize", "multi_summarize", "summarize_structured") and not question:
        if not (mode == "policy_assist" and file_name):
            return jsonify({"error": "質問を入力してください"}), 400
    if mode in ("summarize", "summarize_structured") and not file_name:
        return jsonify({"error": "file_name is required for summarize mode"}), 400
    if mode == "multi_summarize" and (not isinstance(file_names, list) or len(file_names) < 2):
        return jsonify({"error": "file_names must be a list of at least 2 items"}), 400
    if mode == "multi_summarize_final" and not question:
        return jsonify({"error": "question is required for multi_summarize_final mode"}), 400

    max_chars = int(data.get("max_chars", 0))
    if max_chars < 0:
        max_chars = 0

    inputs = {"question": question, "n_queries": n_queries, "output_in_detail": output_in_detail, "mode": mode}
    if file_name:
        inputs["file_name"] = file_name
    if file_names:
        inputs["file_names"] = file_names
    if max_chars > 0:
        inputs["max_chars"] = max_chars

    # policy_assist: PDFを直接添付してKB検索に活用
    if mode == "policy_assist" and file_name:
        records_dir = os.path.realpath(os.path.abspath(RECORDS_DIR))
        record_path = os.path.realpath(os.path.join(records_dir, file_name))
        if not record_path.startswith(records_dir + os.sep):
            return jsonify({"error": "Invalid file name"}), 400
        if not os.path.isfile(record_path):
            return jsonify({"error": f"Record file not found: {file_name}"}), 404
        with open(record_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("utf-8")
        inputs["files"] = [{"key": "record", "files": [{"filename": file_name, "content": pdf_b64}]}]
        if not question:
            inputs["question"] = "添付の相談記録に基づいて対応方針を提案してください"

    # summarize_structured: PDFを直接添付してKB検索をバイパス
    if mode == "summarize_structured" and file_name:
        records_dir = os.path.realpath(os.path.abspath(RECORDS_DIR))
        record_path = os.path.realpath(os.path.join(records_dir, file_name))
        if not record_path.startswith(records_dir + os.sep):
            return jsonify({"error": "Invalid file name"}), 400
        if not os.path.isfile(record_path):
            return jsonify({"error": f"Record file not found: {file_name}"}), 404
        with open(record_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("utf-8")
        inputs["files"] = [{"key": "record", "files": [{"filename": file_name, "content": pdf_b64}]}]

    try:
        endpoint, api_key = get_api_config()
        resp = requests.post(
            endpoint,
            headers={"Content-Type": "application/json", "x-api-key": api_key},
            json={"inputs": inputs},
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
        return jsonify({"answer": body.get("outputs", ""), "usage": body.get("usageMetadata", {})})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
