"""Step 1: Multi-strategy ingredient extraction from product pages.

Strategies:
  a. Supplement Facts / Nutrition Facts panel text
  b. Ingredient list text anywhere on page
  c. Product description / body copy
  d. FAQ sections
  e. Product images → Claude vision
  f. Tab content (click hidden tabs)
  g. Expandable/accordion sections
  h. Schema.org / JSON-LD structured data
  i. Meta tags and Open Graph data
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic
from playwright.async_api import Page, async_playwright

logger = logging.getLogger(__name__)


@dataclass
class Ingredient:
    name: str
    amount: str | None = None
    unit: str | None = None
    sources: list[str] = field(default_factory=list)

    def key(self) -> str:
        return re.sub(r"[^a-z0-9]", "", self.name.lower())


@dataclass
class ProductInfo:
    product_name: str = ""
    brand_name: str = ""
    description: str = ""
    claims: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    product: ProductInfo
    ingredients: list[Ingredient]
    raw_sources: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class IngredientExtractor:
    """Extract ingredients from a product page URL using multiple strategies."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        scraper_cfg = config.get("scraper", {})
        self.headless = scraper_cfg.get("headless", True)
        self.page_timeout = scraper_cfg.get("page_timeout", 60) * 1000  # ms
        self.model = config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514")
        self.client = anthropic.Anthropic()

    async def extract(self, url: str, progress_cb=None) -> ExtractionResult:
        """Run all extraction strategies and return combined results."""
        result = ExtractionResult(product=ProductInfo(), ingredients=[])

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                if progress_cb:
                    progress_cb("Loading product page...")
                await page.goto(url, wait_until="networkidle", timeout=self.page_timeout)
                await page.wait_for_timeout(2000)  # let JS finish

                # Run all strategies
                strategies = [
                    ("json_ld", self._extract_json_ld),
                    ("meta_tags", self._extract_meta_tags),
                    ("supplement_facts", self._extract_supplement_facts),
                    ("ingredient_list", self._extract_ingredient_list),
                    ("body_copy", self._extract_body_copy),
                    ("faq", self._extract_faq_content),
                    ("tabs", self._extract_tab_content),
                    ("accordions", self._extract_accordion_content),
                ]

                all_text_parts: dict[str, str] = {}
                for name, strategy in strategies:
                    if progress_cb:
                        progress_cb(f"Searching: {name}...")
                    try:
                        text = await strategy(page)
                        if text and text.strip():
                            all_text_parts[name] = text.strip()
                            logger.info(f"Strategy '{name}' found {len(text)} chars")
                    except Exception as e:
                        logger.warning(f"Strategy '{name}' failed: {e}")

                result.raw_sources = all_text_parts

                # Extract product info from page
                if progress_cb:
                    progress_cb("Extracting product info...")
                result.product = await self._extract_product_info(page, all_text_parts)

                # Image analysis with Claude vision
                if progress_cb:
                    progress_cb("Analyzing product images with vision...")
                image_text = await self._extract_from_images(page)
                if image_text:
                    all_text_parts["images_vision"] = image_text

                # Send combined text to Claude for ingredient parsing
                if progress_cb:
                    progress_cb("Parsing ingredients with Claude...")
                combined = "\n\n---\n\n".join(
                    f"[Source: {k}]\n{v}" for k, v in all_text_parts.items()
                )
                result.ingredients = await self._parse_ingredients_with_claude(combined)

                # Check for suspiciously few ingredients
                if len(result.ingredients) < 3:
                    result.warnings.append(
                        f"Only {len(result.ingredients)} ingredient(s) found. "
                        "The page may require manual input."
                    )

            finally:
                await browser.close()

        return result

    async def extract_from_text(self, text: str) -> list[Ingredient]:
        """Parse ingredients from user-provided text."""
        return await self._parse_ingredients_with_claude(f"[Source: user_input]\n{text}")

    async def extract_from_image(self, image_data: bytes) -> list[Ingredient]:
        """Extract ingredients from a user-uploaded image using Claude vision."""
        b64 = base64.b64encode(image_data).decode("utf-8")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "This is a photo of a supplement/product label. "
                                "Extract ALL ingredients listed. For each ingredient, "
                                "provide the name and amount/dosage if visible. "
                                "Return as JSON array: "
                                '[{"name": "...", "amount": "...", "unit": "..."}]'
                            ),
                        },
                    ],
                }
            ],
        )
        return self._parse_claude_ingredient_json(response.content[0].text, "user_image")

    # ── Strategy implementations ─────────────────────────────────────────────

    async def _extract_json_ld(self, page: Page) -> str:
        """Extract structured data from JSON-LD script tags."""
        scripts = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                return Array.from(scripts).map(s => s.textContent);
            }
        """)
        parts = []
        for script_text in scripts:
            try:
                data = json.loads(script_text)
                parts.append(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                pass
        return "\n".join(parts)

    async def _extract_meta_tags(self, page: Page) -> str:
        """Extract meta tags and Open Graph data."""
        meta_data = await page.evaluate("""
            () => {
                const metas = document.querySelectorAll('meta[property], meta[name]');
                return Array.from(metas).map(m => ({
                    name: m.getAttribute('name') || m.getAttribute('property') || '',
                    content: m.getAttribute('content') || ''
                })).filter(m => m.content);
            }
        """)
        return "\n".join(f"{m['name']}: {m['content']}" for m in meta_data)

    async def _extract_supplement_facts(self, page: Page) -> str:
        """Look for Supplement Facts / Nutrition Facts panels."""
        selectors = [
            ".supplement-facts", ".nutrition-facts", ".product-facts",
            "#supplement-facts", "#nutrition-facts", "#product-facts",
            '[class*="supplement"]', '[class*="nutrition"]', '[class*="facts"]',
            '[class*="ingredient"]', '[data-testid*="ingredient"]',
            '[aria-label*="Supplement"]', '[aria-label*="Nutrition"]',
        ]
        parts = []
        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements:
                    text = await el.inner_text()
                    if text and len(text.strip()) > 10:
                        parts.append(text.strip())
            except Exception:
                pass
        return "\n\n".join(parts)

    async def _extract_ingredient_list(self, page: Page) -> str:
        """Search for ingredient-related text anywhere on the page."""
        return await page.evaluate("""
            () => {
                const body = document.body.innerText;
                const lines = body.split('\\n');
                const results = [];
                let capturing = false;

                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i].trim();
                    const lower = line.toLowerCase();

                    if (lower.includes('ingredient') || lower.includes('supplement fact') ||
                        lower.includes('nutrition fact') || lower.includes('other ingredients') ||
                        lower.includes('active ingredients') || lower.includes('proprietary blend') ||
                        lower.includes('key ingredients') || lower.includes("what's inside") ||
                        lower.includes('formula contains') || lower.includes('each serving contains')) {
                        capturing = true;
                        results.push(line);
                    } else if (capturing) {
                        if (line.length === 0 && results.length > 3) {
                            capturing = false;
                        } else {
                            results.push(line);
                        }
                    }
                }
                return results.join('\\n');
            }
        """)

    async def _extract_body_copy(self, page: Page) -> str:
        """Extract main product description / body copy."""
        selectors = [
            ".product-description", ".product-body", ".product-content",
            "#product-description", "#product-content",
            '[class*="description"]', '[class*="product-detail"]',
            '[class*="product-info"]', ".rte", ".product__description",
            "article", ".product-single__description",
            '[data-product-description]',
        ]
        parts = []
        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements:
                    text = await el.inner_text()
                    if text and len(text.strip()) > 20:
                        parts.append(text.strip())
            except Exception:
                pass
        return "\n\n".join(parts)

    async def _extract_faq_content(self, page: Page) -> str:
        """Extract FAQ sections that often contain ingredient info."""
        selectors = [
            ".faq", "#faq", '[class*="faq"]', '[class*="FAQ"]',
            '[class*="accordion"]', '[class*="question"]',
            "details", "summary",
        ]
        parts = []
        # Click on FAQ elements to expand them
        for sel in [".faq summary", "details summary", '[class*="faq"] button',
                    '[class*="question"]']:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements:
                    try:
                        await el.click()
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
            except Exception:
                pass

        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements:
                    text = await el.inner_text()
                    if text and len(text.strip()) > 20:
                        parts.append(text.strip())
            except Exception:
                pass
        return "\n\n".join(parts)

    async def _extract_tab_content(self, page: Page) -> str:
        """Click tabs (Ingredients, Details, More Info) and extract content."""
        tab_selectors = [
            'button[role="tab"]', '[class*="tab"]', '.tabs button', '.tabs a',
            '[data-toggle="tab"]', '.product-tabs a', '.product-tabs button',
            'li[role="tab"]', 'a[role="tab"]',
        ]
        parts = []
        tab_keywords = ["ingredient", "detail", "more info", "info", "about",
                        "supplement", "nutrition", "what's in", "formula"]

        for sel in tab_selectors:
            try:
                tabs = await page.query_selector_all(sel)
                for tab in tabs:
                    text = (await tab.inner_text()).lower().strip()
                    if any(kw in text for kw in tab_keywords):
                        try:
                            await tab.click()
                            await page.wait_for_timeout(500)
                            # Re-extract the page content after clicking
                            body = await page.evaluate("() => document.body.innerText")
                            parts.append(f"[After clicking tab: {text}]\n{body[:3000]}")
                        except Exception:
                            pass
            except Exception:
                pass
        return "\n\n".join(parts)

    async def _extract_accordion_content(self, page: Page) -> str:
        """Expand accordion/collapsible sections and extract content."""
        accordion_selectors = [
            "details:not([open])", '[class*="accordion"] button',
            '[class*="collapsible"]', '[class*="expand"]',
            '[aria-expanded="false"]',
        ]
        parts = []
        for sel in accordion_selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements:
                    try:
                        await el.click()
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
            except Exception:
                pass

        # After expanding everything, grab the content
        try:
            expanded = await page.evaluate("""
                () => {
                    const acc = document.querySelectorAll(
                        'details, [class*="accordion"], [class*="collapsible"]'
                    );
                    return Array.from(acc).map(el => el.innerText).join('\\n\\n');
                }
            """)
            if expanded:
                parts.append(expanded)
        except Exception:
            pass
        return "\n\n".join(parts)

    async def _extract_from_images(self, page: Page) -> str:
        """Screenshot product images and analyze with Claude vision."""
        # Get all product images
        image_elements = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                return Array.from(imgs)
                    .filter(img => {
                        const src = (img.src || '').toLowerCase();
                        const alt = (img.alt || '').toLowerCase();
                        const w = img.naturalWidth || img.width;
                        const h = img.naturalHeight || img.height;
                        // Filter: reasonably sized product images
                        return (w > 200 && h > 200) &&
                            !src.includes('icon') && !src.includes('logo') &&
                            !src.includes('badge') && !src.includes('payment') &&
                            !src.includes('svg');
                    })
                    .slice(0, 8)
                    .map(img => ({src: img.src, alt: img.alt}));
            }
        """)

        if not image_elements:
            return ""

        logger.info(f"Found {len(image_elements)} product images to analyze")
        parts = []

        for i, img_info in enumerate(image_elements[:6]):  # limit to 6
            try:
                # Navigate to the image and screenshot it
                img_el = await page.query_selector(f'img[src="{img_info["src"]}"]')
                if not img_el:
                    continue

                screenshot = await img_el.screenshot()
                if not screenshot or len(screenshot) < 1000:
                    continue

                b64 = base64.b64encode(screenshot).decode("utf-8")

                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": b64,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "Does this image show a supplement facts panel, "
                                        "nutrition label, or ingredient list? "
                                        "If YES, extract ALL ingredients with their "
                                        "amounts/dosages. If NO, just say 'No ingredients found'. "
                                        "Return ONLY the ingredient data, nothing else."
                                    ),
                                },
                            ],
                        }
                    ],
                )
                text = response.content[0].text
                if "no ingredient" not in text.lower():
                    parts.append(f"[Image {i+1}: {img_info.get('alt', 'product image')}]\n{text}")
                    logger.info(f"Image {i+1}: found ingredient data")
            except Exception as e:
                logger.warning(f"Image {i+1} analysis failed: {e}")

        return "\n\n".join(parts)

    async def _extract_product_info(
        self, page: Page, text_parts: dict[str, str]
    ) -> ProductInfo:
        """Extract product name, brand, description from page."""
        page_data = await page.evaluate("""
            () => {
                const title = document.querySelector('h1')?.innerText ||
                    document.title || '';
                const ogBrand = document.querySelector('meta[property="og:site_name"]')
                    ?.getAttribute('content') || '';
                const ogTitle = document.querySelector('meta[property="og:title"]')
                    ?.getAttribute('content') || '';
                const ogDesc = document.querySelector('meta[property="og:description"]')
                    ?.getAttribute('content') || '';
                const metaDesc = document.querySelector('meta[name="description"]')
                    ?.getAttribute('content') || '';
                return {
                    title: title,
                    brand: ogBrand,
                    ogTitle: ogTitle,
                    description: ogDesc || metaDesc
                };
            }
        """)

        return ProductInfo(
            product_name=page_data.get("ogTitle") or page_data.get("title", ""),
            brand_name=page_data.get("brand", ""),
            description=page_data.get("description", ""),
            claims=[],
        )

    async def _parse_ingredients_with_claude(self, combined_text: str) -> list[Ingredient]:
        """Use Claude to parse all extracted text into structured ingredient list."""
        if not combined_text.strip():
            return []

        # Truncate if too long
        if len(combined_text) > 30000:
            combined_text = combined_text[:30000]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.1,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Below is text extracted from a supplement/health product page "
                        "using multiple extraction strategies. Your job is to identify "
                        "ALL ingredients in this product.\n\n"
                        "Rules:\n"
                        "- Extract every supplement ingredient, vitamin, mineral, herb, "
                        "amino acid, or bioactive compound\n"
                        "- Include amounts and units when available\n"
                        "- Include which source(s) each ingredient was found in\n"
                        "- Deduplicate — if the same ingredient appears in multiple sources, "
                        "merge them into one entry with multiple sources listed\n"
                        "- Exclude inactive ingredients like gelatin capsule, rice flour, "
                        "magnesium stearate, silicon dioxide (fillers/binders)\n"
                        "- Standardize names (e.g., 'Vit D3' → 'Vitamin D3')\n\n"
                        "Also extract:\n"
                        "- Any product CLAIMS (health benefits mentioned)\n\n"
                        "Return ONLY valid JSON in this exact format:\n"
                        "```json\n"
                        "{\n"
                        '  "ingredients": [\n'
                        '    {"name": "...", "amount": "...", "unit": "...", '
                        '"sources": ["source1", "source2"]}\n'
                        "  ],\n"
                        '  "claims": ["claim1", "claim2"]\n'
                        "}\n"
                        "```\n\n"
                        f"Extracted text:\n{combined_text}"
                    ),
                }
            ],
        )

        text = response.content[0].text
        ingredients = self._parse_claude_ingredient_json(text, "combined")

        # Also try to get claims
        try:
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                data = json.loads(json_match.group())
                claims = data.get("claims", [])
                # Store claims somewhere accessible — we'll get them from the result
                self._last_claims = claims
        except Exception:
            self._last_claims = []

        return ingredients

    def _parse_claude_ingredient_json(
        self, text: str, default_source: str
    ) -> list[Ingredient]:
        """Parse Claude's JSON response into Ingredient objects."""
        try:
            # Find JSON in response
            json_match = re.search(r"\{[\s\S]*\}", text)
            if not json_match:
                # Try array format
                json_match = re.search(r"\[[\s\S]*\]", text)
                if json_match:
                    items = json.loads(json_match.group())
                    return [
                        Ingredient(
                            name=item.get("name", ""),
                            amount=item.get("amount"),
                            unit=item.get("unit"),
                            sources=item.get("sources", [default_source]),
                        )
                        for item in items
                        if item.get("name")
                    ]
                return []

            data = json.loads(json_match.group())
            items = data.get("ingredients", data) if isinstance(data, dict) else data
            if not isinstance(items, list):
                return []

            return [
                Ingredient(
                    name=item.get("name", ""),
                    amount=item.get("amount"),
                    unit=item.get("unit"),
                    sources=item.get("sources", [default_source]),
                )
                for item in items
                if item.get("name")
            ]
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to parse ingredient JSON: {e}")
            return []


def merge_ingredients(
    auto: list[Ingredient], manual: list[Ingredient]
) -> list[Ingredient]:
    """Merge auto-extracted and manually-provided ingredients, deduplicating."""
    by_key: dict[str, Ingredient] = {}

    for ing in auto + manual:
        key = ing.key()
        if key in by_key:
            existing = by_key[key]
            existing.sources = list(set(existing.sources + ing.sources))
            if not existing.amount and ing.amount:
                existing.amount = ing.amount
                existing.unit = ing.unit
        else:
            by_key[key] = Ingredient(
                name=ing.name,
                amount=ing.amount,
                unit=ing.unit,
                sources=list(ing.sources),
            )

    return list(by_key.values())
