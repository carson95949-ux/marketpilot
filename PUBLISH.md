# Publish MarketPilot

## Render
1. Put this folder in a GitHub repository.
2. Create a Render account and connect GitHub.
3. Choose **New -> Blueprint** and select the repo. `render.yaml` creates the service and persistent disk.
4. In Render Environment, add `SESSION_ENCRYPTION_KEY` and any Polymarket Builder credentials.
5. Deploy.

For real use, keep the persistent disk. Render free web services use an ephemeral filesystem, so local SQLite user/purchase data can be lost after a restart.

## Domain
Render -> your service -> Settings -> Custom Domains -> Add Custom Domain. Follow the DNS records Render gives you. Render handles HTTPS after DNS verifies.

## Stripe test mode
1. Create a Stripe account.
2. In Stripe Developers, copy an `sk_test_...` secret key into `STRIPE_SECRET_KEY`.
3. Leave `STRIPE_BUSINESS_APPROVED=false`. The app allows test keys for development.
4. Create a Stripe webhook endpoint: `https://YOUR-DOMAIN/stripe/webhook`.
5. Subscribe to `checkout.session.completed`.
6. Copy the `whsec_...` secret into `STRIPE_WEBHOOK_SECRET`.
7. Test checkout with Stripe test cards.

Do not switch to an `sk_live_...` key unless Stripe explicitly approves MarketPilot's business model.

## Polymarket connection
The browser generates a trading-only session signer with ethers.js. The server encrypts it and submits authorization using your Builder credentials. Set:
- POLYMARKET_BUILDER_API_KEY
- POLYMARKET_BUILDER_SECRET
- POLYMARKET_BUILDER_PASSPHRASE
- SESSION_ENCRYPTION_KEY

Users connect from My Account. Session Keys are for current Polymarket Deposit Wallet accounts; legacy wallet types may not support this flow.
