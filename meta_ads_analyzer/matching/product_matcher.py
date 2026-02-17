"""Product matching logic to ensure market scan finds actual competitors.

Detects when market scan results don't match the focus brand's product type,
and triggers keyword expansion to find real competitors.
"""

from __future__ import annotations

import anthropic

from meta_ads_analyzer.models import BrandReport, PatternReport
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class ProductMatcher:
    """Matches focus brand against market scan results to detect mismatches."""

    def __init__(self, config: dict):
        self.config = config
        self.client = anthropic.AsyncAnthropic()
        self.model = config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514")

    async def extract_product_attributes(self, brand_report: BrandReport) -> dict:
        """Extract product type and key attributes from brand analysis.

        Args:
            brand_report: Brand report from Step 1 analysis

        Returns:
            Dict with product_type, pain_points, application_method, category
        """
        logger.info(f"Extracting product attributes for {brand_report.advertiser.page_name}")

        # Get pattern analysis
        pattern = brand_report.pattern_report

        # Get summary if available
        summary_text = getattr(pattern, 'summary', None) or 'N/A'

        prompt = f"""Analyze this brand's advertising to extract their core product attributes.

Brand: {brand_report.advertiser.page_name}
Total Ads Analyzed: {pattern.total_ads_analyzed}

Pattern Analysis Summary:
{summary_text}

Top Patterns:
{self._format_patterns(pattern)}

Extract:
1. Product Type: Specific product category (e.g., "silicone wrinkle patches", "mouth tape", "collagen supplements")
2. Pain Points: Primary pain points addressed (e.g., "wrinkles, fine lines, aging skin")
3. Application Method: How product is used (e.g., "topical patch", "oral supplement", "tape applied to skin")
4. Product Category: Broad category (e.g., "skincare", "sleep aid", "supplement")

Return JSON:
{{
  "product_type": "specific product",
  "pain_points": ["pain1", "pain2", "pain3"],
  "application_method": "how it's used",
  "category": "broad category"
}}"""

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        text = response.content[0].text.strip()

        logger.debug(f"Claude response for product attributes: {text[:500]}")

        # Extract JSON from response
        if "{" in text and "}" in text:
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                json_str = text[start:end]
                data = json.loads(json_str)

                # Validate required fields
                required = ['product_type', 'category']
                missing = [f for f in required if f not in data]
                if missing:
                    logger.error(f"Missing required fields in response: {missing}")
                    raise ValueError(f"Missing fields: {missing}")

                logger.info(
                    f"Extracted product attributes: {data['product_type']} | "
                    f"Category: {data['category']}"
                )
                return data
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Failed JSON string: {json_str}")
                raise ValueError(f"Failed to parse JSON: {e}")

        logger.error(f"No JSON found in response: {text}")
        raise ValueError("Failed to extract product attributes from response")

    def detect_mismatch(
        self,
        focus_brand_attrs: dict,
        market_reports: list[BrandReport]
    ) -> tuple[bool, dict]:
        """Detect if market scan results match focus brand's product.

        Args:
            focus_brand_attrs: Product attributes from extract_product_attributes
            market_reports: Brand reports from market scan

        Returns:
            (is_mismatch, mismatch_details)
        """
        if not market_reports:
            return False, {}

        # Extract product types from market brands
        market_product_types = []
        for report in market_reports:
            # Use advertiser name and pattern analysis to infer product
            name = report.advertiser.page_name.lower()

            # Simple heuristic detection
            if "tape" in name or "mouth" in name:
                market_product_types.append("mouth_tape")
            elif "patch" in name or "wrinkle" in name:
                market_product_types.append("wrinkle_patch")
            elif "supplement" in name or "vitamin" in name:
                market_product_types.append("supplement")
            else:
                market_product_types.append("unknown")

        # Count dominant product type
        from collections import Counter
        type_counts = Counter(market_product_types)
        dominant_type, dominant_count = type_counts.most_common(1)[0]

        dominant_pct = dominant_count / len(market_product_types) * 100

        # Check if focus brand matches dominant type
        focus_type = focus_brand_attrs["product_type"].lower()
        focus_category = focus_brand_attrs["category"].lower()

        is_mismatch = False
        mismatch_details = {
            "dominant_market_type": dominant_type,
            "dominant_percentage": dominant_pct,
            "focus_brand_type": focus_brand_attrs["product_type"],
            "focus_brand_category": focus_brand_attrs["category"],
        }

        # Detect mismatch
        if dominant_type == "mouth_tape" and "patch" in focus_type:
            is_mismatch = True
            mismatch_details["reason"] = (
                f"Market scan found mouth tape products ({dominant_pct:.0f}%) "
                f"but focus brand sells {focus_brand_attrs['product_type']}"
            )
        elif dominant_type == "wrinkle_patch" and "tape" in focus_type and "mouth" in focus_type:
            is_mismatch = True
            mismatch_details["reason"] = (
                f"Market scan found wrinkle patches ({dominant_pct:.0f}%) "
                f"but focus brand sells {focus_brand_attrs['product_type']}"
            )
        elif dominant_type == "supplement" and focus_category in ["skincare", "sleep"]:
            is_mismatch = True
            mismatch_details["reason"] = (
                f"Market scan found supplements ({dominant_pct:.0f}%) "
                f"but focus brand is in {focus_brand_attrs['category']} category"
            )

        if is_mismatch:
            logger.warning(f"Product mismatch detected: {mismatch_details['reason']}")
        else:
            logger.info(f"Product match confirmed: {dominant_type} aligns with focus brand")

        return is_mismatch, mismatch_details

    async def generate_expansion_keywords(
        self,
        product_attrs: dict,
        primary_keyword: str
    ) -> list[str]:
        """Generate alternative keywords based on product attributes.

        Args:
            product_attrs: Product attributes from extract_product_attributes
            primary_keyword: Original keyword that had mismatch

        Returns:
            List of 4-5 alternative keywords focused on the actual product
        """
        logger.info("Generating expansion keywords based on product attributes")

        prompt = f"""Generate 4-5 alternative search keywords for Meta Ad Library based on this product.

Product: {product_attrs['product_type']}
Category: {product_attrs['category']}
Pain Points: {', '.join(product_attrs['pain_points'])}
Application: {product_attrs['application_method']}

Original Keyword (had wrong results): "{primary_keyword}"

Generate keywords that will find ads for THIS specific product type, not unrelated products.

Rules:
- Focus on the exact product type (e.g., "wrinkle patches", not "collagen tape")
- Include product format variations (e.g., "anti wrinkle patches", "silicone wrinkle patches")
- Mix specific product terms with pain point terms (e.g., "patches for wrinkles", "collagen patches face")
- Keep each keyword 2-4 words max
- Order by most specific to broader

Return JSON array of 4-5 keywords:
["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]"""

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=512,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        text = response.content[0].text.strip()

        # Extract JSON array from response
        if "[" in text and "]" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            keywords = json.loads(text[start:end])

            logger.info(f"Generated {len(keywords)} expansion keywords: {keywords}")
            return keywords

        raise ValueError("Failed to generate expansion keywords from response")

    def _format_patterns(self, pattern: PatternReport) -> str:
        """Format pattern report for prompt."""
        lines = []

        if hasattr(pattern, 'patterns') and pattern.patterns:
            for i, p in enumerate(pattern.patterns[:5], 1):
                lines.append(f"{i}. {p.get('pattern', 'N/A')}")

        return "\n".join(lines) if lines else "No patterns available"
