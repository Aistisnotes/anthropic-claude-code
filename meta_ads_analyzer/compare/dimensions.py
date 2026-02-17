"""Standard dimension constants for comparison analysis."""

from __future__ import annotations

# Hook types (9 types)
ALL_HOOKS = [
    'question',
    'statistic',
    'bold_claim',
    'fear_urgency',
    'story',
    'social_proof',
    'curiosity',
    'direct_address',
    'other',
]

# Angle types (7 types)
ALL_ANGLES = [
    'mechanism',
    'social_proof',
    'transformation',
    'problem_agitate',
    'scarcity',
    'authority',
    'educational',
]

# Emotion types (10 Schwartz values)
ALL_EMOTIONS = [
    'security',
    'achievement',
    'hedonism',
    'stimulation',
    'self_direction',
    'benevolence',
    'conformity',
    'tradition',
    'power',
    'universalism',
]

# Format types (7 types)
ALL_FORMATS = [
    'listicle',
    'testimonial',
    'how_to',
    'long_form',
    'minimal',
    'emoji_heavy',
    'direct_response',
]

# Offer types (8 types)
ALL_OFFERS = [
    'discount',
    'free_trial',
    'guarantee',
    'bonus',
    'free_shipping',
    'bundle',
    'subscription',
    'limited_time',
]

# CTA types (7 types)
ALL_CTAS = [
    'shop_now',
    'learn_more',
    'sign_up',
    'claim_offer',
    'watch',
    'download',
    'contact',
]

# Dimension weights for priority scoring
# Higher weight = more important in competitive analysis
DIMENSION_WEIGHTS = {
    'angles': 4,      # Most important (strategic positioning)
    'hooks': 3,       # High importance (attention capture)
    'emotions': 3,    # High importance (psychological triggers)
    'formats': 2,     # Medium importance (execution style)
    'offers': 2,      # Medium importance (conversion mechanics)
    'ctas': 1,        # Lower importance (final action)
}
