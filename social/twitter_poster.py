"""
twitter_poster.py — Twitter/X posting and summary (Gold Tier).

Uses Twitter API v2 (OAuth 2.0 Bearer Token for read, OAuth 1.0a for write).

Setup:
  1. Go to developer.twitter.com → Create a Project + App
  2. Enable "Read and Write" permissions
  3. Generate: API Key, API Secret, Access Token, Access Token Secret, Bearer Token
  4. Set in .env (see below)

Environment variables (.env):
  TWITTER_API_KEY           — API Key (Consumer Key)
  TWITTER_API_SECRET        — API Secret (Consumer Secret)
  TWITTER_ACCESS_TOKEN      — Access Token
  TWITTER_ACCESS_SECRET     — Access Token Secret
  TWITTER_BEARER_TOKEN      — Bearer Token (for read-only operations)
  DRY_RUN                   — if "true", logs but does not post
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TWITTER_API_BASE = "https://api.twitter.com/2"


# ──────────────────────────────────────────────────────────────────────
# OAuth 1.0a signing (required for tweet posting)
# ──────────────────────────────────────────────────────────────────────

def _oauth1_header(method: str, url: str, params: dict, body: dict = None) -> str:
    """Generate OAuth 1.0a Authorization header."""
    api_key = os.getenv("TWITTER_API_KEY", "")
    api_secret = os.getenv("TWITTER_API_SECRET", "")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN", "")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET", "")

    nonce = base64.b64encode(os.urandom(32)).decode("utf-8").replace("/", "").replace("+", "")[:32]
    timestamp = str(int(time.time()))

    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    # Build signature base
    all_params = {**oauth_params, **(body or {})}
    sorted_params = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_str = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(sorted_params, safe=""),
    ])

    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(access_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()
    ).decode("utf-8")

    oauth_params["oauth_signature"] = signature
    header_parts = ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# ──────────────────────────────────────────────────────────────────────
# Twitter API calls
# ──────────────────────────────────────────────────────────────────────

def _post_tweet_api(text: str) -> dict:
    """Post a tweet using Twitter API v2 with OAuth 1.0a."""
    url = f"{TWITTER_API_BASE}/tweets"
    body = {"text": text}
    body_json = json.dumps(body).encode("utf-8")
    auth_header = _oauth1_header("POST", url, {}, {"text": text})

    req = urllib.request.Request(
        url,
        data=body_json,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return {"error": err.read().decode("utf-8")}


def _get_user_timeline() -> dict:
    """Get recent tweets from the authenticated user."""
    bearer = os.getenv("TWITTER_BEARER_TOKEN", "")
    if not bearer:
        return {"error": "TWITTER_BEARER_TOKEN not set in .env"}

    # Get user ID first
    req = urllib.request.Request(
        f"{TWITTER_API_BASE}/users/me?user.fields=public_metrics",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            user_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return {"error": err.read().decode("utf-8")}

    user_id = user_data.get("data", {}).get("id")
    metrics = user_data.get("data", {}).get("public_metrics", {})
    if not user_id:
        return {"error": "Could not get user ID"}

    return {
        "user_id": user_id,
        "followers": metrics.get("followers_count", 0),
        "following": metrics.get("following_count", 0),
        "tweet_count": metrics.get("tweet_count", 0),
        "platform": "twitter",
    }


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def post_tweet(text: str, dry_run: bool = None) -> dict:
    """
    Post a tweet. Max 280 characters.
    Returns dict with tweet_id or error.
    """
    if dry_run is None:
        dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    if not os.getenv("TWITTER_API_KEY"):
        return {"error": "TWITTER_API_KEY not set in .env — see /social-media skill for setup"}

    if len(text) > 280:
        return {"error": f"Tweet too long ({len(text)} chars). Max 280."}

    if dry_run:
        return {"dry_run": True, "message": f"[DRY RUN] Would tweet: {text[:80]}..."}

    result = _post_tweet_api(text)
    if "data" in result:
        return {"success": True, "tweet_id": result["data"]["id"], "platform": "twitter"}
    return {"error": result.get("error", "Unknown Twitter API error")}


def get_twitter_summary() -> dict:
    """Get Twitter/X account summary (followers, tweet count)."""
    return _get_user_timeline()


def save_summary_to_vault(summary: dict, vault_path: str) -> Path:
    """Save Twitter summary to AI_Employee_Vault/Social/."""
    social_dir = Path(vault_path) / "Social"
    social_dir.mkdir(exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    filepath = social_dir / f"twitter_summary_{date_str}.md"

    content = f"""---
type: social_summary
platform: twitter
generated: {now.isoformat()}
---

## Twitter/X Account Summary — {date_str}

| Metric | Value |
|--------|-------|
| Followers | {summary.get('followers', 'N/A')} |
| Following | {summary.get('following', 'N/A')} |
| Total Tweets | {summary.get('tweet_count', 'N/A')} |

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
    parser = argparse.ArgumentParser(description="AI Employee — Twitter/X Poster (Gold Tier)")
    parser.add_argument("--tweet", help="Tweet text (max 280 chars)")
    parser.add_argument("--summary", action="store_true", help="Get account summary")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument("--dry-run", action="store_true",
                        default=os.getenv("DRY_RUN", "true").lower() == "true")
    args = parser.parse_args()

    if args.summary:
        summary = get_twitter_summary()
        print(json.dumps(summary, indent=2))
        if "error" not in summary:
            path = save_summary_to_vault(summary, args.vault)
            print(f"Summary saved: {path}")
        return

    if args.tweet:
        result = post_tweet(args.tweet, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
