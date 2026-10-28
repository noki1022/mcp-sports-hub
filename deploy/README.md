# Secure Render deployment (experimental)

This branch adds a standalone OAuth 2.1 authorization-code + PKCE (S256) gateway in front of the original Sports Hub. **Not yet validated with a live ChatGPT OAuth handshake.** Do not merge or switch production deployment until the tests and end-to-end login succeed.

## Render build and start

- Build: `npm ci && npm run build`
- Start: `node deploy/start.mjs`
- Required secret environment variables (set in Render dashboard, never in GitHub):
  - `PUBLIC_BASE_URL=https://YOUR-RENDER-SERVICE.onrender.com`
  - `MCP_ADMIN_PASSWORD`: random unique password, at least 20 characters
  - `MCP_TOKEN_SECRET`: random unique signing secret, at least 32 characters
  - `SPORTS_HUB_PROVIDERS=espn,openliga,footballdatauk`
- Remove old `SPORTS_HUB_PORT` and `SPORTS_HUB_HOST` environment variables if present. The launcher forces private loopback port 3000. Render public port defaults to `PORT=10000`.

## Endpoints

- `GET /health` health check (public)
- `GET /.well-known/oauth-authorization-server` OAuth authorization metadata
- `GET /.well-known/oauth-protected-resource/mcp` OAuth resource metadata
- `POST /register` OAuth dynamic client registration restricted to ChatGPT redirect hosts
- `GET /authorize` login form
- `POST /approve` private password approval
- `POST /token` one-time authorization-code redemption with PKCE
- `/mcp` authenticated reverse proxy to `127.0.0.1:3000`

## Known limitations / security review before production

- In-memory OAuth registrations and authorization codes are lost on restart; users must reauthorize.
- Access tokens expire after 1 hour; refresh tokens are not implemented.
- Registration is restricted to `chatgpt.com` and `chat.openai.com`; verify exact callback URI against the ChatGPT client.
- Rate limiting is per remote address and is not durable across restarts.
- Password is checked on the server, never committed.
- This is a minimal, single-user proof of concept, **not a security-audited production identity provider**. Consider using a managed OAuth provider for production.
