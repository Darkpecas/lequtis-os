# ChatGPT → Hermes route (G02 / G03)

Disposable contract for the authorized bridge. **Live Hostinger remains OPEN.**
This route module has no tunnel transport; environment flags and a local Hermes
binary check cannot contact or verify Hostinger.

```sh
# Disposable (default)
python3 runtime/chatgpt_hermes_route/route.py
python3 tests/test_hermes_route.py

# Local Hermes check only (does not contact Hostinger or verify a live route)
LEQUTIS_HERMES_ROUTE=live \
python3 runtime/chatgpt_hermes_route/route.py
```

The local check always reports `live_host: false` and keeps G02/G03 partial.
Those gates can only advance after an actual tunneled probe returns an auditable
remote receipt. Receipts redact key/token/secret fields.
