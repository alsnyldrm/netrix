"""Model images from approved manufacturer and product-image hosts."""

import re

from sqlalchemy import func, select, tuple_

from .. import models as m

IMAGE_HOSTS = ("assets.ext.hpe.com", "www.fortinet.com", "cdn.blueally.com")
SOURCE_HOSTS = ("assets.ext.hpe.com", "www.hpe.com", "buy.hpe.com", "www.fortinet.com", "docs.fortinet.com")

IMAGES = {
    "JL677A": {
        "url": "https://assets.ext.hpe.com/is/image/hpedam/s00009471?bfc=off&fit=fit&fmt=png-alpha&hei=600&wid=800",
        "source": "https://www.hpe.com/jp/ja/product-catalog/networking/networking-switches/pip.options.aruba-6100-switch-series.1013152645.html",
    },
    "JL558A": {
        "url": "https://assets.ext.hpe.com/is/image/hpedam/s00004485?$zoom$=",
        "source": "https://buy.hpe.com/lamerica/es/networking/switches/fixed-port-l3-managed-ethernet-switches/hpe-aruba-networking-2930f-48g-poe-4sfp-740w-switch/p/jl558a",
    },
    "JL675A": {
        "url": "https://assets.ext.hpe.com/is/image/hpedam/s00009458?$zoom$=",
        "source": "https://buy.hpe.com/emea_middle_east/en/networking/switches/fixed-port-l3-managed-ethernet-switches/hpe-aruba-networking-cx-6100-48g-class4-poe-4sfp-370w-switch/p/jl675a",
    },
}


def model_image(db, vendor, model):
    configured = db.scalar(
        select(m.ModelImage).where(
            func.lower(m.ModelImage.vendor) == vendor.lower(), func.lower(m.ModelImage.model) == model.lower()
        )
    )
    if configured:
        return {"url": configured.url, "source": configured.source}
    return fallback_image(vendor, model)


def model_images(db, devices):
    pairs = {(d.vendor.lower(), d.model.lower()) for d in devices}
    configured = (
        {
            (row.vendor.lower(), row.model.lower()): {"url": row.url, "source": row.source}
            for row in db.scalars(
                select(m.ModelImage).where(
                    tuple_(func.lower(m.ModelImage.vendor), func.lower(m.ModelImage.model)).in_(pairs)
                )
            )
        }
        if pairs
        else {}
    )
    return {
        d.id: configured.get((d.vendor.lower(), d.model.lower()), fallback_image(d.vendor, d.model))
        for d in devices
    }


def fallback_image(vendor, model):
    if any(v in vendor.casefold() for v in ("hpe", "hp", "aruba")):
        match = re.search(r"\b(J[A-Z]?\d{3,4}A)\b", model.upper())
        if match:
            return IMAGES.get(match[1])
    return None


def save_image(db, device_id, payload, user):
    from fastapi import HTTPException

    from ..identity.security import audit
    from ..services import get, publish

    device = get(db, m.Device, device_id)
    if not device.vendor.strip() or not device.model.strip():
        raise HTTPException(422, "Önce envanterde üretici ve modeli tanımlayın")
    row = db.scalar(
        select(m.ModelImage).where(
            func.lower(m.ModelImage.vendor) == device.vendor.lower(),
            func.lower(m.ModelImage.model) == device.model.lower(),
        )
    )
    if not row:
        row = m.ModelImage(vendor=device.vendor, model=device.model)
    row.url, row.source = payload.url, payload.source
    db.add(row)
    db.flush()
    audit(db, user, "model_image", "devices", device.id, "Üretici model görseli kaydedildi")
    db.commit()
    publish()
    return {"url": row.url, "source": row.source}
