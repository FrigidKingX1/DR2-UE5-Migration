"""ue_mcp: minimal MCP client for Unreal 5.8's ModelContextProtocol plugin.

Talks Streamable HTTP (JSON-RPC 2.0 over POST /mcp, responses as JSON or
SSE) to the editor-embedded server at http://127.0.0.1:8000/mcp.

With Tool Search enabled (default) the server exposes three meta-tools:
list_toolsets / describe_toolset / call_tool.

CLI:
  python -m ue_mcp init                 # handshake + list tools
  python -m ue_mcp toolsets             # list_toolsets
  python -m ue_mcp describe <toolset>   # describe_toolset
  python -m ue_mcp call <tool> <json>   # call_tool {tool, arguments}
  python -m ue_mcp raw <method> <json>  # raw tools/call {name, arguments}
"""

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/mcp"
CLIENT_INFO = {"name": "ue_mcp", "version": "1.0"}


class McpClient:
    def __init__(self, base=BASE):
        self.base = base
        self.session_id = None
        self.next_id = 1

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept":
             "application/json, text/event-stream"}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _read_sse(self, raw):
        """Extract the last JSON-RPC object from an SSE body."""
        for line in reversed(raw.decode("utf-8", "replace").splitlines()):
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        raise RuntimeError("SSE body contained no data payload: %r" % raw[:400])

    def post(self, payload, expect_reply=True):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base, data=data,
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body = e.read()
            raise RuntimeError("HTTP %s: %s" % (e.code, body[:300]))
        if not expect_reply:
            return None
        if not body:
            return None
        if "text/event-stream" in ctype:
            return self._read_sse(body)
        return json.loads(body.decode("utf-8", "replace"))

    def notify(self, method):
        self.post({"jsonrpc": "2.0", "method": method}, expect_reply=False)

    def rpc(self, method, params=None):
        rid = self.next_id
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        resp = self.post(payload)
        if resp is None:
            raise RuntimeError("no response for %s" % method)
        if "error" in resp:
            raise RuntimeError("rpc error: %s" % json.dumps(resp["error"])[:400])
        return resp.get("result")

    def initialize(self):
        result = self.rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self.notify("notifications/initialized")
        return result

    # Tool Search meta-tools -------------------------------------------
    def list_toolsets(self):
        return self.rpc("tools/call", {
            "name": "list_toolsets", "arguments": {}})

    def describe_toolset(self, toolset):
        return self.rpc("tools/call", {
            "name": "describe_toolset",
            "arguments": {"toolset_name": toolset}})

    def call_tool(self, tool, arguments, toolset_name=None):
        args = {"tool_name": tool, "arguments": arguments}
        if toolset_name:
            args["toolset_name"] = toolset_name
        return self.rpc("tools/call", {"name": "call_tool", "arguments": args})

    # Plain (non-search) tool call --------------------------------------
    def tools_call(self, name, arguments):
        return self.rpc("tools/call", {"name": name, "arguments": arguments})


def _result_text(result):
    """MCP tool results come back as content items; pull readable text."""
    if result is None:
        return ""
    content = result.get("content") or []
    parts = []
    for item in content:
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        else:
            parts.append(json.dumps(item)[:200])
    if result.get("isError"):
        parts.append("[isError=true]")
    return "\n".join(parts)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    c = McpClient()
    info = c.initialize()
    server = (info or {}).get("serverInfo", {})
    print("connected:", server.get("name"), server.get("version"))
    cmd = argv[0]
    if cmd == "init":
        tools = c.rpc("tools/list")
        print(json.dumps(tools, indent=2)[:4000])
    elif cmd == "toolsets":
        print(_result_text(c.list_toolsets()) or json.dumps(c.list_toolsets())[:3000])
    elif cmd == "describe":
        print(_result_text(c.describe_toolset(argv[1])) or
              json.dumps(c.describe_toolset(argv[1]))[:6000])
    elif cmd == "call":
        toolset = argv[1]
        if len(argv) > 2 and argv[-1] == "--stdin":
            payload = json.loads(sys.stdin.read())
        elif len(argv) > 2:
            payload = json.loads(argv[2])
        else:
            payload = {}
        payload.setdefault("toolset_name", toolset)
        tool = payload.get("tool_name")
        args = payload.get("arguments", {})
        print(_result_text(c.call_tool(tool, args, toolset_name=payload.get(
            "toolset_name"))))
    elif cmd == "raw":
        name, args = argv[1], json.loads(argv[2]) if len(argv) > 2 else {}
        print(_result_text(c.tools_call(name, args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
