"""Unit tests for the detection engine: normalization, matching, hashing, text, URLs, scam, scoring."""
import io

import pytest
from PIL import Image, ImageDraw

from app.candidate import CandidateRecord
from app.detection.engine import BrandContext, evaluate
from app.detection.exclusion import OfficialAccountRef, OfficialAppRef, OfficialIndex
from app.detection.logo import InvalidImage, compute_hashes, logo_similarity
from app.detection.normalize import handle_local_part, normalize, skeleton
from app.detection.publisher import publisher_signal
from app.detection.scam import scam_signal
from app.detection.scoring import assess, merge_config
from app.detection.signals import Signal
from app.detection.similarity import handle_similarity, name_similarity
from app.detection.text import description_similarities
from app.detection.urls import analyze_url, extract_urls, url_signal
from app.detection.variants import detect_variant_features, generate_search_terms


# ------------------------------------------------------------------ normalization & variants
class TestNormalization:
    def test_homoglyphs_and_leet_collapse(self):
        assert skeleton("PayPal") == skeleton("PаyPal")  # Cyrillic а
        assert skeleton("paypal") == skeleton("paypa1")
        assert skeleton("NorthvaIe") == skeleton("Northvale")  # capital I vs l
        assert skeleton("micr0soft") == skeleton("microsoft")
        assert skeleton("rnicrosoft") == skeleton("microsoft")  # rn → m

    def test_separators_and_zero_width(self):
        assert skeleton("pay.pal-support") == skeleton("paypal support")
        assert skeleton("pay​pal") == skeleton("paypal")

    def test_normalize_accents_case(self):
        assert normalize("  CAFÉ   Pay ") == "cafe pay"

    def test_handle_local_part(self):
        assert handle_local_part("@acme-help.bsky.social") == "acme-help"
        assert handle_local_part("acme@mastodon.social") == "acme"

    def test_variant_features(self):
        f = detect_variant_features("N0rthvale Pay", "Northvale Pay")
        assert f.homoglyph
        f = detect_variant_features("Northvale Pay Support", "Northvale Pay")
        assert f.contains_brand and "support" in f.risky_added_terms
        f = detect_variant_features("Nortvale Pay", "Northvale Pay")
        assert f.typo_distance == 1
        f = detect_variant_features("North vale Pay", "Northvale Pay")
        assert f.separator_variation

    def test_search_terms_bounded_and_unique(self):
        terms = generate_search_terms("Northvale Pay", ["Northvale", "NV Pay", "northvale"], max_terms=8)
        assert len(terms) <= 8
        assert terms[0] == "northvale pay"
        assert len(set(terms)) == len(terms)
        assert "northvalepay" in terms


# ------------------------------------------------------------------ similarity
class TestSimilarity:
    def test_exact_and_lookalike_names_score_high(self):
        assert name_similarity("PayPal", ["PayPal"]).score == 1.0
        assert name_similarity("PаyPa1", ["PayPal"]).score == 1.0
        assert name_similarity("PayPal Support Team", ["PayPal"]).score >= 0.8
        assert name_similarity("Paypall", ["PayPal"]).score >= 0.85

    def test_unrelated_names_score_low(self):
        assert name_similarity("Garden Tools Weekly", ["PayPal"]).score < 0.5

    def test_short_brand_requires_whole_token(self):
        assert name_similarity("Hubspot Fans", ["HP"]).score == 0.0
        assert name_similarity("HP Support", ["HP"]).score >= 0.8

    def test_missing_name_is_explicit(self):
        s = name_similarity("", ["PayPal"])
        assert not s.evaluated

    def test_handle_similarity(self):
        s = handle_similarity("paypal-support.bsky.social", ["PayPal"])
        assert s.score >= 0.8 and "support" in s.data["risky_terms"]


# ------------------------------------------------------------------ logos
def _logo(color=(30, 80, 60), shift=0, kind="n"):
    img = Image.new("RGB", (128, 128), (240, 240, 235))
    d = ImageDraw.Draw(img)
    if kind == "n":
        d.rectangle([16, 16, 112, 112], fill=color)
        d.rectangle([36 + shift, 30, 50 + shift, 98], fill=(240, 240, 235))
        d.rectangle([78 + shift, 30, 92 + shift, 98], fill=(240, 240, 235))
    else:
        d.ellipse([10, 10, 60, 60], fill=(200, 30, 30))
        d.line([0, 127, 127, 0], fill=(0, 0, 0), width=9)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class TestLogo:
    def test_identical_and_near_identical(self):
        base = compute_hashes(_logo())
        assert logo_similarity(base, compute_hashes(_logo())).score == 1.0
        assert logo_similarity(base, compute_hashes(_logo(color=(36, 86, 66)))).score >= 0.8

    def test_unrelated_logo_low(self):
        assert logo_similarity(compute_hashes(_logo()), compute_hashes(_logo(kind="x"))).score < 0.6

    def test_missing_hashes_not_evaluated(self):
        assert not logo_similarity(None, {"phash": "0" * 16}).evaluated
        assert not logo_similarity(compute_hashes(_logo()), None, "no avatar").evaluated

    def test_rejects_non_images(self):
        with pytest.raises(InvalidImage):
            compute_hashes(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
        with pytest.raises(InvalidImage):
            compute_hashes(b"GIF89a-not-really")


# ------------------------------------------------------------------ description similarity
class TestDescription:
    def test_copied_description_scores_higher_than_unrelated(self):
        corpus = ["Acme Wallet offers instant peer-to-peer payments, contactless card payments and international money transfers."]
        sims = description_similarities(
            corpus,
            [
                "Instant peer-to-peer payments, contactless card payments and international money transfers!",
                "Weekly hiking meetups and trail photography for nature lovers.",
                "",
            ],
            ["Acme Wallet"],
        )
        assert sims[0].score > 0.5
        assert sims[1].score < 0.15
        assert not sims[2].evaluated

    def test_brand_name_alone_does_not_create_similarity(self):
        sims = description_similarities(["Acme Wallet instant payments and money transfers"], ["Acme Wallet Acme Wallet fan club gossip"], ["Acme Wallet"])
        assert sims[0].score < 0.2


# ------------------------------------------------------------------ URLs & scam text
class TestUrlsAndScam:
    def test_extract_urls(self):
        urls = extract_urls("Visit acme-login.xyz/verify or https://t.me/acmehelp today")
        assert "https://acme-login.xyz/verify" in urls and "https://t.me/acmehelp" in urls

    def test_official_domain_is_neutral(self):
        assert analyze_url("https://www.acme.com/help", ["acme.com"], ["Acme"])[0] == 0.0
        assert analyze_url("https://support.acme.com", ["acme.com"], ["Acme"])[0] == 0.0

    def test_lookalike_and_brand_domains(self):
        s, reasons = analyze_url("https://acme-verify.top/login", ["acme.com"], ["Acme"])
        assert s > 0.8 and any("brand name" in r for r in reasons)
        s, _ = analyze_url("https://acrne.com", ["acme.com"], ["Acme"])
        assert s >= 0.8
        assert analyze_url("https://xn--pypal-4ve.com", ["paypal.com"], ["PayPal"])[0] >= 0.6

    def test_no_links_not_evaluated(self):
        assert not url_signal([], ["acme.com"], ["Acme"]).evaluated

    def test_scam_indicators(self):
        s = scam_signal("Acme GIVEAWAY", "Send 0.1 ETH and get double back. Verify your wallet now, DM us on WhatsApp")
        assert s.score > 0.7
        assert {"crypto_giveaway", "credential_request", "off_platform_contact"} <= set(s.data["categories"])
        benign = scam_signal("Acme fans", "We share photos of Acme products we love.")
        assert benign.score == 0.0 and benign.evaluated


# ------------------------------------------------------------------ official exclusion
class TestExclusion:
    def setup_method(self):
        self.index = OfficialIndex(
            [OfficialAccountRef("bluesky", "acme.com"), OfficialAccountRef("mastodon", "acme@mastodon.social", "https://mastodon.social/@acme")],
            [OfficialAppRef("apple", "com.acme.app", "123", "999", "Acme Inc"), OfficialAppRef("google_play", "com.acme.app", None, "Acme+Inc", "Acme Inc")],
            ["acme.com"],
        )

    def _acct(self, source, handle, url=None, **meta):
        return CandidateRecord(source=source, source_type="live", kind="account", external_id=handle, name="Acme", handle=handle, url=url, metadata=meta)

    def test_exact_platform_handle_and_domain_handle(self):
        assert self.index.match(self._acct("bluesky", "acme.com")).rule == "official_platform_handle"
        assert self.index.match(self._acct("bluesky", "news.acme.com")).rule == "bluesky_verified_domain_handle"
        assert self.index.match(self._acct("mastodon", "other@x.social", "https://mastodon.social/@acme/")).rule == "official_profile_url"

    def test_lookalike_handle_not_excluded(self):
        assert self.index.match(self._acct("bluesky", "acme-com.bsky.social")) is None
        assert self.index.match(self._acct("bluesky", "acme.com.evil.net")) is None

    def test_same_handle_on_other_platform_not_excluded(self):
        assert self.index.match(self._acct("mastodon", "acme.com")) is None

    def test_mastodon_verified_link(self):
        c = self._acct("mastodon", "acmenews@hachyderm.io", verified_links=["https://www.acme.com/"])
        assert self.index.match(c).rule == "mastodon_verified_link"

    def test_apps_by_id_not_developer_name(self):
        app = CandidateRecord(source="apple_app_store", source_type="live", kind="app", external_id="com.acme.app", name="Acme")
        assert self.index.match(app).rule == "official_app_id"
        fake = CandidateRecord(source="apple_app_store", source_type="live", kind="app", external_id="com.acme.wallet2", name="Acme",
                               publisher_name="Acme Inc", publisher_id="555")
        assert self.index.match(fake) is None  # same developer *name* is never trusted
        play = CandidateRecord(source="google_play", source_type="live", kind="app", external_id="com.acme.app", name="Acme")
        assert self.index.match(play).rule == "official_app_id"


# ------------------------------------------------------------------ publisher & scoring
def _sig(name, score, evaluated=True, **data):
    return Signal(name=name, evaluated=evaluated, score=score, data=data)


class TestScoring:
    def test_name_only_is_low(self):
        a = assess([_sig("name", 1.0), _sig("handle", 1.0), _sig("scam", 0.0), Signal.missing("logo", "none")], "account")
        assert a.relevant and a.risk_level == "low"
        assert "insufficient" in a.classification.lower()

    def test_publisher_mismatch_alone_is_low(self):
        a = assess([_sig("name", 0.9), _sig("publisher", 0.6), _sig("scam", 0.0)], "app")
        assert a.risk_level == "low"

    def test_correlated_identity_not_double_counted(self):
        one = assess([_sig("name", 0.9)], "account").risk_score
        both = assess([_sig("name", 0.9), _sig("handle", 0.9)], "account").risk_score
        assert one == both

    def test_missing_signals_do_not_inflate(self):
        missing = assess([_sig("name", 0.9), Signal.missing("logo", "no avatar")], "account")
        zero = assess([_sig("name", 0.9), _sig("logo", 0.0)], "account")
        assert missing.risk_score == zero.risk_score
        assert any("Logo" in n for n in missing.not_evaluated)

    def test_corroborated_impersonation_levels(self):
        high = assess([_sig("name", 0.95), _sig("logo", 0.95), _sig("description", 0.6), _sig("scam", 0.0)], "account")
        assert high.risk_level == "high" and high.classification.startswith("Potential impersonation")
        crit = assess([_sig("name", 0.95), _sig("logo", 0.95), _sig("scam", 0.8), _sig("urls", 0.9)], "account")
        assert crit.risk_level == "critical"

    def test_critical_requires_scam_behaviour(self):
        a = assess([_sig("name", 1.0), _sig("logo", 1.0), _sig("description", 1.0), _sig("urls", 1.0), _sig("scam", 0.0)], "account")
        assert a.risk_level == "high"

    def test_unrelated_is_info(self):
        a = assess([_sig("name", 0.3), _sig("scam", 0.9)], "account")
        assert not a.relevant and a.risk_level == "info"

    def test_same_official_publisher_capped_low(self):
        a = assess([_sig("name", 1.0), _sig("logo", 1.0), _sig("description", 0.9), _sig("publisher", 0.0, same_official_publisher=True)], "app")
        assert a.risk_level == "low"

    def test_config_overrides_validated(self):
        cfg = merge_config({"groups": {"visual": {"weight": 0.5, "threshold": 7}, "bogus": {"weight": 1}}, "levels": {"high": {"min_score": 30}}})
        assert cfg["groups"]["visual"]["weight"] == 0.5
        assert cfg["groups"]["visual"]["threshold"] == 0.75  # out-of-range value ignored
        assert "bogus" not in cfg["groups"] and cfg["levels"]["high"]["min_score"] == 30

    def test_publisher_signal_rules(self):
        official = [OfficialAppRef("apple", "com.acme.app", None, "999", "Acme Inc")]
        mk = lambda **kw: CandidateRecord(source="apple_app_store", source_type="live", kind="app", external_id="x.y", name="Acme", **kw)
        assert publisher_signal(mk(publisher_name="Acme Inc", publisher_id="999"), official, ["Acme"]).data["same_official_publisher"]
        assert publisher_signal(mk(publisher_name="Acme Support Ltd", publisher_id="1"), official, ["Acme"]).score == 0.9
        assert publisher_signal(mk(publisher_name="Utility Labs", publisher_id="2"), official, ["Acme"]).score == 0.6
        assert not publisher_signal(mk(publisher_name="Acme Inc"), official, ["Acme"]).evaluated  # no ID → can't verify
        acct = CandidateRecord(source="bluesky", source_type="live", kind="account", external_id="d", name="Acme")
        assert not publisher_signal(acct, official, ["Acme"]).evaluated


# ------------------------------------------------------------------ end-to-end engine (false-positive controls)
def test_engine_false_positive_controls():
    logo = compute_hashes(_logo())
    brand = BrandContext(
        name="Acme Wallet", aliases=["Acme"], description="Acme Wallet: instant payments, contactless card and money transfers.",
        official_domains=["acmewallet.com"], logo_hashes=logo,
        official_accounts=[OfficialAccountRef("bluesky", "acmewallet.com")],
    )
    recs = [
        CandidateRecord("bluesky", "live", "account", "did:1", "Acme Wallet", handle="acmewallet.com"),
        CandidateRecord("bluesky", "live", "account", "did:2", "Acme Wallet Support", handle="acmewallet-help.bsky.social",
                        description="Acme Wallet support. Verify your wallet at acmewallet-secure.top or DM us on Telegram.",
                        image_hashes=logo),
        CandidateRecord("bluesky", "live", "account", "did:3", "Acme Wallet Fans", handle="acmefans.bsky.social",
                        description="Unofficial fan account, photos and news."),
        CandidateRecord("bluesky", "live", "account", "did:4", "Jordan Lee", handle="jordanlee.bsky.social",
                        description="I like hiking and bread."),
    ]
    out = {e.record.external_id: e for e in evaluate(brand, recs)}
    assert out["did:1"].excluded is not None
    assert out["did:2"].assessment.risk_level == "critical"
    assert out["did:3"].assessment.risk_level == "low"
    assert out["did:4"].assessment.risk_level == "info"


# ------------------------------------------------------------------ regressions from live PayPal scan
class TestLiveFalsePositiveRegressions:
    @pytest.mark.parametrize("name", ["AnyPal", "PayPOS - Tap and Get Paid", "Payanywhere: Point of Sale POS", "FastPay Wallet", "Afterpay: Pay over time"])
    def test_similar_looking_unrelated_apps_below_relevance(self, name):
        assert name_similarity(name, ["PayPal"]).score < 0.70

    @pytest.mark.parametrize("name", ["PayPall", "Paypa1 Support", "PayPaI Wallet"])
    def test_real_lookalikes_still_relevant(self, name):
        assert name_similarity(name, ["PayPal"]).score >= 0.80

    def test_weak_scam_indicators_alone_cannot_corroborate(self):
        s = scam_signal("Payments app", "Contact our customer support team 24/7 at +1 (800) 555-0100. Official partner. Act now!")
        assert s.score <= 0.35 and "weak indicators only" in s.detail
        strong = scam_signal("x", "Contact customer support on Telegram to unlock your account")
        assert strong.score >= 0.4

    def test_brand_in_hosting_subdomain_is_weaker_than_brand_domain(self):
        sub, _ = analyze_url("https://djpaypal.bandcamp.com", ["paypal.com"], ["PayPal"])
        dom, _ = analyze_url("https://paypal-help.com", ["paypal.com"], ["PayPal"])
        assert sub < 0.5 <= dom

    def test_product_language_is_not_a_payment_request(self):
        s = scam_signal("How to Create PayPal Account", "Learn how to send money, receive payments and verify your account with customer support.")
        assert "payment_request" not in s.data["categories"]
        s2 = scam_signal("PayPal Help", "To unlock your funds pay the release fee: send us the payment in gift cards")
        assert "payment_request" in s2.data["categories"]


def test_shared_hosting_domains_never_make_every_subdomain_official():
    """Release-audit regression: listing bsky.social as an official domain excluded every *.bsky.social user."""
    from app.detection.urls import is_official_host

    idx = OfficialIndex([], [], ["bsky.social", "acme.com"])
    rec = lambda handle: CandidateRecord("bluesky", "live", "account", f"did:{handle}", "Acme", handle=handle, metadata={"platform": "bluesky"})  # noqa: E731
    assert idx.match(rec("bsky.social")) is not None  # the domain itself
    assert idx.match(rec("acme-support.bsky.social")) is None  # a user on the shared host
    assert idx.match(rec("help.acme.com")) is not None  # a subdomain the brand controls
    assert is_official_host("help.acme.com", ["acme.com"]) and not is_official_host("evil.github.io", ["github.io"])
    m = CandidateRecord("mastodon", "live", "account", "https://x/@a", "Acme", handle="a@x", metadata={"platform": "mastodon", "verified_links": ["https://scam.github.io"]})
    assert OfficialIndex([], [], ["github.io"]).match(m) is None
