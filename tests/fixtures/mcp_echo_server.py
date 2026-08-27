#!/usr/bin/env python3
"""Testler icin minimal MCP sunucusu (stdio, JSON-RPC 2.0).

Davranisi ortam degiskenleriyle degistirilebilir:
  MCP_TEST_MODE=hang    initialize'a hic yanit vermez
  MCP_TEST_MODE=crash   aninda cikar
  MCP_TEST_MODE=noise   yanitlardan once JSON olmayan satirlar yazar
"""

import json
import os
import sys
import time

MODE = os.environ.get("MCP_TEST_MODE", "normal")

TOOLS = [
    {
        "name": "echo",
        "description": "Verilen metni geri dondurur",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "write_thing",
        "description": "Yan etkili ornek arac",
        "inputSchema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    },
    {
        "name": "fail",
        "description": "Her zaman hata dondurur",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def send(obj):
    if MODE == "noise":
        sys.stdout.write("bu JSON degil, yoksayilmali\n")
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    if MODE == "crash":
        sys.exit(1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        mid = msg.get("id")

        if MODE == "hang":
            time.sleep(3600)

        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "test", "version": "1"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "echo":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {"content": [{"type": "text", "text": args.get("text", "")}]},
                    }
                )
            elif name == "write_thing":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "content": [
                                {"type": "text", "text": "yazildi:" + args.get("value", "")}
                            ]
                        },
                    }
                )
            elif name == "fail":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "content": [{"type": "text", "text": "bilerek hata"}],
                            "isError": True,
                        },
                    }
                )
            else:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "error": {"code": -32601, "message": "bilinmeyen arac: " + str(name)},
                    }
                )
        elif mid is not None:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": "bilinmeyen metot"},
                }
            )


if __name__ == "__main__":
    main()
