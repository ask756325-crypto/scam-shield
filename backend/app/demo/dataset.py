"""SYNTHETIC demo dataset for the fictional brand "Northvale Pay".

Every record here is invented. Domains use the reserved `.example` TLD. Records are emitted by the
`demo` source with source_type="simulated" and flow through exactly the same detection engine as
live data. `epochs` lets consecutive demo scans exhibit new / changed / recurring / resolved findings.
"""
from __future__ import annotations

DEMO_BRAND = {
    "name": "Northvale Pay",
    "aliases": ["Northvale", "NV Pay"],
    "description": (
        "Northvale Pay is a digital wallet for instant peer-to-peer payments, contactless card payments, "
        "bill splitting and international money transfers with transparent fees and bank-grade security."
    ),
    "official_domains": ["northvalepay.example", "northvale.example"],
    "keywords": ["instant payments", "digital wallet", "contactless card", "money transfers", "bill splitting", "Northvale Card"],
    "website_url": "https://northvalepay.example",
    "additional_identifiers": ["Northvale Payments Ltd", "Company no. 00000000 (fictional)"],
    "official_accounts": [
        {"platform": "bluesky", "handle": "northvalepay.example", "profile_url": "https://bsky.app/profile/northvalepay.example"},
        {"platform": "mastodon", "handle": "northvale@mastodon.example", "profile_url": "https://mastodon.example/@northvale"},
    ],
    "official_apps": [
        {"store": "apple", "name": "Northvale Pay", "app_id": "com.northvale.pay", "track_id": "1550000001", "publisher_id": "1550000000", "publisher_name": "Northvale Payments Ltd", "url": "https://apps.apple.com/app/id1550000001"},
        {"store": "google_play", "name": "Northvale Pay", "app_id": "com.northvale.pay", "publisher_id": "Northvale+Payments+Ltd", "publisher_name": "Northvale Payments Ltd", "url": "https://play.google.com/store/apps/details?id=com.northvale.pay"},
    ],
    "logo_asset": "northvale-official.png",
}

ALL = [0, 1, 2]

DEMO_RECORDS: list[dict] = [
    # ---------------------------------------------------------------- official (excluded before scoring)
    {"epochs": ALL, "kind": "account", "platform": "bluesky", "external_id": "did:plc:demo-official-nv", "name": "Northvale Pay",
     "handle": "northvalepay.example", "url": "https://bsky.app/profile/northvalepay.example",
     "description": "The official Northvale Pay account. Instant payments and a digital wallet you can trust.",
     "avatar": "northvale-official.png", "links": ["https://northvalepay.example"]},
    {"epochs": ALL, "kind": "account", "platform": "mastodon", "external_id": "https://mastodon.example/@northvale", "name": "Northvale Pay",
     "handle": "northvale@mastodon.example", "url": "https://mastodon.example/@northvale",
     "description": "Product news from Northvale Pay.", "avatar": "northvale-official.png", "links": ["https://northvalepay.example/news"]},
    {"epochs": ALL, "kind": "app", "platform": "apple", "external_id": "com.northvale.pay", "track_id": "1550000001", "name": "Northvale Pay",
     "publisher_name": "Northvale Payments Ltd", "publisher_id": "1550000000", "url": "https://apps.apple.com/app/id1550000001",
     "description": "Send money instantly, split bills and pay contactless with your Northvale Card.", "avatar": "northvale-official.png"},
    {"epochs": ALL, "kind": "app", "platform": "google_play", "external_id": "com.northvale.pay", "name": "Northvale Pay",
     "publisher_name": "Northvale Payments Ltd", "publisher_id": "Northvale+Payments+Ltd",
     "url": "https://play.google.com/store/apps/details?id=com.northvale.pay",
     "description": "Send money instantly, split bills and pay contactless with your Northvale Card.", "avatar": "northvale-official.png"},

    # ---------------------------------------------------------------- impersonation candidates
    {"epochs": ALL, "kind": "account", "platform": "bluesky", "external_id": "did:plc:demo-support", "name": "Northvale Pay Support",
     "handle": "northvalepay-support.bsky.social", "url": "https://bsky.app/profile/northvalepay-support.bsky.social",
     "description": "Northvale Pay customer support team. Problems with instant payments or your digital wallet? DM us.",
     "avatar": "northvale-copy.png", "links": [],
     "variants": {1: {"description": "Official Northvale Pay customer support. Account suspended? Verify your account within 24 hours "
                                     "at northvalepay-verify.top/login or message us on WhatsApp +1 415 555 0199.",
                      "links": ["https://northvalepay-verify.top/login"]}}},
    {"epochs": [0, 1], "kind": "account", "platform": "bluesky", "external_id": "did:plc:demo-giveaway", "name": "N0rthvale Pay",
     "handle": "n0rthvalepay.bsky.social", "url": "https://bsky.app/profile/n0rthvalepay.bsky.social",
     "description": "Northvale Pay anniversary GIVEAWAY! Send 0.1 ETH and receive 0.2 ETH back. Claim your reward: bit.ly/nv-claim "
                    "— wallet check at northvalepay-secure.example/verify",
     "avatar": "northvale-copy.png", "links": ["https://bit.ly/nv-claim", "https://northvalepay-secure.example/verify"]},
    {"epochs": ALL, "kind": "account", "platform": "mastodon", "external_id": "https://social.example/@northvalerewards", "name": "Northvale Rewards",
     "handle": "northvalerewards@social.example", "url": "https://social.example/@northvalerewards",
     "description": "Digital wallet for instant peer-to-peer payments, contactless card payments and international money transfers. Earn rewards on bill splitting.",
     "avatar": "northvale-tinted.png", "links": ["https://northvale-rewards.example"]},
    {"epochs": [1, 2], "kind": "account", "platform": "mastodon", "external_id": "https://social.example/@nortvalehelp", "name": "Nortvale Pay Help",
     "handle": "nortvalehelp@social.example", "url": "https://social.example/@nortvalehelp",
     "description": "24/7 customer care for account recovery and refunds. Contact us on Telegram t.me/nvpayhelp or WhatsApp +1 415 555 0199",
     "avatar": "person.png", "links": ["https://t.me/nvpayhelp"]},

    {"epochs": ALL, "kind": "account", "platform": "mastodon", "external_id": "https://social.example/@northvalepay", "name": "Northvale Pay",
     "handle": "northvalepay@social.example", "url": "https://social.example/@northvalepay",
     "description": "Northvale Pay is a digital wallet for instant peer-to-peer payments, contactless card payments, bill splitting and international money transfers.",
     "avatar": "northvale-copy.png", "links": []},

    # ---------------------------------------------------------------- false-positive controls
    {"epochs": ALL, "kind": "account", "platform": "bluesky", "external_id": "did:plc:demo-fan", "name": "Northvale Pay Fans",
     "handle": "nvpayfans.bsky.social", "url": "https://bsky.app/profile/nvpayfans.bsky.social",
     "description": "Unofficial fan page sharing fintech news and product reviews. Not affiliated with any company.",
     "avatar": "person.png", "links": []},
    {"epochs": ALL, "kind": "account", "platform": "mastodon", "external_id": "https://trails.example/@northvalehikers", "name": "Northvale Hiking Club",
     "handle": "northvalehikers@trails.example", "url": "https://trails.example/@northvalehikers",
     "description": "Weekend trail walks around the Northvale valley. Photos, routes and meetups for all abilities.",
     "avatar": "mountain.png", "links": ["https://trails.example/northvale"]},
    {"epochs": ALL, "kind": "account", "platform": "bluesky", "external_id": "did:plc:demo-unrelated", "name": "Maya Okafor",
     "handle": "mayaokafor.bsky.social", "url": "https://bsky.app/profile/mayaokafor.bsky.social",
     "description": "Product designer. I wrote a case study about Northvale Pay onboarding.", "avatar": "person.png", "links": []},

    # ---------------------------------------------------------------- app store candidates
    {"epochs": ALL, "kind": "app", "platform": "google_play", "external_id": "com.nvpay.wallet.login", "name": "Northvale Pay - Wallet Login",
     "publisher_name": "Northvale Pay Inc Support", "publisher_id": "8812773",
     "url": "https://play.google.com/store/apps/details?id=com.nvpay.wallet.login",
     "description": "Digital wallet for instant payments and money transfers. Verify your account and connect your wallet to unlock your funds. "
                    "Support: northvalepay-secure.example/verify",
     "avatar": "northvale-shifted.png", "links": ["https://northvalepay-secure.example/verify"]},
    {"epochs": ALL, "kind": "app", "platform": "apple", "external_id": "com.quickapps.nvpay", "track_id": "1600000002", "name": "NorthvaIe Pay",
     "publisher_name": "Quick Apps LLC", "publisher_id": "99001", "url": "https://apps.apple.com/app/id1600000002",
     "description": "Instant peer-to-peer payments, contactless card payments, bill splitting and international money transfers.",
     "avatar": "northvale-tinted.png", "links": []},
    {"epochs": ALL, "kind": "app", "platform": "apple", "external_id": "com.northvale.business", "track_id": "1550000009", "name": "Northvale Pay Business",
     "publisher_name": "Northvale Payments Ltd", "publisher_id": "1550000000", "url": "https://apps.apple.com/app/id1550000009",
     "description": "Accept contactless card payments for your shop with Northvale Pay Business.", "avatar": "northvale-official.png", "links": []},
    {"epochs": ALL, "kind": "app", "platform": "apple", "external_id": "com.utilitylabs.splitcalc", "track_id": "1700000003", "name": "Bill Split Calculator for Northvale",
     "publisher_name": "Utility Labs", "publisher_id": "77120", "url": "https://apps.apple.com/app/id1700000003",
     "description": "A simple tip and bill split calculator. Works offline. No account required.", "avatar": "calculator.png", "links": []},
    {"epochs": ALL, "kind": "app", "platform": "google_play", "external_id": "com.northwind.payments", "name": "Northwind Payments",
     "publisher_name": "Northwind Traders", "publisher_id": "551200",
     "url": "https://play.google.com/store/apps/details?id=com.northwind.payments",
     "description": "Invoicing and inventory for small wholesale businesses.", "avatar": "calculator.png", "links": []},
]
