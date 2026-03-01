"""
social_mcp.py — Social Media MCP Server: Facebook, Instagram, Twitter/X (Gold Tier).

All post operations require HITL approval (saved to Pending_Approval/).
Read/summary operations are auto-approved.

Tools:
  post_facebook       — Queue Facebook post for approval
  post_instagram      — Queue Instagram post for approval
  post_twitter        — Queue tweet for approval
  get_social_summary  — Get engagement stats from all platforms

Environment variables (.env):
  FB_PAGE_ACCESS_TOKEN, FB_PAGE_ID, IG_ACCOUNT_ID  — Facebook/Instagram
  TWITTER_API_KEY, TWITTER_API_SECRET              — Twitter OAuth 1.0a
  TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET      — Twitter OAuth 1.0a
  TWITTER_BEARER_TOKEN                              — Twitter read-only
  DRY_RUN, VAULT_PATH
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SERVER_INFO = {
    "name": "social-mcp",
    "version": "1.0.0",
    "description": "Facebook, Instagram, Twitter/X posting — AI Employee Gold Tier",
}

TOOLS = [
    {
        "name": "post_facebook",
        "description": "Queue a Facebook Page post for human approval. Does NOT post immediately.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Post content"},
                "reason": {"type": "string", "description": "Business reason for this post"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "post_instagram",
        "description": "Queue an Instagram post for human approval. Requires image_url.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "caption": {"type": "string", "description": "Post caption"},
                "image_url": {"type": "string", "description": "Public image URL"},
                "reason": {"type": "string"},
            },
            "required": ["caption", "image_url"],
        },
    },
    {
        "name": "post_twitter",
        "description": "Queue a tweet for human approval. Max 280 characters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Tweet text (max 280 chars)"},
                "reason": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "get_social_summary",
        "description": "Get engagement summary from Facebook and Twitter. Auto-approved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platforms": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["facebook", "twitter"]},
                    "default": ["facebook", "twitter"],
                }
            },
            "required": [],
        },
    },
]


# ──────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────

def _create_approval(platform: str, content: str, extra_fields: dict, reason: str) -> str:
    """Save a social post approval request to Pending_Approval/."""
    vault_path = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
    pending = vault_path / "Pending_Approval"
    pending.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d_%H%M")
    filename = f"APPROVAL_{platform}_{date_str}.md"
    filepath = pending / filename

    extra_md = "\n".join(f"| {k} | {v} |" for k, v in extra_fields.items())
    content_block = f"""---
type: approval_request
action: post_{platform}
platform: {platform}
created: {now.isoformat()}
reason: "{reason}"
status: pending
---

## {platform.title()} Post — Pending Approval

| Field | Value |
|-------|-------|
| Platform | {platform.title()} |
| Reason | {reason or "Not specified"} |
{extra_md}

### Post Content

{content}

---

## To Approve
Move to `AI_Employee_Vault/Approved/`

## To Reject
Move to `AI_Employee_Vault/Rejected/`
"""
    filepath.write_text(content_block, encoding="utf-8")
    return f"Approval queued: {filename}\nReview in Pending_Approval/ and move to Approved/ to post."


def _tool_post_facebook(message: str, reason: str = "") -> str:
    return _create_approval("facebook", message, {}, reason)


def _tool_post_instagram(caption: str, image_url: str, reason: str = "") -> str:
    return _create_approval("instagram", caption, {"Image URL": image_url}, reason)


def _tool_post_twitter(text: str, reason: str = "") -> str:
    if len(text) > 280:
        return f"ERROR: Tweet too long ({len(text)} chars). Max 280."
    return _create_approval("twitter", text, {"Characters": len(text)}, reason)


def _tool_get_social_summary(platforms: list = None) -> str:
    platforms = platforms or ["facebook", "twitter"]
    results = []

    if "facebook" in platforms:
        try:
            from social.facebook_poster import get_facebook_summary
            fb = get_facebook_summary()
            if "error" in fb:
                results.append(f"Facebook: {fb['error']}")
            else:
                metrics = fb.get("metrics", {})
                metrics_str = ", ".join(f"{k}={v}" for k, v in metrics.items())
                results.append(f"Facebook: {metrics_str}")
        except Exception as e:
            results.append(f"Facebook: ERROR — {e}")

    if "twitter" in platforms:
        try:
            from social.twitter_poster import get_twitter_summary
            tw = get_twitter_summary()
            if "error" in tw:
                results.append(f"Twitter: {tw['error']}")
            else:
                results.append(
                    f"Twitter: followers={tw.get('followers', 'N/A')}, "
                    f"tweets={tw.get('tweet_count', 'N/A')}"
                )
        except Exception as e:
            results.append(f"Twitter: ERROR — {e}")

    return "\n".join(results) if results else "No social summary available"


# ──────────────────────────────────────────────────────────────────────
# JSON-RPC stdio loop
# ──────────────────────────────────────────────────────────────────────

def _respond(req_id, result=None, error=None):
    r = {"jsonrpc": "2.0", "id": req_id}
    if error:
        r["error"] = error
    else:
        r["result"] = result
    sys.stdout.write(json.dumps(r) + "\n")
    sys.stdout.flush()


def _handle(request: dict) -> None:
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        _respond(req_id, {"protocolVersion": "2024-11-05", "serverInfo": SERVER_INFO, "capabilities": {"tools": {}}})
    elif method == "tools/list":
        _respond(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "post_facebook":
                text = _tool_post_facebook(args["message"], args.get("reason", ""))
            elif name == "post_instagram":
                text = _tool_post_instagram(args["caption"], args["image_url"], args.get("reason", ""))
            elif name == "post_twitter":
                text = _tool_post_twitter(args["text"], args.get("reason", ""))
            elif name == "get_social_summary":
                text = _tool_get_social_summary(args.get("platforms"))
            else:
                _respond(req_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
                return
            _respond(req_id, {"content": [{"type": "text", "text": text}], "isError": text.startswith("ERROR")})
        except KeyError as e:
            _respond(req_id, error={"code": -32602, "message": f"Missing argument: {e}"})
        except Exception as e:
            _respond(req_id, error={"code": -32603, "message": str(e)})
    elif method == "notifications/initialized":
        pass
    elif req_id is not None:
        _respond(req_id, error={"code": -32601, "message": f"Method not found: {method}"})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            _handle(json.loads(line))
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
