"""CLI and reusable core for the LIMS Extraction ReAct Agent."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List

from dotenv import load_dotenv

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
sys.path.append(SRC_DIR)

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from mcp_server import MCPLIMSServer
from prompts import CHATBOT_BASELINE_PROMPT, MAX_ITERATIONS, REACT_AGENT_SYSTEM_PROMPT
from providers import get_llm_provider
from tools import reset_mock_database

load_dotenv()


def load_test_cases() -> List[Dict[str, Any]]:
    """Load the student's five acceptance scenarios."""
    config_path = os.path.join(PROJECT_ROOT, "config", "test_cases.json")
    if not os.path.exists(config_path):
        config_path = os.path.join(PROJECT_ROOT, "config", "test_cases.example.json")
    with open(config_path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_waterfall_trace(trace_data: list) -> str:
    """Persist an UTF-8 waterfall artifact and return its absolute path."""
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    trace_path = os.path.join(docs_dir, "trace_waterfall.json")
    with open(trace_path, "w", encoding="utf-8") as file:
        json.dump(trace_data, file, ensure_ascii=False, indent=2)
    print(f"📊 [OBSERVABILITY] Đã lưu {len(trace_data)} sự kiện tại '{trace_path}'.")
    return trace_path


def run_baseline_chatbot(user_query: str, provider) -> str:
    """Run the level-2 chatbot without tools."""
    response = provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    print(f"\n💬 [CHATBOT BASELINE] {user_query}\n🤖 {response}")
    return response


def _next_prompt(user_query: str, history: List[Dict[str, Any]]) -> str:
    """Build a provider-neutral prompt containing every prior observation."""
    lines = [user_query, "", "LỊCH SỬ REACT ĐÃ XÁC THỰC:"]
    for event in history:
        payload = json.dumps(event["observation"], ensure_ascii=False, separators=(",", ":"))
        lines.append(f"[Observation từ Tool {event['tool_name']}]: {payload}")
    lines.extend(
        [
            "",
            "Hãy suy luận tiếp: gọi tool kế tiếp nếu mục tiêu chưa hoàn tất; nếu đã đủ dữ liệu hoặc hành động cuối đã thành công, trả về Final Answer.",
        ]
    )
    return "\n".join(lines)


def _fallback_answer(observation: Dict[str, Any]) -> str:
    """Produce a safe domain answer if the model exhausts its iteration budget."""
    if not observation:
        return "Không thể hoàn tất yêu cầu vì chưa nhận được Observation hợp lệ từ MCP Server."
    if observation.get("status") == "NOT_FOUND":
        return observation.get("message", "Không tìm thấy dữ liệu yêu cầu trong LIMS.")
    if observation.get("sample_status") == "FAILED":
        return (
            f"Đã đánh dấu FAILED cho mẫu {observation.get('sample_id')} thuộc lô {observation.get('lot_id')}. "
            f"Lý do: {observation.get('failure_reason')}. Lô vẫn ở trạng thái {observation.get('lot_status')}; "
            "các mẫu còn lại không bị ảnh hưởng."
        )
    data = observation.get("data", {})
    samples = data.get("samples", [])
    details = "; ".join(
        f"{sample.get('sample_id')}: {sample.get('yield_ng_ul')} ng/µL ({sample.get('status')})"
        for sample in samples
    )
    return (
        f"Lô {data.get('lot_id')} — {data.get('protocol')}, khay {data.get('tray')}, "
        f"trạng thái {data.get('status')}, {len(samples)} mẫu. {details}"
    ).strip()


def _grounded_answer(history: List[Dict[str, Any]]) -> str:
    """Render a final answer exclusively from verified MCP observations."""
    observations = [event.get("observation", {}) for event in history]
    last_observation = observations[-1] if observations else {}
    if last_observation.get("status") == "NOT_FOUND":
        return _fallback_answer(last_observation)

    query_observation = next(
        (
            event.get("observation", {})
            for event in reversed(history)
            if event.get("tool_name") == "query_extraction_lot"
            and event.get("observation", {}).get("status") == "SUCCESS"
        ),
        None,
    )
    successful_mutations = [
        event.get("observation", {})
        for event in history
        if event.get("tool_name") == "mark_sample_fail"
        and event.get("observation", {}).get("status") == "SUCCESS"
    ]

    if not successful_mutations:
        return _fallback_answer(query_observation or last_observation)
    if not query_observation:
        return _fallback_answer(successful_mutations[-1])

    data = query_observation.get("data", {})
    samples_by_id = {
        sample.get("sample_id"): sample for sample in data.get("samples", [])
    }
    processed = []
    for mutation in successful_mutations:
        sample_id = mutation.get("sample_id")
        sample = samples_by_id.get(sample_id, {})
        yield_value = sample.get("yield_ng_ul")
        yield_text = f", yield {yield_value} ng/µL" if yield_value is not None else ""
        processed.append(f"{sample_id}{yield_text}")

    lot_status = successful_mutations[-1].get("lot_status", data.get("status"))
    return (
        f"Lô {data.get('lot_id')} — protocol {data.get('protocol')}, khay {data.get('tray')}, "
        f"tổng {len(data.get('samples', []))} mẫu. Đã chuyển sang FAILED: "
        f"{'; '.join(processed)}. Trạng thái lô vẫn là {lot_status}; "
        "các mẫu đạt chuẩn khác không bị ảnh hưởng."
    )


def _is_known_failed_sample(history: List[Dict[str, Any]], sample_id: str) -> bool:
    """Reject duplicate mutations using statuses already verified by MCP."""
    normalized_id = str(sample_id or "").strip().upper()
    for event in history:
        observation = event.get("observation", {})
        if event.get("tool_name") == "mark_sample_fail":
            if (
                observation.get("status") == "SUCCESS"
                and str(observation.get("sample_id", "")).upper() == normalized_id
            ):
                return True
        if event.get("tool_name") == "query_extraction_lot":
            for sample in observation.get("data", {}).get("samples", []):
                if (
                    str(sample.get("sample_id", "")).upper() == normalized_id
                    and sample.get("status") == "FAILED"
                ):
                    return True
    return False


def run_react_agent(user_query: str, provider, mcp_server: MCPLIMSServer, verbose: bool = True) -> list:
    """Execute a true multi-step Thought → Action → Observation loop."""
    if verbose:
        print(f"\n🤖 [REACT AGENT] Câu hỏi: {user_query}")

    trace_logs: List[Dict[str, Any]] = []
    tool_history: List[Dict[str, Any]] = []
    query_lower = user_query.lower()
    mutation_authorised = any(
        term in query_lower
        for term in ("đánh dấu", "mark fail", "mark_sample_fail", "tự động", "xử lý mẫu", "chuyển sang failed")
    )
    # Least privilege: a read-only request must never expose the mutation tool.
    tools_list = [
        tool
        for tool in mcp_server.list_tools()
        if tool.get("name") != "mark_sample_fail" or mutation_authorised
    ]
    current_prompt = user_query

    for step in range(1, MAX_ITERATIONS + 1):
        if verbose:
            print(f"\n--- 🔄 ReAct Loop {step}/{MAX_ITERATIONS} ---")
        llm_started = time.perf_counter()
        llm_response = provider.generate_with_tools(
            current_prompt,
            tools_list,
            system_prompt=REACT_AGENT_SYSTEM_PROMPT,
        )
        llm_latency_ms = round((time.perf_counter() - llm_started) * 1000, 2)
        thought = llm_response.get("thought", "Đánh giá bước tiếp theo theo SOP.")
        response_provider = llm_response.get("provider", provider.__class__.__name__)

        if verbose:
            print(f"🧠 [Thought] {thought}")

        if llm_response.get("type") == "text":
            final_content = str(llm_response.get("content", "")).strip()
            if tool_history:
                final_content = _grounded_answer(tool_history)
                thought = (
                    f"{thought} Final Answer được dựng từ Observation MCP đã xác thực "
                    "để ngăn sai lệch dữ liệu LIMS."
                )
            trace_logs.append(
                {
                    "step": step,
                    "query": user_query,
                    "action_type": "FINAL_ANSWER",
                    "thought": thought,
                    "output": final_content,
                    "provider": response_provider,
                    "latency_ms": llm_latency_ms,
                }
            )
            if verbose:
                print(f"🏁 [Final Answer] {final_content}")
            return trace_logs

        if llm_response.get("type") != "tool_call":
            final_content = "LLM trả về định dạng không hợp lệ; tác tử đã dừng an toàn mà không thay đổi LIMS."
            trace_logs.append(
                {
                    "step": step,
                    "query": user_query,
                    "action_type": "FINAL_ANSWER",
                    "thought": "Phản hồi provider không có type text hoặc tool_call.",
                    "output": final_content,
                    "provider": response_provider,
                    "latency_ms": llm_latency_ms,
                }
            )
            if verbose:
                print(f"🏁 [Final Answer] {final_content}")
            return trace_logs

        tool_name = llm_response.get("tool_name", "")
        arguments = llm_response.get("arguments") or {}
        if not mutation_authorised and tool_history:
            final_content = _fallback_answer(tool_history[-1]["observation"])
            trace_logs.append(
                {
                    "step": step,
                    "query": user_query,
                    "action_type": "FINAL_ANSWER",
                    "thought": "Yêu cầu chỉ đọc đã có Observation đầy đủ; bỏ qua đề xuất tool dư thừa và tổng hợp an toàn.",
                    "output": final_content,
                    "provider": response_provider,
                    "latency_ms": llm_latency_ms,
                }
            )
            if verbose:
                print("🛡️ [Read-only Gate] Bỏ qua tool proposal dư thừa sau Observation đầy đủ.")
                print(f"🏁 [Final Answer] {final_content}")
            return trace_logs
        if tool_name == "mark_sample_fail" and not mutation_authorised:
            final_content = "Yêu cầu hiện tại chỉ cho phép tra cứu; không có thao tác cập nhật nào được thực hiện trên LIMS."
            trace_logs.append(
                {
                    "step": step,
                    "query": user_query,
                    "action_type": "FINAL_ANSWER",
                    "thought": "Chặn tool ghi vì người dùng chưa cấp ý định cập nhật rõ ràng.",
                    "output": final_content,
                    "provider": response_provider,
                    "latency_ms": llm_latency_ms,
                }
            )
            if verbose:
                print(f"🛡️ [Safety Gate] {final_content}")
            return trace_logs
        if tool_name == "mark_sample_fail" and _is_known_failed_sample(
            tool_history, arguments.get("sample_id", "")
        ):
            final_content = _grounded_answer(tool_history)
            trace_logs.append(
                {
                    "step": step,
                    "query": user_query,
                    "action_type": "FINAL_ANSWER",
                    "thought": (
                        f"Safety gate chặn cập nhật lặp cho mẫu {arguments.get('sample_id')}: "
                        "Observation MCP xác nhận mẫu đã FAILED."
                    ),
                    "output": final_content,
                    "provider": response_provider,
                    "latency_ms": llm_latency_ms,
                }
            )
            if verbose:
                print(
                    f"🛡️ [Safety Gate] Bỏ qua mark_sample_fail cho "
                    f"{arguments.get('sample_id')} vì mẫu đã FAILED."
                )
                print(f"🏁 [Final Answer] {final_content}")
            return trace_logs
        if verbose:
            print(f"🛠️ [Action] {tool_name}({json.dumps(arguments, ensure_ascii=False)})")

        tool_started = time.perf_counter()
        mcp_result = mcp_server.call_tool(tool_name, arguments)
        tool_latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)
        observation = mcp_result.get("result", {})
        total_latency_ms = round(llm_latency_ms + tool_latency_ms, 2)

        event = {
            "step": step,
            "query": user_query,
            "action_type": "TOOL_EXECUTION",
            "thought": thought,
            "provider": response_provider,
            "tool_name": tool_name,
            "arguments": arguments,
            "observation": observation,
            "server": mcp_result.get("server"),
            "jsonrpc": mcp_result.get("jsonrpc"),
            "llm_latency_ms": llm_latency_ms,
            "tool_latency_ms": tool_latency_ms,
            "latency_ms": total_latency_ms,
        }
        trace_logs.append(event)
        tool_history.append(event)

        if verbose:
            print(f"👁️ [Observation · {tool_latency_ms} ms] {json.dumps(observation, ensure_ascii=False)}")

        # Critical ReAct behaviour: never break immediately after an Observation.
        current_prompt = _next_prompt(user_query, tool_history)

    final_content = _fallback_answer(tool_history[-1]["observation"] if tool_history else {})
    trace_logs.append(
        {
            "step": MAX_ITERATIONS + 1,
            "query": user_query,
            "action_type": "FINAL_ANSWER",
            "thought": "Đã đạt giới hạn vòng lặp; tổng hợp an toàn từ Observation cuối cùng.",
            "output": final_content,
            "latency_ms": 0.0,
        }
    )
    if verbose:
        print(f"🏁 [Final Answer] {final_content}")
    return trace_logs


def run_test_suite(provider, mcp_server: MCPLIMSServer, reset_state: bool = True, verbose: bool = True) -> Dict[str, Any]:
    """Run and evaluate all configured acceptance cases."""
    if reset_state:
        reset_mock_database()
    results = []
    all_traces = []

    for test_case in load_test_cases():
        if test_case.get("reset_state_before"):
            reset_mock_database()
        if verbose:
            print(f"\n{'=' * 66}\n🧪 [{test_case['id']}] {test_case['type']} · {test_case['complexity']}")
            print(f"📌 {test_case['expected_behavior']}")
        traces = run_react_agent(test_case["question"], provider, mcp_server, verbose=verbose)
        actual_tools = [event["tool_name"] for event in traces if event["action_type"] == "TOOL_EXECUTION"]
        expected_tools = test_case.get("expected_tools", [])
        has_final = bool(traces and traces[-1].get("action_type") == "FINAL_ANSWER" and traces[-1].get("output"))
        passed = actual_tools == expected_tools and has_final
        result = {
            "id": test_case["id"],
            "passed": passed,
            "expected_tools": expected_tools,
            "actual_tools": actual_tools,
            "trace_count": len(traces),
        }
        results.append(result)
        all_traces.extend(traces)
        if verbose:
            print(f"{'✅ PASS' if passed else '❌ FAIL'} · tools={actual_tools}")

    save_waterfall_trace(all_traces)
    passed_count = sum(result["passed"] for result in results)
    return {
        "passed": passed_count,
        "total": len(results),
        "results": results,
        "traces": all_traces,
    }


def main() -> None:
    print("=" * 66)
    print("🧬 LAB 3 · LIMS EXTRACTION REACT AGENT WITH MCP")
    print("=" * 66)
    provider = get_llm_provider()
    mcp_server = MCPLIMSServer()
    print(f"🔌 LLM Provider: {provider.__class__.__name__}")
    print(f"🌐 MCP Server: {mcp_server.server_name}")

    if "--interactive" in sys.argv:
        print("\n🎮 Nhập yêu cầu LIMS; gõ 'exit' để kết thúc.")
        while True:
            try:
                user_input = input("👤 Lab Tech › ").strip()
                if not user_input or user_input.lower() in {"exit", "quit"}:
                    break
                save_waterfall_trace(run_react_agent(user_input, provider, mcp_server))
            except (KeyboardInterrupt, EOFError):
                break
        print("👋 Đã kết thúc phiên LIMS.")
    elif "--all" in sys.argv:
        report = run_test_suite(provider, mcp_server)
        print(f"\n📊 [KẾT QUẢ TEST SUITE] {report['passed']}/{report['total']} Test Cases PASS")
        if report["passed"] != report["total"]:
            raise SystemExit(1)
    else:
        print("\n1. Chạy 5 test:       python src/app.py --all")
        print("2. Chat tương tác:    python src/app.py --interactive")
        print("3. Web dashboard:    python src/web_dashboard.py")


if __name__ == "__main__":
    main()
