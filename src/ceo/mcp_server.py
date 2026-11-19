"""Model Context Protocol (MCP) STDIO server for remote agent management."""
import json
import sys
from typing import Dict, Any, List, Optional

from src.db.manager import DatabaseManager
from src.ceo.orchestrator import CeoOrchestrator


class McpServer:
    """Implements standard MCP JSON-RPC protocol over STDIO."""

    def __init__(self, orchestrator: CeoOrchestrator):
        self.orchestrator = orchestrator
        self.tools = {
            "list_hot_jobs": self._tool_list_hot_jobs,
            "get_job_details": self._tool_get_job_details,
            "get_agency_stats": self._tool_get_agency_stats,
            "draft_proposal": self._tool_draft_proposal,
            "chat_with_ceo": self._tool_chat_with_ceo
        }

    def _tool_list_hot_jobs(self, args: Dict[str, Any]) -> Any:
        min_roi = float(args.get("min_roi", 5.0))
        limit = int(args.get("limit", 10))
        return self.orchestrator.list_hot_opportunities(min_roi=min_roi, limit=limit)

    def _tool_get_job_details(self, args: Dict[str, Any]) -> Any:
        job_id = args.get("job_id", "")
        job = self.orchestrator.db.get_job(job_id)
        if not job:
            return {"error": f"Job {job_id} not found."}
        return job

    def _tool_get_agency_stats(self, args: Dict[str, Any]) -> Any:
        return self.orchestrator.get_status_overview()

    def _tool_draft_proposal(self, args: Dict[str, Any]) -> Any:
        job_id = args.get("job_id", "")
        custom_instructions = args.get("custom_instructions", "")
        return self.orchestrator.draft_proposal(job_id, custom_instructions)

    def _tool_chat_with_ceo(self, args: Dict[str, Any]) -> Any:
        message = args.get("message", "")
        return {"response": self.orchestrator.handle_message(message)}

    def handle_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "list_hot_jobs",
                            "description": "Lists highest ROI opportunities available in the agency.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"min_roi": {"type": "number"}, "limit": {"type": "integer"}}
                            }
                        },
                        {
                            "name": "get_job_details",
                            "description": "Fetches complete details for a specific job ID.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"job_id": {"type": "string"}},
                                "required": ["job_id"]
                            }
                        },
                        {
                            "name": "get_agency_stats",
                            "description": "Retrieves daily pipeline throughput, token expenses, and status.",
                            "inputSchema": {"type": "object"}
                        },
                        {
                            "name": "draft_proposal",
                            "description": "Triggers customized proposal drafting for an opportunity.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "job_id": {"type": "string"},
                                    "custom_instructions": {"type": "string"}
                                },
                                "required": ["job_id"]
                            }
                        },
                        {
                            "name": "chat_with_ceo",
                            "description": "Sends a message or command directly to the Agency CEO.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                                "required": ["message"]
                            }
                        }
                    ]
                }
            }

        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            if tool_name in self.tools:
                try:
                    res = self.tools[tool_name](tool_args)
                    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(res, default=str)}]}}
                except Exception as e:
                    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}

        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not supported: {method}"}}
