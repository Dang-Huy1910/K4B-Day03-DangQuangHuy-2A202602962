# Lab 3 · LIMS Extraction ReAct Agent with MCP

Hệ thống tác tử ReAct quản trị tách chiết DNA/RNA trong phòng lab, xây dựng cho Bài Lab 3 của học viên **Đặng Quang Huy · 2A202602962 · K4B**.

Tác tử có thể tra cứu lô tách chiết qua MCP, đánh giá DNA yield theo SOP **≥ 10.0 ng/µL**, đánh dấu `FAILED` cho riêng mẫu không đạt và giữ nguyên các mẫu hợp lệ còn lại trong khay QIAvac.

## Quickstart

Yêu cầu Python 3.10–3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Điền `GEMINI_API_KEY` trong `.env`. Cấu hình mặc định:

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
```

## Chạy nghiệm thu

```bash
# MCP JSON-RPC smoke test
.venv/bin/python src/mcp_server.py

# Chạy và chấm toàn bộ 5 test cases
.venv/bin/python src/app.py --all

# Console tương tác
.venv/bin/python src/app.py --interactive
```

Kết quả mong đợi:

```text
✅ Tool schemas: hợp lệ
✅ JSON-RPC dispatch query_extraction_lot
📊 [KẾT QUẢ TEST SUITE] 5/5 Test Cases PASS
```

Waterfall trace được ghi tự động tại [`docs/trace_waterfall.json`](docs/trace_waterfall.json). Báo cáo nghiệm thu nằm tại [`docs/trace_eval.md`](docs/trace_eval.md).

## Web Dashboard

```bash
.venv/bin/python src/web_dashboard.py
```

Mở [http://localhost:8000](http://localhost:8000). Dashboard **Helix Control** gồm:

- khay QIAvac 6 × 8 với trạng thái `PASSED`, `LOW_YIELD`, `FAILED` và chi tiết từng giếng;
- ReAct console với quick prompts TC01–TC05;
- waterfall timeline tách rõ Thought, Action, Observation, Final Answer và latency;
- one-click runner cho toàn bộ acceptance suite;
- đồng bộ trạng thái thật với mock LIMS backend trong cùng tiến trình.

## Kiến trúc

```text
Natural-language request
        │
        ▼
Gemini / Offline Mock Provider
        │  Native tool call
        ▼
True Multi-Step ReAct Loop
        │  JSON-RPC 2.0
        ▼
LIMS MCP Server
        │
        ├── query_extraction_lot
        └── mark_sample_fail
                 │
                 ▼
          In-memory Mock LIMS
```

Các thành phần chính:

| File | Vai trò |
| :--- | :--- |
| `src/tools.py` | JSON Schemas, hai lô mock, query/update execution layer |
| `src/mcp_server.py` | MCP tool registry và JSON-RPC envelope |
| `src/prompts.py` | SOP và nguyên tắc ReAct/anti-hallucination |
| `src/providers.py` | Gemini, OpenAI và mock adapter; Gemini schema compatibility + rate-limit retry |
| `src/app.py` | ReAct loop, test evaluator và waterfall persistence |
| `src/web_dashboard.py` | Dashboard + API dùng `ThreadingHTTPServer` thuần Python |

## Acceptance scenarios

| ID | Mục tiêu | Tool sequence |
| :---: | :--- | :--- |
| TC01 | Trả lời ngưỡng SOP | Không gọi tool |
| TC02 | Tra cứu `LOT-EXT-2026-01` | `query_extraction_lot` |
| TC03 | Fail riêng `SMP-102` | `mark_sample_fail` |
| TC04 | Phát hiện và xử lý low yield | `query_extraction_lot` → `mark_sample_fail` |
| TC05 | Xử lý lô không tồn tại | `query_extraction_lot` → `NOT_FOUND` |

> Đây là mô hình đào tạo dùng dữ liệu giả lập, không phải hệ thống đưa ra quyết định lâm sàng trong môi trường sản xuất.
