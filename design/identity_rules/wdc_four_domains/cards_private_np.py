import re

TYPES = [
    "watch",
    "footwear",
    "camera",
    "camera_accessory",
    "storage_memory",
    "computer_component",
    "computer_system",
    "networking",
    "other",
]


def type_of(r: dict) -> str:
    title = str(r.get("title") or "").lower()
    brand = str(r.get("brand") or "").lower()
    desc = str(r.get("description") or "").lower()
    text = " ".join((title, brand, desc))

    def has(pattern: str, source: str = text) -> bool:
        return re.search(pattern, source, re.I) is not None

    if has(
        r"\b(?:watch|watches|smartwatch|timepiece|chronometer|chronograph|"
        r"menswatch|damenuhr|herrenuhr|reloj|uhren?|horloge|wrist[- ]?watch|"
        r"gps running watch|activity tracker)\b",
        title,
    ):
        return "watch"

    if has(
        r"\b(?:shoe|shoes|sneaker|sneakers|trainer|trainers|boot|boots|"
        r"cleat|cleats|football boots|soccer|running shoes?|footwear|"
        r"scarpe|chaussures?|zapatillas?|botas|slippers?|moccasins?)\b",
        title,
    ):
        return "footwear"

    if has(
        r"\b(?:sdxc|sdhc|microsd|micro sd|secure digital|compact flash|"
        r"flash memory card|memory card|usb flash|thumb drive|datatraveler|"
        r"\bssd\b|solid state drive|\bhdd\b|hard drive|hard disk|"
        r"\b(?:ddr[2-9]|sdram|sodimm|so-dimm|dimm|rdimm|udimm)\b|"
        r"ram(?:/memory)?|memory kit)\b",
        title,
    ):
        return "storage_memory"

    primary_camera = has(
        r"\b(?:digital camera|dslr|mirrorless|point\s*&?\s*shoot|"
        r"instant camera|film camera|action camera|body camera|camcorder|"
        r"webcam|web camera|document camera|surveillance camera|"
        r"security camera|network camera|ip camera|camera system|"
        r"camera body|body only)\b",
        title,
    )
    accessory = has(
        r"\b(?:lens|telephoto|zoom lens|camera case|camera bag|gadget bag|"
        r"carrying case|battery|charger|remote controller|remote control|"
        r"mount|harness|grip|tripod|video head|light|led panel|"
        r"film pack|instant film|screen|touch pad|adapter|speed booster|"
        r"viewfinder|rucksack|backpack)\b",
        title,
    )
    if accessory and not primary_camera:
        return "camera_accessory"

    if primary_camera or has(
        r"\b(?:powershot|lumix|eos|camera kit|cloud camera|dome camera|"
        r"cctv|photo scanner|image scanner|document scanner)\b",
        title,
    ):
        return "camera"

    if has(
        r"\b(?:processor|cpu|graphics card|video card|geforce|radeon|"
        r"motherboard|mainboard|server adapter|sound card|chassis|"
        r"computer case|mid tower|full tower|mini[- ]itx case|"
        r"replacement light|projector lamp|cooler)\b",
        title,
    ):
        return "computer_component"

    if has(
        r"\b(?:ethernet switch|network switch|desktop switch|router|"
        r"network adapter|gigabit adapter|\d+[- ]port .*switch|"
        r"smart home security kit|security starter kit|starter pack)\b",
        title,
    ):
        return "networking"

    if has(
        r"\b(?:desktop computer|laptop|notebook|tablet|ipad|imac|mac mini|"
        r"macbook|workstation|\bnuc\b|mini pc|microbox|barebone|"
        r"server\b|ultrabook)\b",
        title,
    ):
        return "computer_system"

    return "other"


CARDS = {
    "watch": """(a) IDENTIFIES: Brand plus the exact manufacturer reference or model code is decisive when repeated consistently. Without a code, collection/model name, movement or functions, case size, audience and materials must corroborate.
(b) HARMLESS: Shop wording, language, punctuation, omitted brand, generic luxury prose, price, seller location and reordered names are harmless. “Men’s watch,” “timepiece,” and translated equivalents may vary.
(c) VARIANT: Different reference codes, collection/model names, case sizes, dial or case colours, strap/material, movement, radio/GPS functions and band size are different entities. Similar template descriptions alone prove nothing.
(d) SAME MEANS: The same specific watch reference and configured colour, material, size and movement.""",

    "footwear": """(a) IDENTIFIES: A style/SKU code is decisive, especially with matching model. Otherwise require brand, model and generation plus corroborating gender/age, surface type and colourway.
(b) HARMLESS: Language, retailer category wording, word order, punctuation, translated colours, abbreviated brand, missing description and generic performance prose are harmless.
(c) VARIANT: Model number or generation, style code, colourway, men/women/junior designation, FG/SG/AG/HG or other ground type, low/mid form and material edition create different entities. Retail shoe size is an offer option unless embedded as a distinct model.
(d) SAME MEANS: The same footwear model, generation, audience, surface construction and colourway.""",

    "camera": """(a) IDENTIFIES: Exact camera model or manufacturer code is decisive with the camera family. For surveillance products, the model code identifies the camera or system. Otherwise require brand, model line and major specifications.
(b) HARMLESS: Language, retailer text, price, used/refurbished wording, reordered specifications, omitted brand and generic photographic prose are harmless.
(c) VARIANT: Different body model, generation or model suffix is different. Body-only versus a named lens kit, different included lens, single camera versus multi-camera system, resolution edition, colour edition and materially different kit contents are variants.
(d) SAME MEANS: The same camera body or surveillance-system model with the same included kit configuration.""",

    "camera_accessory": """(a) IDENTIFIES: Manufacturer accessory code is decisive. Otherwise use brand plus accessory model, accessory class and compatibility; lenses additionally require mount, focal range and aperture.
(b) HARMLESS: Translation, retailer wording, price, formatting, omitted compatibility lists and reordered technical details are harmless. Generic “for camera” language adds little.
(c) VARIANT: Different accessory code, lens focal length/aperture/mount, battery type, case model or size, film format/count, charger configuration, mount type and bundled quantity are different entities. Visually similar generic mounts are not automatically identical.
(d) SAME MEANS: The same accessory model for the same interface or compatibility family and the same pack configuration.""",

    "storage_memory": """(a) IDENTIFIES: Exact manufacturer part number is decisive. Otherwise require product family, medium type, capacity and interface, corroborated by speed/class, form factor, RPM, memory generation or kit layout.
(b) HARMLESS: Price, retailer stock code, language, OEM/B-grade/refurbished condition, punctuation, packaging prose and rounded interface wording are harmless when the manufacturer part number agrees.
(c) VARIANT: Capacity, card speed class, read-speed edition, HDD/SSD medium, interface, form factor, RPM, RAM generation/frequency/timings, module count and per-module capacity are different entities. Similar family names do not override these differences.
(d) SAME MEANS: The same storage or memory part number and capacity/performance configuration.""",

    "computer_component": """(a) IDENTIFIES: Exact CPU, GPU, motherboard, case or adapter part number is decisive. Otherwise require maker, model/chipset and component class, with clock, socket, memory amount or board revision as corroboration.
(b) HARMLESS: Retailer IDs, country/site suffixes, price, language, boxed/retail wording, B-grade condition, omitted specifications and reordered feature lists are harmless.
(c) VARIANT: Processor model, socket, core model, GPU chipset or VRAM, motherboard revision/chipset, case model/colour, adapter model and bundled cooler are variants. Shared family names or near-identical specification templates do not establish identity.
(d) SAME MEANS: The same component model or manufacturer part number with the same hardware configuration.""",

    "computer_system": """(a) IDENTIFIES: A manufacturer configuration/part code is decisive. Otherwise require system family and generation plus processor, RAM, storage, screen size and connectivity configuration.
(b) HARMLESS: Retailer wording, language, price, open-box/used/refurbished status, colour-name translation and omitted generic features are harmless.
(c) VARIANT: Different configuration code, processor tier, RAM, storage capacity/type, display size, cellular versus Wi-Fi, generation, graphics option and included operating configuration create different entities. Similar chassis or family names are insufficient.
(d) SAME MEANS: The same computer or tablet model in the same hardware and connectivity configuration.""",

    "networking": """(a) IDENTIFIES: Exact switch, router, adapter or smart-home kit model code is decisive. Otherwise require brand, product family, device class and port or bundle configuration.
(b) HARMLESS: Language, retailer title additions, price, reordered protocol details, omitted brand and translated smart-home descriptions are harmless.
(c) VARIANT: Port count, Ethernet speed, managed versus unmanaged form, wireless generation, hardware revision and kit contents are different entities. A starter kit is distinct from an add-on camera, sensor or hub.
(d) SAME MEANS: The same networking or smart-home model with the same hardware revision, port layout and bundle contents.""",

    "other": """(a) IDENTIFIES: Prefer an exact manufacturer reference, SKU or clearly repeated model code. Without one, require matching brand, product class, model name and multiple distinctive attributes; generic or masked text is not enough.
(b) HARMLESS: Price, shop boilerplate, language, word order, punctuation, missing values, seller codes and generic promotional descriptions are harmless.
(c) VARIANT: Different model/reference codes, product class, dimensions, colour/material edition, pack count or functional configuration indicate different entities. For apparel, garment type and size edition matter; for jewellery, design and reference matter.
(d) SAME MEANS: The same catalogued product model in the same material, size, colour and package configuration."""
}
