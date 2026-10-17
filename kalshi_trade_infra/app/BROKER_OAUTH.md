# Broker account connections

Tau connects existing individual-user brokerage accounts in Settings → Account,
in Alpaca, Robinhood, Interactive Brokers order. Each user completes consent at
their broker. Tau never asks for the user's brokerage password. Provider app
registration and a real consent round trip are required before a connection can
be called accepted. The integration is implemented for local verification; it
has not been deployed or accepted against real customer accounts.

## Current Alpaca configuration — October 17, 2026

The user supplied both OAuth app credentials in Tau’s ignored local `.env`.
A network-free configuration/authorize-URL check passes; the credentials have not
been authenticated through real user consent. Local `APP_SECRET_KEY` is absent.
Anonymous production checks return 200 at `/healthz`, but 404 for the broker callback
and new static module. The OAuth pair has since been uploaded as two encrypted
GitHub Actions Secrets, with metadata verified. Production deployment is
assigned to the user's teammate. A whole-app candidate and broker-only SQL are
prepared; remote drift/schema/dependencies must be checked before install. Use the
[teammate deployment guide](BROKER_OAUTH_DEPLOYMENT.md). Deploy/inject/migrate before real paper consent;
preserve the server’s existing encryption key. [Check receipts and handoff](../results/broker_oauth_2026-10-17/credentials_2026-10-17/HANDOFF.md).

## Operator setup

Use Tau's ignored `.env` for local secrets or the deployment secret store for
servers. `.env.example` contains names and blank placeholders only. Neither the
server nor this configuration check automatically loads `.env`: the launcher
must inject it. Existing `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` configure
shared market data and cannot serve as OAuth client credentials.

The user-confirmed Tau production origin is
`https://d1gfpzcosqrjya.cloudfront.net`; set `APP_PUBLIC_URL` to that exact origin.
It is recorded in the ignored local `.env`; deployment still needs explicit
injection into the running web service. Production requires HTTPS; `http://127.0.0.1:8090` and
`http://localhost:8090` support local testing. No path, query, fragment or user
credentials are accepted. The service never constructs redirects from incoming
Host or proxy headers. Keep `APP_SECRET_KEY` as the same persistent, randomly
generated 32-byte urlsafe-base64 encryption key used by the app; replacing it
without a key migration makes existing Kalshi keys and broker grants unreadable.

Register these exact production redirect URIs:

| Provider | Callback |
| --- | --- |
| Alpaca | `https://d1gfpzcosqrjya.cloudfront.net/auth/brokers/alpaca/callback` |
| Robinhood | `https://d1gfpzcosqrjya.cloudfront.net/auth/brokers/robinhood/callback` |
| IBKR | `https://d1gfpzcosqrjya.cloudfront.net/auth/brokers/ibkr/callback` |

IBKR's documented authorization flow uses a `redirect_uri` carrying a `state`
query parameter. Confirm that IBKR's approved redirect configuration preserves
that parameter. No out-of-band verifier paste or password fallback is exposed.

Check configuration after loading the server environment:

```bash
python -m app.broker_oauth status
```

This prints only readiness, a safe setup reason, callback URLs and disabled Tau
execution status. It makes no network call, registers no app, and reads no account.
The normal `python -m app.schema` deployment migration includes the two additive
`app_broker_connections` and `app_broker_oauth_attempts` tables. Run migrations only
against the intended configured database as part of an authorized deployment;
the broader app migration also runs its existing migrations. No migration was
run while implementing this feature. Updating files alone is insufficient.

### Alpaca first

Register an OAuth app in the [Alpaca Connect dashboard](https://app.alpaca.markets/)
and add the callback above (a separate local callback while developing). Store
`ALPACA_OAUTH_CLIENT_ID` and `ALPACA_OAUTH_CLIENT_SECRET` privately on the web
server. Read [app registration](https://docs.alpaca.markets/us/docs/registering-your-app)
and the [OAuth protocol](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api).

The screen defaults to paper. Account reads and `data` permission are requested;
the user can explicitly select **Authorize trading at Alpaca** to additionally
request `trading`. `account:write` is not requested. The token must return the
requested scopes, and Tau verifies `/v2/account` on the selected paper or live
host before saving the encrypted grant. Only a masked account label is returned
to the browser; full identifiers stay in encrypted credentials.

An unapproved app can connect paper accounts and the developer's own live account.
Other users' live accounts and commercial use require the applicable
[Alpaca approval](https://docs.alpaca.markets/us/docs/about-connect-api).
OAuth account authorization does not change shared market-data entitlements.

### Robinhood next

Use Robinhood's official [Trading MCP onboarding](https://robinhood.com/us/en/support/articles/onboarding-an-external-agent/),
not unofficial username/password automation or its separate crypto API. Register
Tau's client and confirm hosted-platform eligibility with Robinhood; the public
help page directs unlisted hosted platforms to support. Store the approved
`ROBINHOOD_OAUTH_CLIENT_ID` and then set
`ROBINHOOD_OAUTH_PLATFORM_APPROVED=1`. Do not set that flag merely to bypass a
setup message. This adapter does not automatically register a new OAuth client.

Current published discovery metadata is checked at the fixed Robinhood hosts:
resource `https://agent.robinhood.com/mcp/trading`, authorization
`https://robinhood.com/oauth`, token `https://api.robinhood.com/oauth2/token/`.
The public client uses PKCE S256 and the advertised `internal` scope. Scope names
do not imply read-only access: Robinhood's grant can include order rights for its
dedicated Agentic account. After consent, Tau verifies MCP `initialize` only;
no tool is called and account balances/positions are not claimed verified.
Refresh credentials are encrypted for future renewal, but no worker is wired to
renew them or invoke trading tools in this change.

### Interactive Brokers last

Obtain IBKR's vendor/compliance approval for a third-party application. Follow the
[third-party Web API requirements](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/)
and [OAuth1a workflow](https://www.interactivebrokers.com/docs/web-api/authentication/oauth-1a/third-party-oauth/third-party-o-auth-workflow).
This integration uses the documented RSA/Diffie–Hellman flow, rather than
inventing an OAuth2 client-secret flow.

Configure `IBKR_OAUTH_CONSUMER_KEY`, `IBKR_OAUTH_APPROVED=1` and absolute private
server paths for `IBKR_OAUTH_SIGNING_KEY_PATH`,
`IBKR_OAUTH_ENCRYPTION_KEY_PATH`, `IBKR_OAUTH_DH_PARAMS_PATH`. Use separate RSA
signing/encryption keys, at least 2048 bits, and the approved DH parameters. Keep
keys outside Git with access restricted to the service account. Do not reuse the
sibling `trading_agent_new` paper-gateway adapter or turn it into a live adapter.

Tau obtains a request token, redirects for broker authorization, checks the
returned token/state/verifier, exchanges it for access credentials, derives an
LST and verifies the broker's HMAC proof. The time-limited LST expiry is exposed
as status. It does not initialize a brokerage session, claim portfolio-read
acceptance, or place an order. Stateful brokerage sessions and later execution
remain separate implementation and acceptance work.

## API and security contract

All routes require the signed-in Tau user. All POSTs retain the existing
`X-Recursive: 1` CSRF header requirement and session cookie protections.

| Method | Path | Request / response |
| --- | --- | --- |
| GET | `/api/brokers` | Ordered provider readiness and the current user's connection metadata; no grants |
| POST | `/api/brokers/{provider}/connect` | `{environment, permission}` → fixed-host authorization URL; Alpaca defaults to `paper` / `read` |
| GET | `/auth/brokers/{provider}/callback` | Broker parameters → fixed Settings result redirect |
| POST | `/api/brokers/{provider}/disconnect` | `{environment}` → `{disconnected: true, provider_grant_revoked: false}` |

Alpaca supports `paper` and `live`; Robinhood and IBKR expose `live` authorization
only. Invalid environments are rejected before creating state. The UI explains
broker permissions while showing that Tau execution remains disabled.

State expires after ten minutes, is stored only as SHA-256, and binds user,
provider, environment and originating Tau session. It is consumed in a committed
transaction before provider exchange. Concurrent reconnect/disconnect cannot
resurrect a superseded connection. Network calls occur outside DB transactions.
AES-256-GCM authenticates grants and private flow material with separate context
for user/provider/environment/purpose. Public status projects only safe metadata.
Callback queries are omitted from access logs, duplicate parameters are rejected,
and callback redirects are no-store with a no-referrer policy. Provider errors
are never reflected to the SPA or logged with token contents.

Disconnect immediately deletes Tau's local grant and pending attempts. It does
not claim broker-side revocation; users can revoke the app at the broker too.
Failed reconnects preserve an existing grant. Expired grants require reconnect
until a separately tested renewal worker exists.

## Deployment and acceptance

The five original GitHub market-data/news Secrets are separate from OAuth.
The supplied Alpaca OAuth client pair is now stored as two additional encrypted
GitHub Secrets. IBKR key files and other broker registration credentials are
not provisioned. See [deployment secrets](DEPLOYMENT_SECRETS.md)
for secure injection; its SSM loader currently does not load these OAuth fields.
Do not run the loader expecting it to configure them. Keep public origin and
broker callbacks aligned with TLS, cookie settings and the deployed web origin.

After deployment, verify an authenticated connection screen, complete Alpaca
paper consent, confirm masked account metadata, disconnect, and test cancelled,
expired and repeated callbacks. Then separately accept Robinhood and IBKR with
approved registrations. Mocked tests establish local contracts only. No real
broker authorization, production deployment or account-read acceptance is claimed
by those tests. Existing research/data flags and all trading gates are unchanged;
there is no equity-order dispatcher or generic MCP-tool access in this change.
