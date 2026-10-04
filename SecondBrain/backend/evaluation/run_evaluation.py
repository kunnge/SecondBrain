import json
import os

import requests

# 配置

# RAG Chat API 地址
API_URL = "http://localhost:8000/chat"

# 当前脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 测试问题文件
TEST_CASE_FILE = os.path.join(BASE_DIR, "test_cases.json")

# 所有测试结果的根目录
RESULT_DIR = os.path.join(BASE_DIR, "results")

# 获取下一次测试编号
def get_run_id():
    os.makedirs(RESULT_DIR, exist_ok=True)
    result_dirs = [name for name in os.listdir(RESULT_DIR)if name.startswith("result") and name[6:].isdigit()]
    if not result_dirs:
        return 1
    numbers = [int(name[6:])for name in result_dirs]
    return max(numbers) + 1
# 本次测试编号
RUN_ID = get_run_id()

# 本次测试结果目录
CURRENT_RESULT_DIR = os.path.join(RESULT_DIR,f"result{RUN_ID}")

# 每一次请求最多等待 60 秒
REQUEST_TIMEOUT = 60

# 读取测试问题
def load_test_cases():
    """读取测试问题"""
    with open(TEST_CASE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
# 保存 JSON
def save_json(data, filename):
    """保存 JSON 到本次测试结果文件夹"""
    os.makedirs(CURRENT_RESULT_DIR, exist_ok=True)
    filepath = os.path.join(CURRENT_RESULT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
    return filepath
# 调用 RAG API
def call_chat_api(test_case):
    """调用 RAG Chat API"""
    payload = {
        "query": test_case["query"],
        "document_id": test_case.get("document_id"),
        "history": test_case.get("history"),
        "top_k": test_case.get("top_k")
    }
    response = requests.post(
        API_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )
    # 解析 API 返回的 JSON
    result = response.json()
    return {
        "success": True,
        "request": payload,
        "status_code": response.status_code,
        "response": result
    }
# 单题测试
def evaluate_case(test_case):
    """测试单个问题"""
    case_id = test_case.get("id")
    print("\n" + "=" * 60)
    print(f"正在测试：{case_id}")
    print(f"问题：{test_case['query']}")
    print("=" * 60)
    # 调用 RAG API
    result = call_chat_api(test_case)
    # 保存当前问题的完整响应
    filepath = save_json(result, f"{case_id}.json")
    if result["success"]:
        print("✅ 请求成功")
        print(f"响应文件：{filepath}")
    else:
        print("❌ 请求失败")
        print(f"错误：{result.get('error')}")
        print(f"响应文件：{filepath}")
def main():
    print("=" * 60)
    print("RAG 自动化问题测试")
    print("=" * 60)
    # 读取测试问题
    try:
        test_cases = load_test_cases()
    except Exception as e:
        print(f"读取 test_cases.json 失败：{e}")
        return
    print(f"测试数量：{len(test_cases)}")
    # 创建本次测试的结果目录
    os.makedirs(CURRENT_RESULT_DIR, exist_ok=True)
    # 逐题调用 RAG
    for test_case in test_cases:
        evaluate_case(test_case)
    print("\n" + "=" * 60)
    print("全部测试完成")
    print("=" * 60)
if __name__ == "__main__":
    main()