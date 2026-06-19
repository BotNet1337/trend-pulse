"""SMS-number providers for the account factory (TASK-133, Layer B2).

`base` defines the `SmsProvider` Protocol + `PurchasedNumber` DTO; `fake` is the
deterministic CI impl; `smspva` is the real httpx-backed SMSPVA REST client;
`factory` selects the impl by env (`ACCOUNT_FACTORY_PROVIDER`).
"""
