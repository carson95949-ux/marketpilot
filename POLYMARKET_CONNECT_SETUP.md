# Polymarket account connection — V2.4

The account connector no longer requires `eth-account`, `eth-abi`, or a separate Windows installer.

## Owner setup
Add these server-side values to `.env`:

```text
POLYMARKET_BUILDER_API_KEY=
POLYMARKET_BUILDER_SECRET=
POLYMARKET_BUILDER_PASSPHRASE=
SESSION_ENCRYPTION_KEY=
```

Generate the encryption key once:

```bat
py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Customer flow
1. Customer signs into MarketPilot.
2. Customer opens **My Account**.
3. Customer connects MetaMask or Rabby.
4. Customer pastes the Polymarket Deposit Wallet address shown in Polymarket.
5. The browser creates a separate trading-only session signer.
6. The customer signs the DepositWallet authorization in their wallet.
7. MarketPilot submits the signed authorization with your Builder credentials and stores only the separate session signer encrypted at rest.
8. The customer can revoke the session from My Account.

Session Keys are intended for current Polymarket Deposit Wallet accounts. Legacy wallet types may not support this connection flow.
