"""
🔌 MODEL CONTEXT PROTOCOL (MCP) SERVER MODULE
Mô phỏng kiến trúc MCP Server (Client-Server Architecture) cung cấp công cụ chuẩn hóa.
"""

import json
import sys
from typing import Dict, Any, List
from tools import TOOLS_SCHEMA, dispatch_tool_call

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class MCPLIMSServer:
    """
    Giả lập MCP Server tuân thủ chuẩn giao thức Model Context Protocol
    """
    def __init__(self, server_name: str = "lims-extraction-mcp-server"):
        self.server_name = server_name
        self.version = "2026.1.0"
        
    def list_tools(self) -> List[Dict[str, Any]]:
        """Trả về danh sách các Tools chuẩn giao thức MCP"""
        return TOOLS_SCHEMA
        
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch a tool and wrap its JSON payload in the lab's MCP envelope.
        """
        raw_content = dispatch_tool_call(tool_name, arguments)
        try:
            content = json.loads(raw_content)
        except (TypeError, json.JSONDecodeError) as exc:
            content = {
                "status": "PROTOCOL_ERROR",
                "error": f"Tool trả về nội dung JSON không hợp lệ: {exc}",
            }
        return {
            "jsonrpc": "2.0",
            "server": self.server_name,
            "tool": tool_name,
            "result": content,
        }


# Backward-compatible import for the original codelab skeleton.
MCPAcademicServer = MCPLIMSServer


if __name__ == "__main__":
    print("==========================================================")
    print("🔌 KIỂM THỬ ĐỘC LẬP MCP SERVER (LIMS Extraction)")
    print("==========================================================")
    
    server = MCPLIMSServer()
    tools = server.list_tools()
    print(f"✅ Khởi tạo thành công MCP Server: {server.server_name} (Version: {server.version})")
    print(f"📦 Số lượng Tools công bố: {len(tools)}")
    
    schemas_valid = all(t.get("parameters", {}).get("properties") for t in tools)
    print(f"{'✅' if schemas_valid else '❌'} Tool schemas: {'hợp lệ' if schemas_valid else 'thiếu properties'}")

    test_result = server.call_tool("query_extraction_lot", {"lot_id": "LOT-EXT-2026-01"})
    protocol_ok = (
        test_result.get("jsonrpc") == "2.0"
        and test_result.get("result", {}).get("status") == "SUCCESS"
    )
    print(f"{'✅' if protocol_ok else '❌'} JSON-RPC dispatch query_extraction_lot")
    print(f"   {json.dumps(test_result, ensure_ascii=False)}")
