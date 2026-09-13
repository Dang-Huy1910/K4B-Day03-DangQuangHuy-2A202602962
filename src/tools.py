"""LIMS tool schemas and deterministic execution backend.

The mock store is intentionally in-process so the CLI and dashboard can show
that a ReAct action changes one sample without invalidating its extraction lot.
"""

from __future__ import annotations

import copy
import json
from threading import RLock
from typing import Any, Dict


SOP_MIN_YIELD_NG_UL = 10.0
DEFAULT_OPERATOR = "LabTech-2A202602962"

TOOLS_SCHEMA = [
    {
        "name": "query_extraction_lot",
        "description": (
            "Tra cứu thông tin trạng thái, giao thức, khay QIAvac và chi tiết "
            "các mẫu (kèm nồng độ DNA yield) trong lô tách chiết LIMS."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "Mã lô tách chiết, ví dụ LOT-EXT-2026-01.",
                }
            },
            "required": ["lot_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mark_sample_fail",
        "description": (
            "Đánh dấu lỗi/thất bại cho một mẫu xét nghiệm trong lô tách chiết "
            "mà không hủy cả lô mẻ chạy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lot_id": {
                    "type": "string",
                    "description": "Mã lô chứa mẫu cần đánh dấu lỗi.",
                },
                "sample_id": {
                    "type": "string",
                    "description": "Mã mẫu xét nghiệm cần đánh dấu FAILED.",
                },
                "reason": {
                    "type": "string",
                    "description": "Lý do nghiệp vụ hoặc sự cố kỹ thuật gây lỗi mẫu.",
                },
                "operator_name": {
                    "type": "string",
                    "description": "Định danh kỹ thuật viên thực hiện thao tác.",
                    "default": DEFAULT_OPERATOR,
                },
            },
            "required": ["lot_id", "sample_id", "reason"],
            "additionalProperties": False,
        },
    },
]


def _completed_samples() -> list[Dict[str, Any]]:
    """Build a realistic 6 x 8 MagMAX tray containing 48 qualified samples."""
    sample_types = ("Plasma", "Serum", "Swab", "Saliva")
    samples = []
    for index in range(48):
        row, column = divmod(index, 8)
        samples.append(
            {
                "sample_id": f"RNA-{index + 1:03d}",
                "well": f"{chr(65 + row)}{column + 1}",
                "yield_ng_ul": round(18.5 + (index % 9) * 2.35, 2),
                "status": "PASSED",
                "sample_type": sample_types[index % len(sample_types)],
            }
        )
    return samples


def _in_progress_samples() -> list[Dict[str, Any]]:
    """Build a mixed-state 24-sample tray for the operational dashboard."""
    samples = [
        {"sample_id": "SMP-101", "well": "A1", "yield_ng_ul": 45.2, "status": "PASSED", "sample_type": "Blood"},
        {"sample_id": "SMP-102", "well": "A2", "yield_ng_ul": 4.8, "status": "LOW_YIELD", "sample_type": "Saliva"},
        {"sample_id": "SMP-103", "well": "A3", "yield_ng_ul": 52.0, "status": "PASSED", "sample_type": "Tissue"},
        {"sample_id": "SMP-104", "well": "A4", "yield_ng_ul": 38.6, "status": "PASSED", "sample_type": "Swab"},
        {"sample_id": "SMP-105", "well": "A5", "yield_ng_ul": 26.4, "status": "PASSED", "sample_type": "Plasma"},
        {"sample_id": "SMP-106", "well": "A6", "yield_ng_ul": 31.8, "status": "PASSED", "sample_type": "Serum"},
        {"sample_id": "SMP-107", "well": "A7", "yield_ng_ul": 14.6, "status": "PASSED", "sample_type": "Swab"},
        {"sample_id": "SMP-108", "well": "A8", "yield_ng_ul": 7.3, "status": "LOW_YIELD", "sample_type": "Blood"},
        {"sample_id": "SMP-109", "well": "B1", "yield_ng_ul": 22.7, "status": "PASSED", "sample_type": "Tissue"},
        {"sample_id": "SMP-110", "well": "B2", "yield_ng_ul": 41.5, "status": "PASSED", "sample_type": "Plasma"},
        {"sample_id": "SMP-111", "well": "B3", "yield_ng_ul": 16.2, "status": "FAILED", "sample_type": "Saliva", "failure_reason": "Phát hiện nhiễm chéo tại giếng B3", "failed_by": DEFAULT_OPERATOR},
        {"sample_id": "SMP-112", "well": "B4", "yield_ng_ul": 29.9, "status": "PASSED", "sample_type": "Swab"},
        {"sample_id": "SMP-113", "well": "B5", "yield_ng_ul": 35.6, "status": "PASSED", "sample_type": "Blood"},
        {"sample_id": "SMP-114", "well": "B6", "yield_ng_ul": 12.8, "status": "PASSED", "sample_type": "Saliva"},
        {"sample_id": "SMP-115", "well": "B7", "yield_ng_ul": 8.9, "status": "LOW_YIELD", "sample_type": "Tissue"},
        {"sample_id": "SMP-116", "well": "B8", "yield_ng_ul": 47.3, "status": "PASSED", "sample_type": "Blood"},
        {"sample_id": "SMP-117", "well": "C1", "yield_ng_ul": 19.5, "status": "PASSED", "sample_type": "Serum"},
        {"sample_id": "SMP-118", "well": "C2", "yield_ng_ul": 33.1, "status": "PASSED", "sample_type": "Swab"},
        {"sample_id": "SMP-119", "well": "C3", "yield_ng_ul": 2.1, "status": "FAILED", "sample_type": "Plasma", "failure_reason": "Mất thể tích mẫu trong bước rửa cột", "failed_by": DEFAULT_OPERATOR},
        {"sample_id": "SMP-120", "well": "C4", "yield_ng_ul": 27.6, "status": "PASSED", "sample_type": "Tissue"},
        {"sample_id": "SMP-121", "well": "C5", "yield_ng_ul": 44.0, "status": "PASSED", "sample_type": "Blood"},
        {"sample_id": "SMP-122", "well": "C6", "yield_ng_ul": 6.4, "status": "LOW_YIELD", "sample_type": "Saliva"},
        {"sample_id": "SMP-123", "well": "C7", "yield_ng_ul": 18.8, "status": "PASSED", "sample_type": "Swab"},
        {"sample_id": "SMP-124", "well": "C8", "yield_ng_ul": 55.7, "status": "PASSED", "sample_type": "Tissue"},
    ]
    return samples


_INITIAL_DATABASE: Dict[str, Dict[str, Any]] = {
    "LOT-EXT-2026-01": {
        "lot_id": "LOT-EXT-2026-01",
        "protocol": "QIAamp DNA Mini Kit",
        "tray": "QIAvac-Tray-A",
        "status": "IN_PROGRESS",
        "capacity": 48,
        "started_at": "2026-09-13T08:30:00+07:00",
        "samples": _in_progress_samples(),
    },
    "LOT-EXT-2026-02": {
        "lot_id": "LOT-EXT-2026-02",
        "protocol": "MagMAX Viral RNA",
        "tray": "QIAvac-Tray-B",
        "status": "COMPLETED",
        "capacity": 48,
        "completed_at": "2026-09-12T17:15:00+07:00",
        "samples": _completed_samples(),
    },
}

MOCK_DATABASE: Dict[str, Dict[str, Any]] = copy.deepcopy(_INITIAL_DATABASE)
_DATABASE_LOCK = RLock()


def reset_mock_database() -> None:
    """Restore the fixture for repeatable CLI and dashboard test runs."""
    with _DATABASE_LOCK:
        MOCK_DATABASE.clear()
        MOCK_DATABASE.update(copy.deepcopy(_INITIAL_DATABASE))


def _normalise(value: str) -> str:
    return str(value or "").strip().upper()


def _lot_summary(lot: Dict[str, Any]) -> Dict[str, int]:
    samples = lot["samples"]
    return {
        "total": len(samples),
        "passed": sum(sample["status"] == "PASSED" for sample in samples),
        "low_yield": sum(sample["status"] == "LOW_YIELD" for sample in samples),
        "failed": sum(sample["status"] == "FAILED" for sample in samples),
    }


def execute_query_extraction_lot(lot_id: str) -> str:
    """Return a snapshot of an extraction lot and its current QC summary."""
    normalised_id = _normalise(lot_id)
    with _DATABASE_LOCK:
        lot = MOCK_DATABASE.get(normalised_id)
        if lot is None:
            result = {
                "status": "NOT_FOUND",
                "lot_id": normalised_id,
                "message": f"Không tìm thấy lô tách chiết '{normalised_id}' trong LIMS.",
            }
        else:
            data = copy.deepcopy(lot)
            data["sop_min_yield_ng_ul"] = SOP_MIN_YIELD_NG_UL
            data["summary"] = _lot_summary(lot)
            result = {"status": "SUCCESS", "lot_id": normalised_id, "data": data}
    return json.dumps(result, ensure_ascii=False)


def execute_mark_sample_fail(
    lot_id: str,
    sample_id: str,
    reason: str,
    operator_name: str = DEFAULT_OPERATOR,
) -> str:
    """Fail one sample while preserving the status of its containing lot."""
    normalised_lot_id = _normalise(lot_id)
    normalised_sample_id = _normalise(sample_id)
    clean_reason = str(reason or "").strip()
    clean_operator = str(operator_name or DEFAULT_OPERATOR).strip() or DEFAULT_OPERATOR

    if not clean_reason:
        return json.dumps(
            {"status": "VALIDATION_ERROR", "message": "Lý do đánh dấu lỗi không được để trống."},
            ensure_ascii=False,
        )

    with _DATABASE_LOCK:
        lot = MOCK_DATABASE.get(normalised_lot_id)
        if lot is None:
            result = {
                "status": "NOT_FOUND",
                "lot_id": normalised_lot_id,
                "message": f"Không tìm thấy lô tách chiết '{normalised_lot_id}' trong LIMS.",
            }
        else:
            sample = next((item for item in lot["samples"] if item["sample_id"] == normalised_sample_id), None)
            if sample is None:
                result = {
                    "status": "NOT_FOUND",
                    "lot_id": normalised_lot_id,
                    "sample_id": normalised_sample_id,
                    "message": f"Không tìm thấy mẫu '{normalised_sample_id}' trong lô '{normalised_lot_id}'.",
                }
            else:
                previous_status = sample["status"]
                sample["status"] = "FAILED"
                sample["failure_reason"] = clean_reason
                sample["failed_by"] = clean_operator
                result = {
                    "status": "SUCCESS",
                    "lot_id": normalised_lot_id,
                    "sample_id": normalised_sample_id,
                    "previous_status": previous_status,
                    "sample_status": "FAILED",
                    "lot_status": lot["status"],
                    "failure_reason": clean_reason,
                    "operator_name": clean_operator,
                    "message": f"Đã đánh dấu FAILED cho mẫu {normalised_sample_id}; lô {normalised_lot_id} vẫn giữ trạng thái {lot['status']}.",
                }
    return json.dumps(result, ensure_ascii=False)


TOOL_ROUTER = {
    "query_extraction_lot": execute_query_extraction_lot,
    "mark_sample_fail": execute_mark_sample_fail,
}


def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Dispatch a schema-compatible call and always return JSON text."""
    executor = TOOL_ROUTER.get(tool_name)
    if executor is None:
        return json.dumps({"status": "UNKNOWN_TOOL", "error": f"Tool '{tool_name}' không tồn tại."}, ensure_ascii=False)
    try:
        return executor(**arguments)
    except TypeError as exc:
        return json.dumps({"status": "VALIDATION_ERROR", "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "EXECUTION_ERROR", "error": str(exc)}, ensure_ascii=False)
