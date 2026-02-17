"""Page network detection - group related pages by brand."""

from collections import defaultdict
from typing import Optional
from urllib.parse import urlparse

import anthropic

from meta_ads_analyzer.models import PageNetwork, NetworkPage, PageType, ScrapedAd
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def detect_page_networks(
    ads: list[ScrapedAd],
    config: dict
) -> dict[str, PageNetwork]:
    """Detect brand networks by grouping related pages.

    Args:
        ads: List of scraped ads
        config: Config dict with API settings

    Returns:
        Dict mapping page_name -> PageNetwork (multiple pages may map to same network)
    """
    # Step 1: Group ads by page
    pages_to_ads = defaultdict(list)
    for ad in ads:
        pages_to_ads[ad.page_name].append(ad)

    # Step 2: Extract signals per page
    page_signals = {}
    for page_name, page_ads in pages_to_ads.items():
        page_signals[page_name] = _extract_page_signals(page_ads)

    # Step 3: Detect networks using domain + content matching
    domain_groups = _group_by_domain(page_signals)

    if not domain_groups:
        logger.info("No multi-page networks detected")
        return {}

    # Step 4: Use Claude to confirm ambiguous groupings
    networks = await _confirm_networks_with_claude(domain_groups, page_signals, config)

    # Step 5: Build page -> network mapping
    page_to_network = {}
    for network in networks:
        for page in network.pages:
            page_to_network[page.page_name] = network

    return page_to_network


def _extract_page_signals(ads: list[ScrapedAd]) -> dict:
    """Extract grouping signals from page's ads.

    Args:
        ads: List of ads from a single page

    Returns:
        Dict with domains, product_names, offer_patterns, ad_count
    """
    domains = set()
    product_names = set()
    offer_patterns = set()

    for ad in ads:
        # Extract domain
        if ad.link_url:
            domain = urlparse(ad.link_url).netloc
            if domain:
                domains.add(domain)

        # Extract product/ingredient mentions (capitalized multi-word phrases)
        text = (ad.primary_text or "") + " " + (ad.headline or "")
        words = text.split()
        for i in range(len(words)-1):
            if len(words[i]) > 2 and len(words[i+1]) > 2:
                if words[i][0].isupper() and words[i+1][0].isupper():
                    product_names.add(f"{words[i]} {words[i+1]}")

        # Extract offer patterns (discount %, trial, guarantee)
        if "%" in text:
            offer_patterns.add("percentage_discount")
        if "trial" in text.lower():
            offer_patterns.add("trial_offer")
        if "guarantee" in text.lower():
            offer_patterns.add("guarantee")

    return {
        "domains": list(domains),
        "product_names": list(product_names),
        "offer_patterns": list(offer_patterns),
        "ad_count": len(ads),
    }


def _group_by_domain(page_signals: dict) -> list[list[str]]:
    """Group pages with same primary domain.

    Args:
        page_signals: Dict mapping page_name to signals dict

    Returns:
        List of page groups (each group is a list of page names)
    """
    domain_to_pages = defaultdict(list)

    for page_name, signals in page_signals.items():
        if signals["domains"]:
            primary_domain = signals["domains"][0]  # Most common domain
            domain_to_pages[primary_domain].append(page_name)
        else:
            domain_to_pages["_no_domain"].append(page_name)  # Separate group

    # Only return groups with 2+ pages
    return [pages for pages in domain_to_pages.values() if len(pages) > 1]


async def _confirm_networks_with_claude(
    domain_groups: list[list[str]],
    page_signals: dict,
    config: dict
) -> list[PageNetwork]:
    """Use Claude to confirm/refine page groupings.

    Args:
        domain_groups: List of page groups to confirm
        page_signals: Dict mapping page_name to signals
        config: Config dict with API settings

    Returns:
        List of confirmed PageNetwork objects
    """
    if not domain_groups:
        return []

    # Build confirmation prompt
    groups_text = []
    for i, group in enumerate(domain_groups, 1):
        group_desc = f"Group {i}:\n"
        for page in group:
            signals = page_signals[page]
            group_desc += f"  - {page}\n"
            group_desc += f"    Domains: {signals['domains']}\n"
            group_desc += f"    Products: {signals['product_names'][:3]}\n"
            group_desc += f"    Ads: {signals['ad_count']}\n"
        groups_text.append(group_desc)

    prompt = f"""Analyze these page groups and confirm if they belong to the same brand network.

{chr(10).join(groups_text)}

For each group, determine:
1. Are these pages run by the same brand? (yes/no)
2. If yes, what's the brand name?
3. What's the page type for each? (branded, doctor_authority, lifestyle, niche_topic, generic)
4. Confidence level (0-1)

Return JSON:
[
  {{
    "is_network": true,
    "brand_name": "Brand X",
    "pages": [
      {{"page_name": "...", "page_type": "branded"}},
      {{"page_name": "...", "page_type": "doctor_authority"}}
    ],
    "confidence": 0.9
  }}
]

ONLY return the JSON array, no other text."""

    try:
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514"),
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse response
        import json
        text = response.content[0].text.strip()

        # Extract JSON array from response
        if "[" in text and "]" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            data = json.loads(text[start:end])

            networks = []
            for item in data:
                if item.get("is_network"):
                    # Calculate total ads and unique domains
                    page_list = []
                    total_ads = 0
                    unique_domains = set()

                    for p in item["pages"]:
                        page_name = p["page_name"]
                        signals = page_signals.get(page_name, {})
                        total_ads += signals.get("ad_count", 0)
                        unique_domains.update(signals.get("domains", []))

                        page_list.append(
                            NetworkPage(
                                page_name=page_name,
                                page_type=PageType(p["page_type"]),
                                ad_count=signals.get("ad_count", 0),
                                primary_domain=signals["domains"][0] if signals.get("domains") else None,
                                signals=[],
                            )
                        )

                    network = PageNetwork(
                        network_name=item["brand_name"],
                        primary_page=item["pages"][0]["page_name"],
                        pages=page_list,
                        total_ads=total_ads,
                        unique_domains=list(unique_domains),
                        network_confidence=item.get("confidence", 0.0),
                    )
                    networks.append(network)

            logger.info(f"Confirmed {len(networks)} brand networks via Claude")
            return networks

        logger.warning("Could not parse network confirmation response")
        return []

    except Exception as e:
        logger.error(f"Failed to confirm networks with Claude: {e}")
        return []
