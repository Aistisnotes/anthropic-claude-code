"""Product type classification and keyword expansion."""

from meta_ads_analyzer.classifier.keyword_expander import (
    deduplicate_ads_across_keywords,
    generate_related_keywords,
)
from meta_ads_analyzer.classifier.product_type import (
    classify_product_type_batch,
    filter_ads_by_product_type,
    get_dominant_product_type,
)

__all__ = [
    "classify_product_type_batch",
    "get_dominant_product_type",
    "filter_ads_by_product_type",
    "generate_related_keywords",
    "deduplicate_ads_across_keywords",
]
