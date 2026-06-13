"""Curated dense crypto-RU channel list for the offline scoring eval (~29 handles).

GOAL: one tight TOPIC CLUSTER (Russian-language crypto news) where the SAME story
realistically lands across many channels within minutes/hours — the missing
ingredient for the viral-score design. Prod data today is 75% one channel, so the
cross_channel term and velocity's Δchannel_count are structurally starved (0 clusters
span 3+ channels). Density beats time-depth: 29 channels all covering crypto news
will produce real multi-channel clusters; 10y of one channel teaches nothing about
cross-channel virality.

SOURCING: discovered via TGStat-adjacent public directories (tlgrm.ru, tgrm.su) +
vc.ru curated lists, then EVERY handle re-verified LIVE via https://t.me/s/<handle>
(public feed + subscriber count) on 2026-06-13. Dead/squatted handles dropped.
Pure trading-signal / pump groups excluded — we want NEWS/MEDIA so the same *event*
co-occurs across channels (that is what the score is supposed to detect).

Topical sub-clusters (all crypto, will co-cluster on big news):
  core news/media · investing+crypto · TON ecosystem
"""

# (handle, subscribers_at_verify_2026-06-13, note)
CRYPTO_RU_VERIFIED = [
    # ── core RU crypto news / media ──────────────────────────────────────────
    ("@decenter", "2.24M", "DeCenter — блокчейн/монеты/DeFi"),
    ("@investkingyru", "2.1M", "InvestKing — крипто-инвестиции"),
    ("@coin_post", "300K", "CoinPost — выжимка крипто-новостей"),
    ("@Pro_Blockchain", "176K", "Pro Blockchain — проекты/ICO"),
    ("@crypto_sekta", "167K", "Криптосекта — рынок/инвесторы"),
    ("@RBCCrypto", "135K", "РБК Крипто"),
    ("@crypto_hd", "135K", "Crypto Headlines — агрегатор новостей"),
    ("@criptovest", "130K", "Криптовест"),
    ("@slezisatoshi", "128K", "Слёзы Сатоши — обзор рынка"),
    ("@if_market_news", "121K", "InvestFuture Market News"),
    ("@incrypted", "112K", "Incrypted — новости и разборы"),
    ("@icospeaksnews", "112K", "ICO Speaks News"),
    ("@binance_ru", "99.7K", "Binance Новости RU"),
    ("@forklog", "94.1K", "ForkLog — крупнейшее RU крипто-медиа"),
    ("@cryptodaily", "89.7K", "Crypto Daily"),
    ("@crypnews247", "49.1K", "CrypNews247"),
    ("@blockchainrf", "19.9K", "Blockchain RF"),
    ("@bitcoin_cryptonews", "17.8K", "Bitcoin Crypto News"),
    ("@bitcoin_magazine", "15.2K", "Bitcoin Magazine RU"),
    ("@hashtelegraph", "13K", "Hash Telegraph"),
    ("@bitsmedia", "10.5K", "BITS.MEDIA — RU крипто-портал"),
    ("@whattonews", "6.94K", "WhattoNews"),
    ("@web3news", "5.98K", "Web3 News RU"),
    # ── investing channels with heavy crypto coverage ────────────────────────
    ("@bitkogan", "263K", "Bitkogan — инвестиции+крипто"),
    ("@investfuture", "186K", "InvestFuture"),
    # ── TON ecosystem (dense co-clustering on TON news) ──────────────────────
    ("@toncoin_rus", "567K", "Toncoin RUS"),
    ("@tonworldru", "410K", "TON World RU"),
    ("@tonblockchain", "199K", "TON Blockchain"),
    ("@ruton", "139K", "RUTON — TON новости"),
]

HANDLES = [h for h, _, _ in CRYPTO_RU_VERIFIED]

if __name__ == "__main__":
    print(f"verified_live={len(HANDLES)}")
    for h, subs, note in CRYPTO_RU_VERIFIED:
        print(f"{h:24} {subs:>7}  {note}")
