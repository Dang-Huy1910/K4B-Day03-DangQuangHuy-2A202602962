# BÁO CÁO NGHIỆM THU BÀI LAB 3 — LIMS EXTRACTION REACT AGENT

> **Họ và Tên:** Đặng Quang Huy
>
> **Mã Học Viên:** 2A202602962
>
> **Lớp:** K4B
>
> **Chủ đề:** Trợ lý Tác tử Quản trị Tách chiết Mẫu Phòng Lab (LIMS Extraction ReAct Agent)
>
> **LLM nghiệm thu:** Google Gemini — `gemini-3.5-flash-lite`
>
> **Ngày nghiệm thu:** 13/09/2026
>
> **GitHub Repository:** [Dang-Huy1910/K4B-Day03-Lab-Chatbot-vs-ReAct-Agent-MCP](https://github.com/Dang-Huy1910/K4B-Day03-Lab-Chatbot-vs-ReAct-Agent-MCP)

---

## 1. Agentic Fit Scoring Matrix

| Tiêu chí | Điểm | Giải trình |
| :--- | :---: | :--- |
| **1. Multi-step Reasoning** | **5/5** | Tác tử phải thực hiện chuỗi suy luận: tra cứu lô → đọc nồng độ yield từng giếng → đối chiếu ngưỡng SOP 10 ng/µL → quyết định đánh dấu fail đúng mẫu. |
| **2. Tool Interaction** | **5/5** | Bắt buộc truy cập dữ liệu LIMS qua MCP để lấy nồng độ thực tế. LLM đơn thuần có thể ảo giác DNA yield và tạo rủi ro lâm sàng. |
| **3. Dynamic Decision** | **5/5** | Nhánh hành động được quyết định hoàn toàn tại runtime từ Observation: `NOT_FOUND` thì dừng an toàn; lô hợp lệ nhưng không có mẫu dưới ngưỡng thì chỉ tổng hợp; phát hiện yield < 10.0 ng/µL mới gọi `mark_sample_fail`. Safety gate còn ngăn mutation khi người dùng chỉ yêu cầu tra cứu. |
| **4. Long Horizon Goal** | **5/5** | Tác tử duy trì mục tiêu kiểm soát chất lượng và ngữ cảnh lô xuyên suốt ba vòng ReAct, theo dõi trạng thái trước/sau mutation, bảo toàn trạng thái `IN_PROGRESS` và tính toàn vẹn của ba mẫu đạt chuẩn còn lại. |
| **TỔNG ĐIỂM AGENTIC FIT** | **20/20** | **Bài toán đáp ứng đầy đủ bốn đặc trưng của một Agentic System.** |

---

## 2. Kiến trúc và quy tắc an toàn

- MCP Server: `lims-extraction-mcp-server`, envelope JSON-RPC 2.0.
- Tool tra cứu: `query_extraction_lot(lot_id)`.
- Tool cập nhật: `mark_sample_fail(lot_id, sample_id, reason, operator_name)`.
- SOP: DNA yield đạt chuẩn khi **≥ 10.0 ng/µL**; thấp hơn ngưỡng là `LOW_YIELD`.
- Phạm vi cập nhật: chỉ mẫu được chọn chuyển sang `FAILED`; trạng thái lô và các mẫu đạt chuẩn khác được giữ nguyên.
- Anti-hallucination: dữ liệu lô, yield và trạng thái chỉ được kết luận từ Observation của MCP.

---

## 3. Kết quả Waterfall Trace trên Gemini API thật

Lệnh nghiệm thu:

```bash
.venv/bin/python src/app.py --all
```

Kết quả: **5/5 Test Cases PASS**, **5 lượt gọi Tool chính xác**, **10 trace events**. Toàn bộ event trong `docs/trace_waterfall.json` ghi nhận `provider: "gemini-3.5-flash-lite"`; không có event fallback trong artifact cuối.

Trích xuất các trường nghiệm thu từ TC04, đồng bộ với artifact Gemini hiện tại:

```json
[
  {
    "step": 1,
    "action_type": "TOOL_EXECUTION",
    "thought": "Gemini quyết định gọi công cụ 'query_extraction_lot' với tham số: {\"lot_id\": \"LOT-EXT-2026-01\"}",
    "provider": "gemini-3.5-flash-lite",
    "tool_name": "query_extraction_lot",
    "arguments": {"lot_id": "LOT-EXT-2026-01"},
    "observation": {
      "status": "SUCCESS",
      "lot_id": "LOT-EXT-2026-01",
      "data": {
        "tray": "QIAvac-Tray-A",
        "status": "IN_PROGRESS",
        "sop_min_yield_ng_ul": 10.0,
        "samples": [
          {"sample_id": "SMP-102", "yield_ng_ul": 4.8, "status": "LOW_YIELD"}
        ]
      }
    },
    "server": "lims-extraction-mcp-server",
    "jsonrpc": "2.0",
    "llm_latency_ms": 1228.99,
    "tool_latency_ms": 2.25,
    "latency_ms": 1231.24
  },
  {
    "step": 2,
    "action_type": "TOOL_EXECUTION",
    "thought": "Gemini quyết định gọi công cụ 'mark_sample_fail' với tham số: {\"sample_id\": \"SMP-102\", \"operator_name\": \"LabTech-2A202602962\", \"reason\": \"DNA yield (4.8 ng/uL) thấp hơn ngưỡng chuẩn tối thiểu 10.0 ng/uL theo tiêu chuẩn SOP (LOW_YIELD).\", \"lot_id\": \"LOT-EXT-2026-01\"}",
    "provider": "gemini-3.5-flash-lite",
    "tool_name": "mark_sample_fail",
    "arguments": {
      "lot_id": "LOT-EXT-2026-01",
      "sample_id": "SMP-102",
      "reason": "DNA yield (4.8 ng/uL) thấp hơn ngưỡng chuẩn tối thiểu 10.0 ng/uL theo tiêu chuẩn SOP (LOW_YIELD).",
      "operator_name": "LabTech-2A202602962"
    },
    "observation": {
      "status": "SUCCESS",
      "previous_status": "LOW_YIELD",
      "sample_status": "FAILED",
      "lot_status": "IN_PROGRESS"
    },
    "server": "lims-extraction-mcp-server",
    "jsonrpc": "2.0",
    "llm_latency_ms": 1867.13,
    "tool_latency_ms": 0.15,
    "latency_ms": 1867.28
  },
  {
    "step": 3,
    "action_type": "FINAL_ANSWER",
    "thought": "Gemini phản hồi trực tiếp bằng văn bản (không cần gọi công cụ).",
    "provider": "gemini-3.5-flash-lite",
    "latency_ms": 1868.48
  }
]
```

### Bảng kết quả Test Cases

| Test | Kịch bản | Tool sequence | Kết quả |
| :---: | :--- | :--- | :---: |
| TC01 | Hỏi ngưỡng SOP | Không gọi tool | ✅ PASS |
| TC02 | Tra cứu chi tiết lô | `query_extraction_lot` | ✅ PASS |
| TC03 | Đánh dấu lỗi một mẫu | `mark_sample_fail` | ✅ PASS |
| TC04 | Kiểm tra và tự động xử lý low yield | `query_extraction_lot` → `mark_sample_fail` | ✅ PASS |
| TC05 | Lô không tồn tại | `query_extraction_lot` → `NOT_FOUND` | ✅ PASS |

---

## 4. Checklist nghiệm thu kỹ thuật

- [x] Điền đầy đủ thông tin học viên, lớp và chủ đề.
- [x] Cấu hình Gemini API thật và xác nhận `gemini-3.5-flash-lite` xử lý toàn bộ trace cuối.
- [x] Hai Tool Schemas có properties, required fields và mô tả nghiệp vụ đầy đủ.
- [x] MCP Server dispatch và đóng gói JSON-RPC 2.0 thành công.
- [x] ReAct loop giữ Observation qua nhiều vòng, không dừng ngay sau tool call.
- [x] TC04 gọi đúng hai tool theo thứ tự và bảo toàn trạng thái lô.
- [x] TC05 xử lý `NOT_FOUND`, không bịa dữ liệu.
- [x] Test suite đạt **5/5** và lưu `docs/trace_waterfall.json`.
- [x] Đã kiểm tra chế độ hội thoại `src/app.py --interactive` khởi động và thoát an toàn.
- [x] Dashboard hiển thị khay 48 giếng, console, quick prompts, waterfall timeline và one-click test runner.
- [ ] Commit và push lên GitHub cá nhân (bước nộp bài do chủ repository thực hiện).

---

## 5. Kết luận

Hệ thống đáp ứng đầy đủ mục tiêu Lab 3: phân biệt phản hồi trực tiếp và tác tử có công cụ, thực thi True Multi-Step ReAct qua MCP, xử lý mẫu `LOW_YIELD` ở cấp mẫu, lưu bằng chứng quan sát, và cung cấp dashboard vận hành trực quan. Artifact nghiệm thu cuối được sinh từ Google Gemini API thật, vượt đủ 5 kịch bản kiểm thử và đạt **Agentic Fit 20/20**.

## 6. Thông tin nộp bài

- **Repository:** <https://github.com/Dang-Huy1910/K4B-Day03-Lab-Chatbot-vs-ReAct-Agent-MCP>
- **Nhánh nộp bài:** `main`
- **Trạng thái source code:** Đã hoàn thiện và nghiệm thu 5/5 test cases.
- **Thao tác cuối trên VLearn:** Dán URL repository ở trên vào ô nộp bài.
