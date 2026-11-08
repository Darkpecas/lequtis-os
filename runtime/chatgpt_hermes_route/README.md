# ChatGPT → Hermes route (G02 / G03)

Disposable contract for the authorized bridge. **Live Hostinger remains OPEN**
until Alan supplies tunnel credentials on the host.

```sh
# Disposable (default)
python3 runtime/chatgpt_hermes_route/route.py
python3 tests/test_hermes_route.py

# Live attempt (operator only — never paste secrets into chat)
LEQUTIS_HERMES_ROUTE=live \
LEQUTIS_TUNNEL_ID=... \
LEQUTIS_TUNNEL_API_KEY=... \
python3 runtime/chatgpt_hermes_route/route.py
```

Receipts always redact key/token/secret fields and set `live_host` honestly.
