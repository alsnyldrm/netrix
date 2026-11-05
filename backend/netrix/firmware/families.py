"""Model families and software branches; product sources are in firmware-management.md."""

import re

from .versions import release

FAMILIES = {
    "aruba_5400": "aos_s_54xx",
    "aruba_2900": "aos_s_29xx",
    "aruba_6100": "cx6100",
    "hp_1950": "hp1950",
}
AOS_S_FAMILIES = ("aos_s_54xx", "aos_s_29xx")
BRANCH_FAMILY = {
    "K": "aos_s_54xx",
    "KB": "aos_s_54xx",
    "WB": "aos_s_29xx",
    "WC": "aos_s_29xx",
    "PL": "cx6100",
    "R35": "hp1950",
    "R51": "hp1950",
}
PRODUCTS = {
    "K": "J8697A J8698A J9642A J9643A",
    "KB": "J9821A J9822A J9823A J9824A J9825A J9826A J9850A J9851A J9868A JL001A JL002A JL003A JL095A",
    "WB": "J9726A J9727A J9728A J9729A J9836A",
    "WC": "JL253A JL254A JL255A JL256A JL258A JL259A JL260A JL261A JL262A JL263A JL264A JL319A JL320A JL321A JL322A JL323A JL324A JL557A JL558A JL559A JL692A JL693A R0M67A R0M68A",
    "PL": "JL675A JL676A JL677A JL678A JL679A R9Y04A",
    "R35": "JG960A JG961A JG962A JG963A",
    "R51": "JH295A",
}
MODEL_BRANCH = {model: branch for branch, codes in PRODUCTS.items() for model in codes.split()}


def version_branch(version):
    parsed = release(version)
    return parsed[0] if parsed else None


def model_branch(device):
    model = (device.model or "").upper()
    tokens = set(re.findall(r"[A-Z0-9]+", model))
    branches = {MODEL_BRANCH[token] for token in tokens if token in MODEL_BRANCH}
    family = FAMILIES.get(device.adapter)
    named_branches = {
        branch
        for pattern, branch in (
            (r"\b2920\b", "WB"),
            (r"\b2930[FM]?\b", "WC"),
            (r"\b54(?:00|06|12)R\b", "KB"),
            (r"\b54(?:00|06|12)ZL\b", "K"),
            (r"\b6100\b", "PL"),
            (r"\b1950[ -]+12XGT\b", "R51"),
        )
        if re.search(pattern, model)
    }
    unknown_sku = any(
        token not in MODEL_BRANCH and re.fullmatch(r"(?:J[A-Z]?|R\d|S\d)[A-Z0-9]{3,6}", token)
        for token in tokens
    )
    if (
        unknown_sku
        or len(branches | named_branches) > 1
        or re.search(r"\b(?:2530|2540|3810[MR]?|6000|6200)\b", model)
    ):
        return None
    if len(branches) == 1:
        branch = branches.pop()
        return branch if BRANCH_FAMILY[branch] == family else None
    if branches:
        return None
    # A series such as 6100 or 2930F has one software branch, even before
    # inventory has read its running revision. Catalog can then report the
    # image as available and the current revision as unknown; planning still
    # excludes unknown revisions and never guesses that a device is current.
    if len(named_branches) == 1:
        branch = next(iter(named_branches))
        return branch if BRANCH_FAMILY[branch] == family else None
    # A complete series name can identify hardware when no SKU was stored.
    named = {
        "aos_s_54xx": r"\b54(?:00|06|12)(?:R|ZL2?)?\b",
        "aos_s_29xx": r"\b(?:2920|2930[FM]?)\b",
        "cx6100": r"\b6100\b",
        "hp1950": r"\b1950\b",
    }
    branch = version_branch(device.software_version)
    if named_branches and branch not in named_branches:
        return None
    if family not in named or not re.search(named[family], model):
        return None
    if family == "aos_s_29xx":
        if "2920" in model and branch != "WB" or "2930" in model and branch != "WC":
            return None
    if family == "hp1950" and ("12XGT" in model) != (branch == "R51"):
        return None
    return branch if BRANCH_FAMILY.get(branch) == family else None
