"""Block engine for landing pages (plan §15).

A landing page is an ordered list of typed blocks. The registry below is the
single source of truth shared by:
- the admin editor UI (fetched via GET /api/landing-pages/blocks)
- server-side sanitization on write (unknown types/fields rejected)
- public rendering (product_showcase blocks get their products resolved here)

Field types the editor understands:
  text | textarea | url | color | select | number | lines | csv_ids
`lines` fields hold "a | b | c" rows — parsed client-side for display.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass


@dataclass
class BlockField:
    key: str
    label: str
    ftype: str = "text"
    options: list[str] | None = None
    default: str = ""
    hint: str = ""


BLOCK_REGISTRY: dict[str, dict] = {
    "hero": {
        "label": "Hero banner",
        "fields": [
            BlockField("headline", "Headline"),
            BlockField("subheadline", "Subheadline", "textarea"),
            BlockField("cta_label", "Button label"),
            BlockField("cta_href", "Button link", "text", hint="e.g. /products"),
            BlockField("image", "Background image URL", "url"),
        ],
    },
    "rich_text": {
        "label": "Rich text",
        "fields": [
            BlockField("title", "Title"),
            BlockField("body", "Body", "textarea"),
        ],
    },
    "image_text": {
        "label": "Image + text",
        "fields": [
            BlockField("image", "Image URL", "url"),
            BlockField("title", "Title"),
            BlockField("body", "Body", "textarea"),
            BlockField("image_side", "Image side", "select", options=["left", "right"]),
            BlockField("cta_label", "Button label"),
            BlockField("cta_href", "Button link"),
        ],
    },
    "feature_grid": {
        "label": "Feature grid",
        "fields": [
            BlockField("title", "Title"),
            BlockField("items", "Features", "lines", hint="One per line:  icon | title | text"),
        ],
    },
    "product_showcase": {
        "label": "Product showcase",
        "fields": [
            BlockField("title", "Section title"),
            BlockField("mode", "Pick products by", "select", options=["latest", "category", "selected"]),
            BlockField("category", "Category", "text", hint="Used when mode = category"),
            BlockField("product_ids", "Product IDs", "csv_ids", hint="Comma-separated, used when mode = selected"),
            BlockField("limit", "Max products", "number", default="8"),
        ],
    },
    "testimonials": {
        "label": "Testimonials",
        "fields": [
            BlockField("title", "Title"),
            BlockField("items", "Quotes", "lines", hint="One per line:  name | quote"),
        ],
    },
    "faq": {
        "label": "FAQ",
        "fields": [
            BlockField("title", "Title"),
            BlockField("items", "Q&A", "lines", hint="One per line:  question | answer"),
        ],
    },
    "trust_badges": {
        "label": "Trust badges",
        "fields": [
            BlockField("items", "Badges", "lines", hint="One per line:  icon | label"),
        ],
    },
    "cta": {
        "label": "Call to action",
        "fields": [
            BlockField("title", "Title"),
            BlockField("body", "Body", "textarea"),
            BlockField("cta_label", "Button label"),
            BlockField("cta_href", "Button link", "text", hint="e.g. /products"),
        ],
    },
}


def registry_public() -> list[dict]:
    return [
        {
            "type": btype,
            "label": spec["label"],
            "fields": [asdict(f) for f in spec["fields"]],
        }
        for btype, spec in BLOCK_REGISTRY.items()
    ]


def sanitize_blocks(blocks) -> tuple[list[dict], list[str]]:
    """Validate + normalize a blocks payload. Returns (clean_blocks, errors)."""
    if blocks is None:
        return [], []
    if not isinstance(blocks, list):
        return [], ["blocks must be a list"]

    clean: list[dict] = []
    errors: list[str] = []
    for i, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            errors.append(f"block #{i}: must be an object")
            continue
        btype = raw.get("type")
        if btype not in BLOCK_REGISTRY:
            errors.append(f"block #{i}: unknown type '{btype}'")
            continue
        out: dict = {"id": str(raw.get("id") or uuid.uuid4().hex[:8]), "type": btype}
        for f in BLOCK_REGISTRY[btype]["fields"]:
            val = raw.get(f.key, f.default)
            if f.ftype == "number":
                try:
                    val = int(val) if str(val).strip() != "" else f.default
                except (TypeError, ValueError):
                    val = f.default
            elif val is None:
                val = f.default
            elif not isinstance(val, str):
                val = str(val)
            out[f.key] = val
        clean.append(out)
    return clean, errors


def resolve_blocks(db, blocks: list[dict]) -> list[dict]:
    """Prepare blocks for public rendering.

    Mutates a deep copy: product_showcase blocks get a `products` list of
    public-safe product cards (supplier identity and costs never leak — §9).
    """
    from app.storefront.public import public_card  # local import avoids cycle

    resolved = copy.deepcopy(blocks)
    for block in resolved:
        if block.get("type") != "product_showcase":
            continue
        from app.catalog import models as cm

        q = db.query(cm.Product).filter(cm.Product.status == "active")
        ids: list[int] = []
        for part in str(block.get("product_ids") or "").split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        mode = block.get("mode") or "latest"
        if mode == "selected" and ids:
            rows = [db.get(cm.Product, pid) for pid in ids]
            rows = [r for r in rows if r and r.status == "active"]
        elif mode == "category" and block.get("category"):
            q = q.filter(cm.Product.category == block["category"])
            rows = q.order_by(cm.Product.id.desc()).all()
        else:
            rows = q.order_by(cm.Product.id.desc()).all()
        try:
            limit = max(1, min(12, int(block.get("limit") or 8)))
        except (TypeError, ValueError):
            limit = 8
        block["products"] = [public_card(db, p) for p in rows[:limit]]
    return resolved
