#!/usr/bin/env python3
"""
WebBridge Client — 连接 Docker 容器内的 Hermes Agent 到宿主机的 Chrome + Kimi WebBridge。

WebBridge API 端点: POST http://host.docker.internal:10086/command
请求体: {"action": "...", "args": {...}, "session": "..."}

用法（在 Hermes terminal 工具中）：
    python3 /workspace/webbridge_client.py fetch --url "https://..." --session hypothesis-001
    python3 /workspace/webbridge_client.py navigate --url "https://..." --session hypothesis-001 --new-tab
    python3 /workspace/webbridge_client.py snapshot --session hypothesis-001
    python3 /workspace/webbridge_client.py search --query "calendar anomaly ETF" --session hypothesis-001
    python3 /workspace/webbridge_client.py click --selector "@e12" --session hypothesis-001
    python3 /workspace/webbridge_client.py fill --selector "@e5" --value "search text" --session hypothesis-001
    python3 /workspace/webbridge_client.py evaluate --code "document.title" --session hypothesis-001
    python3 /workspace/webbridge_client.py close --session hypothesis-001
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse

# 优先从环境变量读取，兼容 docker-compose 注入的配置
WEBBRIDGE_HOST = os.environ.get("WEBBRIDGE_HOST", "host.docker.internal")
WEBBRIDGE_PORT = os.environ.get("WEBBRIDGE_PORT", "10086")
WEBBRIDGE_URL = f"http://{WEBBRIDGE_HOST}:{WEBBRIDGE_PORT}/command"


def api_request(action, args_dict, session, timeout=60):
    payload = {"action": action, "args": args_dict}
    if session:
        payload["session"] = session

    req = urllib.request.Request(
        WEBBRIDGE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        return {"error": f"HTTP {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed: {e.reason}. Is WebBridge running at http://{WEBBRIDGE_HOST}:{WEBBRIDGE_PORT}/ ?"}
    except Exception as e:
        return {"error": str(e)}


def cmd_navigate(args):
    r = api_request("navigate", {"url": args.url, "newTab": args.new_tab}, args.session)
    print(json.dumps(r, indent=2))


def cmd_find_tab(args):
    r = api_request("find_tab", {"url": args.url, "active": args.active}, args.session)
    print(json.dumps(r, indent=2))


def _check_navigate_success(r):
    """Check if navigate response indicates success.
    
    WebBridge API returns: {"ok": true, "data": {"success": true, ...}}
    """
    return r.get("ok") is True and r.get("data", {}).get("success") is True


def _extract_text_from_tree(node, lines=None, seen=None, depth=0):
    """Recursively extract all text from snapshot accessibility tree.
    
    The snapshot tree is deeply nested. Top-level 'tree' array may have
    only 2-3 nodes (banner, main, footer), but each contains many children.
    
    Avoids duplicates by skipping InlineTextBox nodes (their text is already
    in the parent's 'name' field) and tracking seen text.
    """
    if lines is None:
        lines = []
    if seen is None:
        seen = set()
    if isinstance(node, dict):
        role = node.get("role", "")
        # Skip InlineTextBox — text already captured in parent StaticText's 'name'
        if role == "InlineTextBox":
            return lines
        name = node.get("name", "")
        if name and name.strip() and not name.startswith("\n"):
            text = name.strip()
            if text not in seen:
                seen.add(text)
                lines.append("  " * depth + text)
        for child in node.get("children", []):
            _extract_text_from_tree(child, lines, seen, depth + 1)
    elif isinstance(node, list):
        for child in node:
            _extract_text_from_tree(child, lines, seen, depth)
    return lines


def _format_extracted_text(lines, max_chars=15000):
    """Format extracted lines into a readable text block."""
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... [truncated, total {len(text)} chars]"
    return text


def cmd_fetch(args):
    """Navigate (new tab) + snapshot + text extraction in one call."""
    r1 = api_request("navigate", {"url": args.url, "newTab": True}, args.session)
    if not _check_navigate_success(r1):
        print(json.dumps({"navigate_error": r1}, indent=2))
        return
    
    # Wait briefly for dynamic content to load
    import time
    time.sleep(2)
    
    r2 = api_request("snapshot", {}, args.session)
    
    # Extract all text from the nested tree
    tree = r2.get("data", {}).get("tree", [])
    extracted_lines = _extract_text_from_tree(tree)
    extracted_text = _format_extracted_text(extracted_lines)
    
    # Return both raw snapshot and extracted text
    result = {
        "ok": r2.get("ok"),
        "url": r2.get("data", {}).get("url"),
        "title": r2.get("data", {}).get("title"),
        "extracted_text": extracted_text,
        "text_chars": len(extracted_text),
        "tree_top_nodes": len(tree),
        "raw_snapshot": r2.get("data", {}),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_snapshot(args):
    r = api_request("snapshot", {}, args.session)
    
    # Extract all text from the nested tree
    tree = r.get("data", {}).get("tree", [])
    extracted_lines = _extract_text_from_tree(tree)
    extracted_text = _format_extracted_text(extracted_lines)
    
    result = {
        "ok": r.get("ok"),
        "url": r.get("data", {}).get("url"),
        "title": r.get("data", {}).get("title"),
        "extracted_text": extracted_text,
        "text_chars": len(extracted_text),
        "tree_top_nodes": len(tree),
        "raw_snapshot": r.get("data", {}),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_click(args):
    r = api_request("click", {"selector": args.selector}, args.session)
    print(json.dumps(r, indent=2))


def cmd_fill(args):
    r = api_request("fill", {"selector": args.selector, "value": args.value}, args.session)
    print(json.dumps(r, indent=2))


def cmd_evaluate(args):
    r = api_request("evaluate", {"code": args.code}, args.session)
    print(json.dumps(r, indent=2))


def cmd_screenshot(args):
    r = api_request("screenshot", {"format": args.format, "quality": args.quality}, args.session)
    print(json.dumps(r, indent=2))


def cmd_list_tabs(args):
    r = api_request("list_tabs", {}, args.session)
    print(json.dumps(r, indent=2))


def cmd_close(args):
    r = api_request("close_session", {}, args.session)
    print(json.dumps(r, indent=2))


def cmd_search(args):
    """Search via Google — navigates to Google and searches."""
    site = f" site:{args.site}" if args.site else ""
    query = args.query + site
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    r1 = api_request("navigate", {"url": url, "newTab": True}, args.session)
    if not _check_navigate_success(r1):
        print(json.dumps({"navigate_error": r1}, indent=2))
        return
    
    import time
    time.sleep(2)
    
    r2 = api_request("snapshot", {}, args.session)
    
    # Extract all text from the nested tree
    tree = r2.get("data", {}).get("tree", [])
    extracted_lines = _extract_text_from_tree(tree)
    extracted_text = _format_extracted_text(extracted_lines)
    
    result = {
        "ok": r2.get("ok"),
        "url": r2.get("data", {}).get("url"),
        "title": r2.get("data", {}).get("title"),
        "extracted_text": extracted_text,
        "text_chars": len(extracted_text),
        "tree_top_nodes": len(tree),
        "raw_snapshot": r2.get("data", {}),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_download(args):
    """Download a file via WebBridge (uses host Chrome's session/cookies).
    
    Returns base64-encoded content that the agent can decode and save.
    Useful for PDFs and other files that require browser cookies/session.
    """
    # First navigate to establish session context
    r1 = api_request("navigate", {"url": args.url, "newTab": True}, args.session)
    if not _check_navigate_success(r1):
        print(json.dumps({"navigate_error": r1}, indent=2))
        return
    
    # Use evaluate to fetch the file via browser's fetch API
    fetch_code = f'''
fetch("{args.url}")
    .then(r => r.ok ? r.arrayBuffer() : Promise.reject(r.statusText))
    .then(buf => {{
        const bytes = new Uint8Array(buf);
        const base64 = btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
        return {{success: true, base64: base64, size: bytes.length}};
    }})
    .catch(e => ({{success: false, error: e.toString()}}));
'''
    r2 = api_request("evaluate", {"code": fetch_code}, args.session)
    print(json.dumps(r2, indent=2))


def cmd_save_pdf(args):
    """Save current page as PDF using WebBridge save_as_pdf API."""
    pdf_args = {}
    if args.output:
        pdf_args["file_name"] = args.output
    
    r = api_request("save_as_pdf", pdf_args, args.session)
    print(json.dumps(r, indent=2))


def main():
    parser = argparse.ArgumentParser(description="WebBridge Client — bridge Hermes Docker agent to host Chrome")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("navigate", help="Navigate to a URL")
    p.add_argument("--url", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--new-tab", action="store_true", default=False)

    p = sub.add_parser("find_tab", help="Find an already-open tab")
    p.add_argument("--url", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--active", action="store_true", default=False)

    p = sub.add_parser("fetch", help="Navigate to URL (new tab) and return page snapshot")
    p.add_argument("--url", required=True)
    p.add_argument("--session", required=True)

    p = sub.add_parser("snapshot", help="Get current page accessibility tree snapshot")
    p.add_argument("--session", required=True)

    p = sub.add_parser("click", help="Click an element by @e ref or CSS selector")
    p.add_argument("--selector", required=True)
    p.add_argument("--session", required=True)

    p = sub.add_parser("fill", help="Fill text into an input/textarea/contenteditable")
    p.add_argument("--selector", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--session", required=True)

    p = sub.add_parser("evaluate", help="Execute JS code on the page")
    p.add_argument("--code", required=True)
    p.add_argument("--session", required=True)

    p = sub.add_parser("screenshot", help="Take a screenshot")
    p.add_argument("--format", default="png", choices=["png", "jpeg"])
    p.add_argument("--quality", type=int, default=90)
    p.add_argument("--session", required=True)

    p = sub.add_parser("list_tabs", help="List open tabs in session")
    p.add_argument("--session", required=True)

    p = sub.add_parser("close", help="Close all tabs in session")
    p.add_argument("--session", required=True)

    p = sub.add_parser("search", help="Search Google via WebBridge")
    p.add_argument("--query", required=True)
    p.add_argument("--site", default="")
    p.add_argument("--session", required=True)

    p = sub.add_parser("download", help="Download a file via WebBridge (returns base64)")
    p.add_argument("--url", required=True)
    p.add_argument("--session", required=True)

    p = sub.add_parser("save_pdf", help="Save current page as PDF to /tmp/kimi-webbridge-pdfs/")
    p.add_argument("--session", required=True)
    p.add_argument("--output", default="", help="Output file name (optional)")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    handler = globals().get(f"cmd_{args.cmd}")
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
