import re

TYPES = [
    "printer_equipment_and_supplies",
    "networking_and_surveillance",
    "camera_and_optics",
    "computer_hardware_and_storage",
    "watches",
    "audio",
    "phones_wearables_and_accessories",
    "cycling_parts",
    "ram_mounts",
    "home_furniture_and_appliances",
    "apparel_and_footwear",
    "consumables_and_personal_care",
    "media_and_collectibles",
    "other",
]


def type_of(r: dict) -> str:
    text = " ".join(
        str(r.get(k) or "") for k in ("title", "brand", "description")
    ).casefold()

    def hit(pattern: str) -> bool:
        return re.search(pattern, text, re.IGNORECASE) is not None

    if hit(
        r"\b(?:inkjet|laserjet|thermal printer|printer|toner|ink cartridge|"
        r"transfer belt|transfer unit|ultrachrome|label(?:ling)? tape|"
        r"printer ribbon|monochrome ribbon|prints per roll|"
        r"pgi[- ]?\d|pfi[- ]?\d|c13t\d|lc[- ]?\d|106r\d|x950x\w+)\b"
    ):
        return "printer_equipment_and_supplies"

    if hit(
        r"\b(?:cisco catalyst|ws-c\d|ubiquiti|unifi|eap(?:110|115|225)|"
        r"tl-sg\d|t1700g|access point|gigabit (?:ethernet )?switch|"
        r"managed switch|network switch|wi-?fi repeater|poe switch|"
        r"ip camera|cctv|hikvision|turbohd|\d+-channel (?:dvr|nvr)|"
        r"\bdvr\b|\bnvr\b|uvc-g[34])"
    ):
        return "networking_and_surveillance"

    if hit(
        r"\b(?:ram mounts?|ram mount|ram-b-|rap-b-|rap-\d|"
        r"x-grip|tough-claw|double socket arm|suction cup base|"
        r"u-bolt mount|ball bases?|ball connector)\b"
    ):
        return "ram_mounts"

    if hit(
        r"\b(?:mirrorless|digital camera|camera body|dslr|rebel sl\d|"
        r"alpha a\d|alpha 7|a7[rs]?\s*(?:iii|iv)|fujifilm xf|"
        r"nikkor|nikon af-s|canon (?:rf|ef)|sigma \d+mm|"
        r"\d+(?:-\d+)?mm f/?\d|lens|tripod|gimbal|zenmuse|"
        r"instax|instant film|manfrotto|gopro|hero[4-9]|atem)\b"
    ):
        return "camera_and_optics"

    if hit(
        r"\b(?:watch|montre|zegarek|uhr|chronograph|quartz movement|"
        r"automatic men's|automatic mens|seiko prospex|tag heuer|"
        r"tissot|panerai|daniel wellington|swiss military hanowa|"
        r"seamaster|forerunner|vivoactive|eco-?drive|pam\d{5}|"
        r"dw\d{8}|waz\d|war\d|spb\d|sne\d|srpa\d)\b"
    ):
        return "watches"

    if hit(
        r"\b(?:headphones?|headsets?|earphones?|earbuds?|airpods|"
        r"soundlink|noise[- ]cancell|jabra (?:evolve|biz)|"
        r"logitech h1\d{2}|wh-?1000xm|mdr-ex|hesh \d|"
        r"bowers\s*&\s*wilkins pi\d|stereo headset)\b"
    ):
        return "audio"

    if hit(
        r"\b(?:smartphone|redmi|xiaomi note|powerbank|power bank|"
        r"wireless charging case|charging case for airpods|"
        r"replacement band|phone mount|phone/phablet|"
        r"xbox one controller|wireless controller)\b"
    ):
        return "phones_wearables_and_accessories"

    if hit(
        r"\b(?:shimano|sram|park tools?|parktool|maxxis|"
        r"rear derailleur|front derailleur|bike chain|chain wear|"
        r"bicycle cassette|disc brake pads?|disc rotor|"
        r"clipless road pedal|spd pedals?|bicycle tyre|bicycle tire|"
        r"minion dhr|high roller ii|assegai|rekon)\b"
    ):
        return "cycling_parts"

    if hit(
        r"\b(?:core i[3579][ -]?\d|athlon|processor|cpu\b|"
        r"geforce|radeon|gtx \d|rtx \d|graphics card|motherboard|"
        r"\bddr[34]l?\b|so-?dimm|udimm|vengeance lpx|hyperx fury|"
        r"\bssd\b|hard drive|\bhdd\b|solid state drive|"
        r"usb flash drive|pendrive|datatraveler|cruzer|"
        r"sdxc|sdhc|microsd|compactflash|memory card|"
        r"computer case|mid[- ]tower|cpu cooler|case fan|"
        r"webcam|monitor|signage display|wireless desktop|"
        r"keyboard|gaming mouse|mouse pad|smart-ups|\bups\b|"
        r"replacement battery cartridge|magsafe|privacy filter)\b"
    ):
        return "computer_hardware_and_storage"

    if hit(
        r"\b(?:oven|microwave|ceiling fan|grill|grill cart|"
        r"mattress|bedding|cat tree|scratching post|outdoor furniture|"
        r"dining set|sofa lounge|storage box|basin|table|"
        r"floral foam|light bulb|trubice|garland)\b"
    ):
        return "home_furniture_and_appliances"

    if hit(
        r"\b(?:t-?shirt|cap\b|baseball cap|jacket|coat|bomber|"
        r"shoe|shoes|sandal|swimsuit|bathing suit|bra\b|"
        r"vans old skool|salomon speedcross|new era nfl|visor)\b"
    ):
        return "apparel_and_footwear"

    if hit(
        r"\b(?:softgels?|supplement|coq10|ubiquinol|pre-workout|"
        r"bcaa|shampoo|cosmetic|loreal|ink? chromative|"
        r"whisky|whiskey|oolong tea|chocolate bar|isomalt|"
        r"dog shampoo|mg,\s*\d+\s*softgels|servings?)\b"
    ):
        return "consumables_and_personal_care"

    if hit(
        r"\b(?:pokemon|pokémon|trainer box|booster|trading card|"
        r"criterion collection|publication date|paperback|book\b|"
        r"foil\)|magic: the gathering|notebook refill|"
        r"traveler'?s (?:notebook|refills?)|lined refill|sketch refill)\b"
    ):
        return "media_and_collectibles"

    return "other"


CARDS = {
    "printer_equipment_and_supplies": """IDENTIFIES: Exact manufacturer part number, such as 106R03624, 800033-801, C13T079340A0, LC-1100BK or PFI-1000Y, is decisive when consistent with the brand. Otherwise require printer family plus supply type, colour and yield.
HARMLESS: Language, compatible-printer lists, OEM/genuine wording, punctuation, page-count formatting, retailer text, missing price and currency differences.
VARIANT: Colour, standard/high/extra-high yield, cartridge versus multipack, pack count, ribbon panel type, tape width/length, printer model, OEM versus compatible, and refurbished status.
SAME MEANS: The same printer device or the same exact supply SKU, colour, yield and package configuration.""",

    "networking_and_surveillance": """IDENTIFIES: Exact model codes such as WS-C2960X-24TS-L, EAP225, TL-SG105E, UVC-G4-PRO or DS-7208HUHI-K2-P are decisive. Without a code, require brand, product family, port/channel count and defining PoE, radio or camera specifications.
HARMLESS: Language, rack-mount wording, expanded protocol names, omitted speeds, retailer descriptions, price and formatting.
VARIANT: Port count, PoE support or budget, uplink type, software/license tier, indoor versus outdoor, camera generation, resolution, lens, storage, included injector, and single versus multipack.
SAME MEANS: The same network or surveillance model in the same hardware, licensing and package configuration.""",

    "camera_and_optics": """IDENTIFIES: Camera or lens model code is decisive, including a7S III, SEL2470Z, XF 8-16mm, RF 85mm F1.2 or AJDBD-001. Otherwise require brand plus body/lens family, focal length, aperture and mount; kits also require included lens or accessory.
HARMLESS: Language, spacing in focal lengths, “body only” synonyms, warranty wording, marketing copy, price and minor punctuation.
VARIANT: Body generation, sensor model, lens mount, focal range, aperture, colour, kit versus body-only, included lens/battery, film format, frame style, shot count and refurbished condition.
SAME MEANS: The same camera, optic, film pack or camera accessory in the same model and bundle.""",

    "computer_hardware_and_storage": """IDENTIFIES: Exact manufacturer model or part number is decisive. Otherwise require family plus key specifications: CPU number; GPU chip and board edition; RAM capacity/type/speed/layout; or storage line, capacity, interface and form factor.
HARMLESS: Language, reordered specifications, decimal versus TB/GB notation, omitted benchmark speeds, retailer wording, price and cosmetic formatting.
VARIANT: Capacity, memory generation/speed/ECC/layout, CPU suffix, GPU chip/VRAM/OC edition, storage interface/form factor, monitor size, case colour, cooler size, regional power version, bundle and refurbished status.
SAME MEANS: The same hardware SKU with the same capacity, performance-defining suffixes, form factor and package contents.""",

    "watches": """IDENTIFIES: A reference number such as PAM00687, T109.210.22.031.00, DW00100006, WAZ111A.BA0875 or SPB103J1 is decisive when brand-compatible. Otherwise require brand, collection, movement, case size, dial and strap or bracelet.
HARMLESS: Language, punctuation in reference numbers, “men’s/ladies” wording, translated colour names, price, warranty text and reordered specifications.
VARIANT: Reference number, movement, case size/material, dial colour, strap or bracelet, complication, edition, authenticity, and replica/copy status. A replacement band is not the watch.
SAME MEANS: The same authentic watch reference and configuration, or the same separately sold watch accessory.""",

    "audio": """IDENTIFIES: Exact model code or named model, such as Jabra Evolve 20 MS Stereo, WH-1000XM3B, PI3 or Logitech 981-000589, is decisive. Otherwise require brand, series, wearing style and connection type.
HARMLESS: Language, “headset” versus “headphones,” expanded Bluetooth or noise-cancelling claims, colour omission, price and retailer prose.
VARIANT: Mono versus stereo, wired versus wireless, USB/QD/3.5 mm connector, UC/MS certification, generation, colour when sold separately, charging stand or case inclusion, and renewed condition.
SAME MEANS: The same audio model in the same connectivity, headset layout, colour and bundle configuration.""",

    "phones_wearables_and_accessories": """IDENTIFIES: Exact phone or accessory model code is decisive. For phones without codes, require brand, model name, generation, RAM, storage, colour and SIM configuration. Accessories require intended device plus accessory type.
HARMLESS: Language, reordered RAM/storage, translated colours, carrier marketing, price, warranty wording and omitted common compatibility details.
VARIANT: Pro/T/Plus suffix, generation, RAM, storage, colour, SIM count, region, phone versus case, wired versus wireless charging case, battery inclusion, compatible device generation and refurbished condition.
SAME MEANS: The same phone configuration or the same separately sold wearable/mobile accessory and bundle.""",

    "cycling_parts": """IDENTIFIES: Manufacturer part or series code is strongest; otherwise require brand, component family and fit specifications, such as derailleur cage/speed, pedal model, rotor diameter, or tyre diameter, width, compound and casing.
HARMLESS: Language, inch-symbol formatting, DHR2 versus DHR II, marketing claims, folded/folding wording, price and reordered specifications.
VARIANT: Wheel diameter, tyre width, compound, casing, tubeless readiness, brake material, rotor diameter, drivetrain speed, cage length, pedal mechanism, colour and front/rear designation.
SAME MEANS: The same bicycle component model with the same dimensions, compatibility and performance construction.""",

    "ram_mounts": """IDENTIFIES: RAM/RAP part numbers such as RAM-B-149ZU or RAP-B-400U are decisive. Without one, require component type, ball size, arm length, base or clamp type and included holder.
HARMLESS: RAM versus RAM Mounts branding, inch versus 25 mm notation, language, trademark symbols, unpacked wording, price and descriptive prose.
VARIANT: B/C/D ball size, arm length, suction/U-bolt/Tough-Claw base, rail diameter, phone cradle size, number of balls, material and complete kit versus individual component.
SAME MEANS: The same RAM mounting part or kit with identical geometry, ball system and included components.""",

    "home_furniture_and_appliances": """IDENTIFIES: Exact appliance or furniture model is decisive, such as HBG634BS1B or BLZ-4LTE-NG. Otherwise require brand, product form, dimensions/capacity, fuel or power type, material and set composition.
HARMLESS: Language, centimetre/inch conversions, assembly and lifestyle copy, minor rounded measurements, price, delivery wording and missing colour when the model fixes it.
VARIANT: Dimensions, capacity, gas type, colour, material, mattress size/construction, furniture piece count, built-in versus cart, appliance generation and included pedestal, cover or accessories.
SAME MEANS: The same appliance or home furnishing model in the same size, finish, operating type and set composition.""",

    "apparel_and_footwear": """IDENTIFIES: Brand plus named style is required; a style/SKU code is decisive when available. Size, colour and intended wearer must corroborate because many sampled titles name only the design.
HARMLESS: Language, word order, gendered marketing synonyms, retailer prose, price and minor colour-name translation.
VARIANT: Size, width, colour, material, fit, adult versus junior, team/logo, garment type, season or edition, and multipack count. Visually similar styles from the same brand remain different.
SAME MEANS: The same sellable apparel or footwear style in the same size, colour, fit and licensed design.""",

    "consumables_and_personal_care": """IDENTIFIES: Brand and exact formula/flavour are required; a product code is decisive if present. Strength, net quantity, serving count and package count must agree. Alcohol additionally requires label, type and bottle volume.
HARMLESS: Language, reordered ingredients, health claims, decimal comma, unit conversion, serving-description wording, price and packaging prose.
VARIANT: Formula, flavour, strength, dosage, volume/weight, serving or capsule count, scent, vintage or label, dietary certification, and single versus multipack.
SAME MEANS: The same consumable formula or beverage in the same strength, flavour, quantity and retail pack.""",

    "media_and_collectibles": """IDENTIFIES: Exact work, set or product number is strongest. Books require title and edition/format; trading products require franchise, expansion and product form; notebook refills require numbered refill and paper type.
HARMLESS: Language, subtitle punctuation, publisher marketing, capitalization, price, release-date formatting and omitted creator when title and edition agree.
VARIANT: Edition, release, format, language when content differs, foil status, card printing, expansion, booster versus trainer box, sheet or pack count, film restoration, disc count and numbered refill type.
SAME MEANS: The same published edition, collectible printing or stationery refill in the same format and package.""",

    "other": """IDENTIFIES: Prefer an exact manufacturer model, catalogue number or clearly unique branded product name. Without a code, require agreement on brand, object type, dimensions, material, compatibility and package contents; retailer SKUs alone are not decisive.
HARMLESS: Language, word order, generic marketing, punctuation, unit formatting, missing descriptions, price and currency.
VARIANT: Size, capacity, colour, material, model suffix, compatibility, edition, pack count, included accessories, personalization, condition, replica status and digital coupon versus physical product. Real estate requires the same lot/address, not merely similar wording.
SAME MEANS: The same specifically configured thing offered for sale, not merely the same broad product family."""
}
