"""A small, hand-labelled SYNTHETIC benchmark for the detection engine.

Every record below is fictional (brand "Acme Wallet", reserved .example/.test domains) and labelled by hand:
    positive = an impersonation an analyst should confirm
    negative = legitimate look-alike (fan, news, namesake business, partner, unrelated) that must not be flagged
It exists to catch regressions and to make the engine's trade-offs visible. It is NOT a measurement of real-world
accuracy — for that, use the analyst-labelled metrics computed from your own confirmed / marked-legitimate findings.
Logo similarity is not exercised here (no images), so scores are conservative versus real scans with a brand logo.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..candidate import CandidateRecord
from ..detection.engine import BrandContext
from ..detection.exclusion import OfficialAccountRef, OfficialAppRef

BRAND = BrandContext(
    name="Acme Wallet",
    aliases=["AcmeWallet"],
    description="Acme Wallet is a mobile wallet for instant payments, money transfers and contactless card payments.",
    keywords=["wallet", "payments", "money transfer"],
    official_domains=["acmewallet.example"],
    official_accounts=[OfficialAccountRef("bluesky", "acmewallet.example"), OfficialAccountRef("mastodon", "acmewallet@mastodon.example")],
    official_apps=[OfficialAppRef("apple", "com.acmewallet.ios", "900001", "555", "Acme Wallet Inc"),
                   OfficialAppRef("google_play", "com.acmewallet.android", None, "555", "Acme Wallet Inc")],
    official_app_descriptions=["Send money instantly, pay contactless and manage your Acme Wallet cards."],
)


@dataclass
class Case:
    id: str
    label: bool  # True = impersonation
    category: str
    record: CandidateRecord
    official: bool = False  # an official asset: must be excluded, never scored


def _acct(i, name, handle, desc, links=(), platform="bluesky"):
    return CandidateRecord(platform, "simulated", "account", f"bench:{i}", name, handle=handle, description=desc,
                           external_links=list(links), url=f"https://bench.test/{i}", metadata={"platform": platform})


def _app(i, name, pkg, publisher, pub_id, desc, store="apple", links=()):
    src = "apple_app_store" if store == "apple" else "google_play"
    return CandidateRecord(src, "simulated", "app", pkg, name, description=desc, publisher_name=publisher, publisher_id=pub_id,
                           external_links=list(links), url=f"https://bench.test/{i}", metadata={"platform": store})


CASES: list[Case] = [
    # ---------------------------------------------------------------- impersonation (positives)
    Case("p01", True, "homoglyph giveaway", _acct(1, "Acme WaIlet", "acmewaiiet.bsky.social",
         "Acme Wallet anniversary GIVEAWAY! Send 0.1 ETH and get 0.2 ETH back. Claim: bit.ly/acme-claim", ["https://bit.ly/acme-claim"])),
    Case("p02", True, "support scam", _acct(2, "Acme Wallet Support", "acmewallet-support.bsky.social",
         "Official Acme Wallet support. Account locked? Verify your wallet within 24h at acmewallet-verify.top/login or DM us on Telegram t.me/acmehelp",
         ["https://acmewallet-verify.top/login", "https://t.me/acmehelp"])),
    Case("p03", True, "recovery scam", _acct(3, "AcmeWallet Help Desk", "acmewallethelp@social.example",
         "24/7 Acme Wallet recovery team. Lost funds? Message us on WhatsApp +1 415 555 0101 to restore your wallet.", platform="mastodon")),
    Case("p04", True, "fake brand page", _acct(4, "Acme Wallet", "acme-wallet.bsky.social",
         "Instant payments, money transfers and contactless card payments. Connect your wallet to unlock rewards: acmewallet-rewards.xyz",
         ["https://acmewallet-rewards.xyz"])),
    Case("p05", True, "typo + credential link", _acct(5, "Acme Walet", "acmewalet.bsky.social",
         "Update your Acme Wallet details to avoid suspension: acme-wallet-secure.click/account", ["https://acme-wallet-secure.click/account"])),
    Case("p06", True, "fake support (mastodon)", _acct(6, "Acme Wallet Customer Care", "acmecare@social.example",
         "Official Acme Wallet customer care. Refund issues? Send your seed phrase to our verification agent via t.me/acmecare",
         ["https://t.me/acmecare"], platform="mastodon")),
    Case("p07", True, "fake login app", _app(7, "Acme Wallet - Login", "com.acmewallet.login.secure", "Acme Wallet Support Ltd", "777",
         "Send money instantly, pay contactless and manage your Acme Wallet cards. Verify your account to unlock your funds.", "google_play",
         ["https://acmewallet-login.top"])),
    Case("p08", True, "copied listing", _app(8, "AcmeWallet Pay", "com.quickdev.acmewalletpay", "Quick Dev Studio", "8080",
         "Send money instantly, pay contactless and manage your Acme Wallet cards. Instant payments and money transfers.")),
    Case("p09", True, "airdrop scam", _acct(9, "Acme Wallet Airdrop", "acmewallet-airdrop.bsky.social",
         "Free crypto airdrop for Acme Wallet users! Claim your tokens now at acme-airdrop.top", ["https://acme-airdrop.top"])),
    Case("p10", True, "payment request", _acct(10, "Acme Wallet Refunds", "acmewalletrefunds@social.example",
         "Acme Wallet refund department. To receive your refund, pay the processing fee via gift card. Contact refunds@acme-refund.top",
         platform="mastodon")),
    # ---------------------------------------------------------------- legitimate look-alikes (negatives)
    Case("n01", False, "fan account", _acct(11, "Acme Wallet Fans", "acmewalletfans.bsky.social",
         "Unofficial fan page. Tips and news about mobile payments. Not affiliated with Acme Wallet.")),
    Case("n02", False, "news commentary", _acct(12, "FinTech Weekly", "fintechweekly.bsky.social",
         "Weekly newsletter on payments. This week: Acme Wallet, Stripe and the future of contactless.")),
    Case("n03", False, "namesake business", _acct(13, "Acme Hardware", "acmehardware.bsky.social",
         "Family-run hardware store since 1952. Tools, paint and garden supplies.")),
    Case("n04", False, "namesake person", _acct(14, "Wallet Acme", "walletacme.bsky.social",
         "Photographer. Landscapes and street photography. Prints available.")),
    Case("n05", False, "developer blog", _acct(15, "Integrating Acme Wallet", "devnotes.bsky.social",
         "Blog posts about integrating payment SDKs, including the Acme Wallet API.", ["https://devnotes.test"])),
    Case("n06", False, "unrelated wallet app", _app(16, "Budget Wallet", "com.budgetapps.wallet", "Budget Apps", "4242",
         "Track expenses and set monthly budgets. Works offline.")),
    Case("n07", False, "companion utility", _app(17, "Receipt Scanner for Acme Wallet users", "com.toolsmith.receipts", "Toolsmith", "1212",
         "Scan paper receipts and export them as PDF. Independent app, not affiliated with Acme Wallet.")),
    Case("n08", False, "partner listing by official publisher", _app(18, "Acme Wallet Business", "com.acmewallet.business", "Acme Wallet Inc", "555",
         "Accept contactless card payments in your shop with Acme Wallet Business.")),
    Case("n09", False, "unrelated similar name", _acct(19, "Acmeway Travel", "acmeway.bsky.social",
         "Guided walking tours in the Alps. Book your adventure.")),
    Case("n10", False, "employee personal account", _acct(20, "Dana at Acme Wallet", "dana.bsky.social",
         "Product designer at Acme Wallet. Opinions my own. Cyclist.")),
    # ---------------------------------------------------------------- hard cases (expected to expose trade-offs)
    Case("h01", True, "quiet impersonator (no links, no scam text)", _acct(23, "Acme Wallet", "acmewallet-pay.bsky.social",
         "Payments made simple.")),
    Case("h02", False, "fan contest with giveaway wording", _acct(24, "Acme Wallet Community", "acmecommunity.bsky.social",
         "Fan-run community. Monthly giveaway of Acme Wallet stickers for the best payments meme! Not affiliated with Acme Wallet.")),
    Case("h03", False, "reseller app reusing brand copy", _app(25, "Acme Wallet Cards Shop", "com.cardshop.acme", "CardShop Retail", "3131",
         "Buy Acme Wallet gift cards. Send money instantly, pay contactless and manage your Acme Wallet cards.")),
    Case("h04", False, "parody account", _acct(26, "Acme Wallet (parody)", "acmewalletparody.bsky.social",
         "Parody account. Verify your sense of humour at the door. Not the real Acme Wallet.")),
    # ---------------------------------------------------------------- official assets (must be excluded)
    Case("o01", False, "official account", _acct(21, "Acme Wallet", "acmewallet.example", "The official Acme Wallet account."), official=True),
    Case("o02", False, "official app", _app(22, "Acme Wallet", "com.acmewallet.ios", "Acme Wallet Inc", "555",
         "Send money instantly, pay contactless and manage your Acme Wallet cards."), official=True),
]
