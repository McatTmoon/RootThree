from pathlib import Path
import yaml
from django.conf import settings

_COMPAT_CACHE = None


def get_compat_data():
    global _COMPAT_CACHE
    if _COMPAT_CACHE is None:
        compat_path = settings.BASE_DIR / "participant_kit" / "compat.yaml"
        if compat_path.exists():
            with open(compat_path, "r", encoding="utf-8") as f:
                _COMPAT_CACHE = yaml.safe_load(f)
        else:
            _COMPAT_CACHE = {}
    return _COMPAT_CACHE


def is_compatible(donor_group, recipient_group, product):
    """
    Check if a donor blood group is compatible with a recipient blood group
    for a given product according to the official BloodNet compatibility rules.
    """
    data = get_compat_data()
    product_compat = data.get(product, {})
    allowed_groups = product_compat.get(recipient_group, [])
    return donor_group in allowed_groups
