"""cloud — Cloud agent package for the AI Employee (Platinum Tier).

Cloud agent responsibilities:
  - Email triage via GmailWatcher (domain="cloud")
  - Draft email/social replies into Pending_Approval/cloud/
  - Health monitoring → Signals/health_cloud.json
  - Vault sync push via VaultSync

Forbidden on cloud:
  - Sending emails (no SMTP send)
  - WhatsApp access
  - Banking / payment actions
  - Writing Dashboard.md directly
"""
