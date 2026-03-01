"""
facebook_poster.py — Facebook Page + Instagram Business posting (Gold Tier).

Uses Facebook Graph API v19+ to:
  - Post to a Facebook Page
  - Post to an Instagram Business account (connected to the Page)
  - Get engagement summary (likes, comments, reach)

Setup:
  1. Create a Facebook App at developers.facebook.com
  2. Add Facebook Login + Pages API + Instagram Graph API permissions
  3. Generate a Page Access Token (long-lived, 60 days)
  4. Find your Page ID and Instagram Account ID from Graph API Explorer
  5. Set in .env (see below)

Environment variables (.env):
  FB_PAGE_ACCESS_TOKEN    — long-lived page access token
  FB_PAGE_ID              — your Facebook Page ID
  IG_ACCOUNT_ID           — Instagram Business account ID (linked to FB Page)
  FACEBOOK_API_VERSION    — Graph API version (default: v19.0)
  DRY_RUN                 — if "true", logs but does not post
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import urllib.request
import urllib.parse
import urllib.error
from dotenv import load_dotenv

load_dotenv()

API_VERSION = os.getenv("FACEBOOK_API_VERSION", "v19.0")
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


# ──────────────────────────────────────────────────────────────────────
# HTTP helper (no requests dependency)
# ──────────────────────────────────────────────────────────────────────

def _graph_post(endpoint: str, params: dict) -> dict:
    """Make a POST request to the Graph API."""
    url = f"{BASE_URL}/{endpoint}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        return {"error": {"code": err.code, "message": body}}


def _graph_get(endpoint: str, params: dict) -> dict:
    """Make a GET request to the Graph API."""
    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/{endpoint}?{query}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        return {"error": {"code": err.code, "message": body}}


# ──────────────────────────────────────────────────────────────────────
# Facebook Page posting
# ──────────────────────────────────────────────────────────────────────

def post_to_facebook(message: str, dry_run: bool = None) -> dict:
    """
    Post a message to the configured Facebook Page.
    Returns dict with post_id or error.
    """
    if dry_run is None:
        dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    page_id = os.getenv("FB_PAGE_ID", "")
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "")

    if not page_id or not token:
        return {"error": "FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN not set in .env"}

    if dry_run:
        return {"dry_run": True, "message": f"[DRY RUN] Would post to Facebook Page {page_id}: {message[:80]}..."}

    result = _graph_post(f"{page_id}/feed", {
        "message": message,
        "access_token": token,
    })

    if "id" in result:
        return {"success": True, "post_id": result["id"], "platform": "facebook"}
    return {"error": result.get("error", {}).get("message", "Unknown error")}


# ──────────────────────────────────────────────────────────────────────
# Instagram posting
# ──────────────────────────────────────────────────────────────────────

def post_to_instagram(caption: str, image_url: Optional[str] = None, dry_run: bool = None) -> dict:
    """
    Post to Instagram Business account.
    For text-only posts, uses a default branded image URL or carousel.
    image_url: publicly accessible image URL (required for Instagram posts).
    """
    if dry_run is None:
        dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    ig_id = os.getenv("IG_ACCOUNT_ID", "")
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "")  # Same token works for IG via FB

    if not ig_id or not token:
        return {"error": "IG_ACCOUNT_ID or FB_PAGE_ACCESS_TOKEN not set in .env"}

    if dry_run:
        return {"dry_run": True, "message": f"[DRY RUN] Would post to Instagram {ig_id}: {caption[:80]}..."}

    if not image_url:
        return {"error": "Instagram requires an image_url. Provide a publicly accessible image URL."}

    # Step 1: Create media container
    container = _graph_post(f"{ig_id}/media", {
        "image_url": image_url,
        "caption": caption,
        "access_token": token,
    })

    if "id" not in container:
        return {"error": f"Failed to create IG media container: {container}"}

    # Step 2: Publish the container
    result = _graph_post(f"{ig_id}/media_publish", {
        "creation_id": container["id"],
        "access_token": token,
    })

    if "id" in result:
        return {"success": True, "post_id": result["id"], "platform": "instagram"}
    return {"error": result.get("error", {}).get("message", "Unknown error")}


# ──────────────────────────────────────────────────────────────────────
# Engagement summary
# ──────────────────────────────────────────────────────────────────────

def get_facebook_summary(days: int = 7) -> dict:
    """Get Facebook Page engagement summary for the last N days."""
    page_id = os.getenv("FB_PAGE_ID", "")
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "")

    if not page_id or not token:
        return {"error": "FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN not set in .env"}

    result = _graph_get(f"{page_id}/insights", {
        "metric": "page_impressions,page_engaged_users,page_fans",
        "period": "week",
        "access_token": token,
    })

    if "data" in result:
        summary = {"platform": "facebook", "period_days": days, "metrics": {}}
        for item in result["data"]:
            name = item.get("name", "")
            values = item.get("values", [])
            if values:
                summary["metrics"][name] = values[-1].get("value", 0)
        return summary

    return {"error": result.get("error", {}).get("message", "Could not fetch insights")}


def save_summary_to_vault(summary: dict, vault_path: str) -> Path:
    """Save social media summary to AI_Employee_Vault/Social/."""
    social_dir = Path(vault_path) / "Social"
    social_dir.mkdir(exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    platform = summary.get("platform", "facebook")
    filepath = social_dir / f"{platform}_summary_{date_str}.md"

    metrics = summary.get("metrics", {})
    metrics_md = "\n".join(f"| {k} | {v} |" for k, v in metrics.items()) or "| No data | — |"

    content = f"""---
type: social_summary
platform: {platform}
generated: {now.isoformat()}
period_days: {summary.get('period_days', 7)}
---

## {platform.title()} Engagement Summary — {date_str}

| Metric | Value |
|--------|-------|
{metrics_md}

---
*Generated by AI Employee — Gold Tier*
"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AI Employee — Facebook/Instagram Poster (Gold Tier)")
    parser.add_argument("--message", required=True, help="Post content")
    parser.add_argument("--platform", choices=["facebook", "instagram", "both"], default="facebook")
    parser.add_argument("--image-url", default="", help="Image URL (required for Instagram)")
    parser.add_argument("--summary", action="store_true", help="Get engagement summary instead of posting")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument("--dry-run", action="store_true",
                        default=os.getenv("DRY_RUN", "true").lower() == "true")
    args = parser.parse_args()

    if args.summary:
        summary = get_facebook_summary()
        print(json.dumps(summary, indent=2))
        if "error" not in summary:
            path = save_summary_to_vault(summary, args.vault)
            print(f"Summary saved: {path}")
        return

    if args.platform in ("facebook", "both"):
        result = post_to_facebook(args.message, dry_run=args.dry_run)
        print(f"Facebook: {result}")

    if args.platform in ("instagram", "both"):
        result = post_to_instagram(args.message, image_url=args.image_url, dry_run=args.dry_run)
        print(f"Instagram: {result}")


if __name__ == "__main__":
    main()
