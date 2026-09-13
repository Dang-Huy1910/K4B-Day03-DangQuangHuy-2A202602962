"""
🔌 MULTI-PROVIDER LLM ADAPTER (Google Gemini, OpenAI & Offline Mock)
Hỗ trợ Native Tool Calling và chuyển đổi linh hoạt qua biến môi trường LLM_PROVIDER.
"""

import os
import sys
import json
import re
import time
from typing import Dict, Any, List
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

class BaseLLMProvider:
    """Interface cơ sở cho các LLM Provider hỗ trợ Native Tool Calling"""
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError

    def generate_with_tools(self, prompt: str, tools_schema: List[Dict[str, Any]], system_prompt: str = "") -> Dict[str, Any]:
        raise NotImplementedError


class MockOfflineProvider(BaseLLMProvider):
    """Deterministic LIMS provider used for offline development and CI."""
    def __init__(self):
        self.model_name = "Offline-Mock-Model-2026"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if "yield" in prompt.lower() or "nồng độ" in prompt.lower():
            return (
                "Theo SOP QIAamp, DNA yield tối thiểu đạt chuẩn là 10.0 ng/µL. "
                "Mẫu dưới ngưỡng này được phân loại LOW_YIELD."
            )
        return "Tôi có thể giải đáp SOP chung nhưng không truy cập dữ liệu lô thời gian thực ở chế độ Chatbot."

    @staticmethod
    def _identifier(pattern: str, prompt: str, fallback: str) -> str:
        match = re.search(pattern, prompt, re.IGNORECASE)
        return match.group(0).upper() if match else fallback

    @staticmethod
    def _observations(prompt: str) -> list[tuple[str, Dict[str, Any]]]:
        observations = []
        for line in prompt.splitlines():
            if not line.startswith("[Observation từ Tool ") or "]: " not in line:
                continue
            heading, payload = line.split("]: ", 1)
            tool_name = heading.removeprefix("[Observation từ Tool ")
            try:
                observations.append((tool_name, json.loads(payload)))
            except json.JSONDecodeError:
                continue
        return observations

    def generate_with_tools(self, prompt: str, tools_schema: List[Dict[str, Any]], system_prompt: str = "") -> Dict[str, Any]:
        prompt_lower = prompt.lower()
        lot_id = self._identifier(r"LOT-EXT-[A-Z0-9-]+", prompt, "LOT-EXT-2026-01")
        sample_id = self._identifier(r"SMP-[A-Z0-9-]+", prompt, "SMP-102")
        observations = self._observations(prompt)
        is_conditional_qc = any(term in prompt_lower for term in ("tự động", "nếu phát hiện", "dưới 10", "thấp hơn 10"))

        if observations:
            last_tool, observation = observations[-1]
            if last_tool == "mark_sample_fail":
                if observation.get("status") == "SUCCESS":
                    return {
                        "type": "text",
                        "content": (
                            f"Đã hoàn tất kiểm soát chất lượng lô {observation.get('lot_id')}. "
                            f"Mẫu {observation.get('sample_id')} đã chuyển sang FAILED với lý do: "
                            f"{observation.get('failure_reason')}. Trạng thái lô vẫn là "
                            f"{observation.get('lot_status')}; các mẫu đạt chuẩn khác không bị ảnh hưởng."
                        ),
                        "thought": "Thao tác cập nhật mẫu đã thành công; có thể tổng hợp kết quả mà không cần gọi thêm tool.",
                    }
                return {
                    "type": "text",
                    "content": observation.get("message", "Không thể đánh dấu lỗi cho mẫu theo yêu cầu."),
                    "thought": "Tool cập nhật không thành công; cần báo đúng trạng thái thay vì suy đoán.",
                }

            if last_tool == "query_extraction_lot":
                if observation.get("status") == "NOT_FOUND":
                    return {
                        "type": "text",
                        "content": observation.get("message", f"Không tìm thấy lô {lot_id} trong LIMS."),
                        "thought": "LIMS trả về NOT_FOUND nên phải dừng và phản hồi lịch sự, không bịa dữ liệu.",
                    }
                data = observation.get("data", {})
                samples = data.get("samples", [])
                low_samples = [s for s in samples if float(s.get("yield_ng_ul", 0)) < 10.0]
                if is_conditional_qc and low_samples:
                    target = low_samples[0]
                    target_yield = target.get("yield_ng_ul")
                    return {
                        "type": "tool_call",
                        "tool_name": "mark_sample_fail",
                        "arguments": {
                            "lot_id": data.get("lot_id", lot_id),
                            "sample_id": target.get("sample_id"),
                            "reason": f"DNA yield {target_yield} ng/µL dưới ngưỡng SOP 10.0 ng/µL",
                            "operator_name": "LabTech-2A202602962",
                        },
                        "thought": f"Phát hiện {target.get('sample_id')} có yield {target_yield} ng/µL dưới ngưỡng; cần đánh dấu riêng mẫu này là FAILED.",
                    }
                summary = data.get("summary", {})
                sample_lines = "; ".join(
                    f"{s.get('sample_id')}: {s.get('yield_ng_ul')} ng/µL ({s.get('status')})"
                    for s in samples
                )
                return {
                    "type": "text",
                    "content": (
                        f"Lô {data.get('lot_id')} đang ở trạng thái {data.get('status')}, "
                        f"protocol {data.get('protocol')}, khay {data.get('tray')}. "
                        f"Có {summary.get('total', len(samples))} mẫu — {sample_lines}."
                    ),
                    "thought": "Đã có dữ liệu lô đầy đủ; tổng hợp số mẫu, yield và trạng thái khay cho kỹ thuật viên.",
                }

        if is_conditional_qc:
            return {
                "type": "tool_call",
                "tool_name": "query_extraction_lot",
                "arguments": {"lot_id": lot_id},
                "thought": "Cần tra cứu lô trước để quyết định mẫu nào thực sự dưới ngưỡng SOP 10.0 ng/µL.",
            }

        if "đánh dấu" in prompt_lower and ("fail" in prompt_lower or "lỗi" in prompt_lower):
            reason = "Mẫu bị đông vón hạt từ tính" if "đông vón" in prompt_lower else "Lỗi mẫu theo xác nhận của kỹ thuật viên"
            return {
                "type": "tool_call",
                "tool_name": "mark_sample_fail",
                "arguments": {"lot_id": lot_id, "sample_id": sample_id, "reason": reason, "operator_name": "LabTech-2A202602962"},
                "thought": f"Kỹ thuật viên yêu cầu cập nhật trực tiếp mẫu {sample_id}; gọi mark_sample_fail nhưng không thay đổi trạng thái cả lô.",
            }

        if "tra cứu" in prompt_lower or "kiểm tra" in prompt_lower or lot_id in prompt:
            return {
                "type": "tool_call",
                "tool_name": "query_extraction_lot",
                "arguments": {"lot_id": lot_id},
                "thought": f"Yêu cầu cần dữ liệu thực tế của {lot_id}; gọi query_extraction_lot để tránh suy đoán.",
            }

        return {
            "type": "text",
            "content": "Theo SOP QIAamp, nồng độ DNA yield tối thiểu đạt chuẩn là 10.0 ng/µL; thấp hơn ngưỡng này được phân loại LOW_YIELD.",
            "thought": "Đây là câu hỏi kiến thức SOP chung nên có thể trả lời trực tiếp, không cần gọi tool.",
        }


class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider (Native Tool Calling với Google GenAI SDK)"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gemini-3.5-flash-lite"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return "[Gemini Error]: Chưa cấu hình GEMINI_API_KEY trong file .env! Đang sử dụng chế độ Mock."
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(model=self.model_name, contents=contents)
            return response.text
        except Exception as e:
            return f"[Gemini Exception]: {str(e)}"

    def generate_with_tools(self, prompt: str, tools_schema: List[Dict[str, Any]], system_prompt: str = "") -> Dict[str, Any]:
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            print("ℹ️ [Gemini Provider]: Chưa tìm thấy GEMINI_API_KEY hợp lệ. Tự động chuyển sang Mock Offline.")
            return MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt)
        
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            
            def gemini_compatible_schema(value):
                """Remove valid JSON-Schema keywords not accepted by Gemini's subset."""
                if isinstance(value, dict):
                    return {
                        key: gemini_compatible_schema(item)
                        for key, item in value.items()
                        if key not in {"additionalProperties", "$schema"}
                    }
                if isinstance(value, list):
                    return [gemini_compatible_schema(item) for item in value]
                return value

            # Chuẩn hóa function declarations cho Gemini SDK
            function_declarations = []
            for tool in tools_schema:
                # Bỏ qua các tool schema chưa được định nghĩa hoàn chỉnh
                if not tool.get("name") or not tool.get("parameters"):
                    continue
                function_declarations.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": gemini_compatible_schema(tool.get("parameters", {}))
                })

            config = types.GenerateContentConfig(
                system_instruction=system_prompt if system_prompt else None,
                tools=[{"function_declarations": function_declarations}] if function_declarations else None,
                temperature=0.2
            )

            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=config,
                    )
                    break
                except Exception as api_error:
                    error_text = str(api_error)
                    if (
                        attempt == 0
                        and "429 RESOURCE_EXHAUSTED" in error_text
                        and "GenerateRequestsPerDay" not in error_text
                    ):
                        retry_match = re.search(r"retryDelay['\": ]+([0-9]+)s", error_text)
                        retry_seconds = min(int(retry_match.group(1)) + 2 if retry_match else 50, 60)
                        print(f"⏳ [Gemini Rate Limit]: Chờ {retry_seconds}s theo RetryInfo rồi gọi lại API thật...")
                        time.sleep(retry_seconds)
                        continue
                    raise

            # Kiểm tra xem Gemini có trả về Tool Call không
            if response.function_calls:
                call = response.function_calls[0]
                args = dict(call.args) if hasattr(call, 'args') and call.args else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.name,
                    "arguments": args,
                    "thought": f"Gemini quyết định gọi công cụ '{call.name}' với tham số: {json.dumps(args, ensure_ascii=False)}",
                    "provider": self.model_name,
                }
            else:
                return {
                    "type": "text",
                    "content": response.text or "",
                    "thought": "Gemini phản hồi trực tiếp bằng văn bản (không cần gọi công cụ).",
                    "provider": self.model_name,
                }

        except Exception as e:
            print(f"⚠️ [Gemini API Warning]: Không thể kết nối live API ({str(e)}). Tự động fallback về Mock.")
            fallback = MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt)
            fallback["provider"] = "MockOfflineProvider (fallback)"
            return fallback


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Provider (Native Tool Calling với OpenAI SDK)"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            return "[OpenAI Error]: Chưa cấu hình OPENAI_API_KEY trong file .env! Đang sử dụng chế độ Mock."
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(model=self.model_name, messages=messages)
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[OpenAI Exception]: {str(e)}"

    def generate_with_tools(self, prompt: str, tools_schema: List[Dict[str, Any]], system_prompt: str = "") -> Dict[str, Any]:
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            print("ℹ️ [OpenAI Provider]: Chưa tìm thấy OPENAI_API_KEY hợp lệ. Tự động chuyển sang Mock Offline.")
            return MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            tools = []
            for tool in tools_schema:
                if not tool.get("name"):
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {})
                    }
                })

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None
            )

            msg = response.choices[0].message
            if msg.tool_calls:
                call = msg.tool_calls[0]
                args = json.loads(call.function.arguments) if call.function.arguments else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.function.name,
                    "arguments": args,
                    "thought": f"OpenAI quyết định gọi công cụ '{call.function.name}' với tham số: {json.dumps(args, ensure_ascii=False)}"
                }
            else:
                return {
                    "type": "text",
                    "content": msg.content or "",
                    "thought": "OpenAI phản hồi trực tiếp bằng văn bản (không cần gọi công cụ)."
                }
        except Exception as e:
            print(f"⚠️ [OpenAI API Warning]: Không thể kết nối live API ({str(e)}). Tự động fallback về Mock.")
            return MockOfflineProvider().generate_with_tools(prompt, tools_schema, system_prompt)


def get_llm_provider() -> BaseLLMProvider:
    """Factory function khởi tạo Provider theo LLM_PROVIDER env variable"""
    provider_type = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    if provider_type == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if key and key != "your_gemini_api_key_here":
            return GeminiProvider()
        else:
            return MockOfflineProvider()
    elif provider_type == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if key and key != "your_openai_api_key_here":
            return OpenAIProvider()
        else:
            return MockOfflineProvider()
    elif provider_type == "mock":
        return MockOfflineProvider()
    else:
        return MockOfflineProvider()
