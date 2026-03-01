# Social Media Skill

Post to Facebook Pages, Instagram Business accounts, and Twitter/X.
All posts require human approval before publishing (HITL workflow).

## When to Use

- User wants to post to Facebook or Instagram
- User wants to send a tweet
- User wants a social media engagement summary
- User asks what was posted recently

## Platforms Supported

| Platform | Method | Approval Required |
|----------|--------|:-----------------:|
| Facebook Page | Graph API v19+ | Yes |
| Instagram Business | Graph API (2-step) | Yes |
| Twitter/X | API v2 + OAuth 1.0a | Yes |

## Quick Start

### 1. Configure credentials in .env

```bash
# Facebook / Instagram
FACEBOOK_PAGE_ID=your_page_id
FACEBOOK_ACCESS_TOKEN=your_long_lived_page_token
INSTAGRAM_BUSINESS_ACCOUNT_ID=your_instagram_business_id

# Twitter / X
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_api_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_SECRET=your_access_token_secret
```

### 2. Use MCP tools (preferred)

The `social` MCP server exposes these tools to Claude:
- `post_facebook` — creates Facebook approval request
- `post_instagram` — creates Instagram approval request
- `post_twitter` — creates Twitter approval request
- `get_social_summary` — reads recent social data from vault (auto)

### 3. Direct Python API

```python
# Facebook
from social.facebook_poster import post_to_facebook, post_to_instagram
result = post_to_facebook("Your post content here")

# Twitter
from social.twitter_poster import post_tweet
result = post_tweet("Your tweet content here #hashtag")

# Get summary
from social.twitter_poster import get_twitter_summary, save_summary_to_vault
summary = get_twitter_summary()
save_summary_to_vault(summary, "AI_Employee_Vault")
```

## HITL Workflow

1. All social posts are saved to `AI_Employee_Vault/Pending_Approval/` as `.md` files
2. Review the content and move to `Approved/` to publish
3. The Approval Watcher dispatches the actual post
4. Summary stats are saved to `AI_Employee_Vault/Social/`

## Post Guidelines (from Company Handbook)

- Maximum 1 post per platform per day
- No political content, no invented statistics
- Add `#AI` or note AI assistance where appropriate
- Posts must be professional and factual

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Facebook token expired | Refresh long-lived token (valid 60 days) via Graph API Explorer |
| Instagram post fails | Ensure Instagram account is a Business account linked to the Facebook Page |
| Twitter 401 error | Regenerate access tokens in Twitter Developer Portal |
| Circuit open | Wait for reset timeout; check `recovery.retry_handler.CIRCUITS["facebook"].state` |
