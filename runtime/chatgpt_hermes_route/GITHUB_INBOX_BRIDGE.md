# GitHub → existing Hermes inbox (permanent pull-transport candidate)

This is a **real implementation of a bounded transport**, not a deployed or verified Hostinger connection. It is not a replacement for LeQutis's canonical KB/graph. It polls one GitHub issue for comments beginning with `/hermes-intake`, requires an allowlisted GitHub author, writes each authorized message exactly once as an `awaiting_approval` JSON file in a pre-existing inbox, and never executes instructions. It does not currently consume the older unmarked issue #20 comment.

## VPS prerequisites (one-time authorized operator setup)
- Existing Hostinger VPS with Python 3 and a checked-out copy of this repository.
- Existing Hermes/LeQutis inbox path identified from the real installed system. Do not guess or create a parallel canonical store.
- GitHub fine-grained **read-only** token for repository issue comments, stored only in a restricted host environment file; never paste credentials into GitHub or ChatGPT.
- A local supervisor such as systemd to restart the polling process. Network access to api.github.com.
- A separate, approved Hermes dispatcher that consumes the inbox, enforces action-specific approvals, and returns authenticated receipts. **This repo change does not supply or enable that dispatcher.**

Environment: `LEQUTIS_GITHUB_READ_TOKEN`, `LEQUTIS_BRIDGE_ALLOWED_LOGIN=Darkpecas`, `LEQUTIS_BRIDGE_INBOX=<verified existing path>`, optional `LEQUTIS_BRIDGE_REPO`, `LEQUTIS_BRIDGE_ISSUE=20`, `LEQUTIS_BRIDGE_POLL_SECONDS=90`.

Run `python3 runtime/chatgpt_hermes_route/github_inbox_bridge.py --once` for a non-executing probe. Then verify a test comment's id, hash and source URL in the existing inbox and independent Hermes acknowledgement. Run under a restricted account with filesystem access limited to the inbox; do not run as root if avoidable. The worker logs counts and exception class, not task contents or secrets.

**Security boundary:** The allowlisted GitHub username is NOT sufficient as a command execution authorization. This bridge is intake only. No commands, shell, model calls, memory promotions or external effects are performed. Live Hermes delivery and graph assimilation remain OPEN until deployed and verified.
