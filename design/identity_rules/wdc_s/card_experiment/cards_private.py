TYPES = [
    "printer_supply",
    "watch",
    "network_equipment",
    "storage_memory",
    "computer_component",
    "camera_optics",
    "audio",
    "mobile_phone",
    "power_equipment",
    "display",
    "mounting_hardware",
    "cycling",
    "home_garden",
    "pet_product",
    "apparel",
    "food_supplement",
    "games_media_stationery",
    "other",
]


def type_of(r: dict) -> str:
    import re

    title = str(r.get("title") or "").lower()
    description = str(r.get("description") or "").lower()
    brand = str(r.get("brand") or "").lower()
    text = " ".join((title, brand, description))

    def has(pattern, value=text):
        return re.search(pattern, value, re.I) is not None

    if has(
        r"\b(toner|ink cartridge|ink module|inkjet canister|printer ribbon|"
        r"monochrome ribbon|resin ribbon|colour ribbon|color ribbon|"
        r"ultrachrome\b.*\bink|inkpatroon|printer tape)\b"
    ) or (has(r"\b(magenta|cyan|yellow|black)\b", title) and
          has(r"\b(cartridge|toner|printer|ink)\b", title)):
        return "printer_supply"

    if has(
        r"\b(watch|chronograph|chrono\b|timepiece|timer\b|clock\b|"
        r"forerunner|prospex|carrera|automatic quartz|quartz chronograph)\b"
    ) or has(r"\b\d{2,3}\s*mm\b.*\b(dial|movement|case)\b"):
        return "watch"

    if has(
        r"\b(ethernet switch|network switch|managed switch|smart switch|"
        r"poe switch|gigabit switch|access point|wireless router|desktop router|"
        r"network hub|access node|wi-?fi repeater|jetstream|catalyst|unifi)\b"
    ) and not has(r"\b(camera|video camera|protect\s+[ghk]\d)\b", title):
        return "network_equipment"

    if has(
        r"\b(smart-?ups|ups\b|inverter/?charger|power inverter|"
        r"replacement battery cartridge|power adapter|power adaptor|"
        r"battery charger|charging case|charging dock|power dock|"
        r"dual cell charger|dual battery charger)\b"
    ) and not has(r"\b(camera|camcorder|gopro|rover\d|volt\s*\d)\b", text):
        return "power_equipment"

    if has(
        r"\b(mirrorless|dslr|digital camera|video camera|cctv|webcam|"
        r"camview|camera body|camera with|bullet camera|protect camera|"
        r"stabilized camera|zenmuse|instant film|film pack|"
        r"\d+(?:-\d+)?\s*mm\s+f/?\d|lens\b|telephoto|macro lens|zoom lens)\b"
    ):
        return "camera_optics"

    if has(
        r"\b(headphones?|earphones?|earbuds?|headsets?|eargear|soundbuds|"
        r"airpods?|skypods?|noise cancell?ing|stereo headset|mono qd|"
        r"charging pod)\b"
    ):
        return "audio"

    if has(r"\b(smartphone|mobile phone|dual sim|redmi note)\b"):
        return "mobile_phone"

    if has(
        r"\b(ssd|solid state|hard drive|hdd|nas drive|external drive|"
        r"internal drive|mobile drive|portable drive|flash drive|pendrive|"
        r"usb flash|memory card|microsd|micro sd|sdhc|sdxc|compactflash|"
        r"\bcf memory|data tape|binary data tape)\b"
    ):
        return "storage_memory"

    if has(
        r"\b(cpu|processor|core i[3579]|graphics card|geforce|radeon|"
        r"\b[gr]tx\s*\d|ddr[345]|so-?dimm|udimm|desktop memory|memory ram|"
        r"motherboard|atx motherboard|computer case|mid[- ]tower|"
        r"cpu cooler|liquid cooling|case fan|pwm fan|gaming mouse|"
        r"mouse pad|desktop keyboard|keyboard with)\b"
    ):
        return "computer_component"

    if has(
        r"\b(monitor|billboard panel|lcd panel|led panel|privacy filter|"
        r"screen protector|screenguard|laptop lcd screen|display panel)\b"
    ):
        return "display"

    if has(
        r"\b(ram-[a-z0-9]|rap-[a-z0-9]|x-grip|y-grip|tough-claw|"
        r"suction cup base|socket arm|socket brace|ball adapter|"
        r"ball connector|clamp base|v-bolt base|rail mount|handlebar rail mount|"
        r"gripbar|mounting base|twin socket|triple socket|bracket to rods)\b"
    ):
        return "mounting_hardware"

    if has(
        r"\b(rear derailleur|shifter|bicycle cassette|bike chain|"
        r"chain wear indicator|clipless road pedal|mtb pedals?|cycling pedal|"
        r"disc brake pads|tubeless ready|bicycle tire|bike tire|"
        r"minion dhr|high roller|assegai)\b"
    ):
        return "cycling"

    if has(
        r"\b(oven|ceiling fan|grill|burner|garden furniture|dining set|"
        r"sofa lounge|storage crate|mattress|bedframe|table\b|trolley|"
        r"outdoor seating|heater ring|pressunit)\b"
    ):
        return "home_garden"

    if has(
        r"\b(cat tree|scratching post|scratcher|dog chewing|dog tower|"
        r"pup tower|petal foam|dog shampoo|pet product)\b"
    ):
        return "pet_product"

    if has(
        r"\b(t-?shirt|dress\b|jacket|slippers|corset|covering suit|"
        r"\bcap\b|adjustable cap|nfl hat|headwear|sunglasses|oxford\b)\b"
    ):
        return "apparel"

    if has(
        r"\b(capsules?|softgels?|dietary supplement|nutrition product|"
        r"cellular aid|palmetto|vitamin|nougat|whisky|scotch|walker\s+\d|"
        r"ready-tempered|drink\b)\b"
    ):
        return "food_supplement"

    if has(
        r"\b(trainer box|trainer pack|fighter pack|card game|tcg|"
        r"collectible card|drawing journal|notebook refill|lined refill|"
        r"traveler'?s notebook|journal refill|archive\b|release date|"
        r"book\b|voucher tokens?)\b"
    ):
        return "games_media_stationery"

    return "other"


CARDS = {
    "printer_supply": """IDENTIFIES: Manufacturer plus exact cartridge, ribbon, tape, or module code is decisive; printer-family compatibility, colour, yield, and genuine/generic status corroborate. A code printed only in compatibility prose needs brand and supply type.
HARMLESS: Language, “ink module” versus “cartridge,” reordered compatibility lists, punctuation, missing yield, retailer claims, and price.
VARIANT: Colour, standard/high/extra-high yield, capacity, cartridge code, multipack count, genuine versus compatible/remanufactured, and ribbon panel composition.
SAME MEANS: The same sellable printing consumable, with the same code, colour, yield class, authenticity class, and pack configuration.""",

    "watch": """IDENTIFIES: Exact reference number is decisive when paired with the maker or clearly named collection. Otherwise require brand, collection/model, movement type, dial description, case size, and intended wearer. Replica wording is identity-critical.
HARMLESS: “Watch,” “timer,” or “clock” wording, language, reordered specifications, retailer prose, missing dimensions, and price.
VARIANT: Reference suffix, dial or case colour, case size, strap/bracelet, movement, complications, edition, gendered size, authentic versus replica, and watch versus replacement strap.
SAME MEANS: The same watch reference and physical configuration, including authenticity status, as sold.""",

    "network_equipment": """IDENTIFIES: Exact switch, router, access-point, or hub model/part number is decisive. Without it, require brand, product family, port count/type, PoE class, speed, and management/rack format.
HARMLESS: “Port” versus “gate,” translated networking terms, punctuation, software marketing, omitted minor specifications, and price.
VARIANT: Model suffix, port count, uplink type, PoE support/budget, managed status, regional or software edition, included power supply, and standalone versus bundle.
SAME MEANS: The same network-device SKU with the same hardware and included configuration.""",

    "storage_memory": """IDENTIFIES: Maker and exact part number are decisive. Otherwise require product line, medium/form factor, capacity, interface, and speed class; these noisy records may contain implausible capacities, which must still be treated literally when consistently stated.
HARMLESS: GB/TB formatting, language, marketing speed prose, reordered interface terms, missing benchmark values, and price.
VARIANT: Capacity, HDD/SSD/flash/tape medium, form factor, connector/interface, RPM, SD/CF class, endurance line, colour when encoded in the line, pack count, and bundled adapter.
SAME MEANS: The same storage-media SKU with identical capacity, format, interface, performance tier, and bundle.""",

    "computer_component": """IDENTIFIES: Exact manufacturer part number or processor/GPU/motherboard/case model is decisive. For RAM, require line, total capacity, module count, DDR generation, speed, form factor, and ECC status. For cooling/cases, require model and size.
HARMLESS: Clock rounding, reordered specifications, translated component names, omitted latency or connector details, retailer branding errors, and price.
VARIANT: Chip/model suffix, generation, memory capacity and kit count, speed, ECC, form factor, overclock edition, case colour, fan size/count, socket support, and included accessories.
SAME MEANS: The same component SKU and retail kit, not merely the same chipset or product family.""",

    "camera_optics": """IDENTIFIES: Camera or lens maker plus exact model/reference is decisive. Otherwise use body generation, mount, focal length/aperture, stabilization and lens suffixes. For film or surveillance cameras, model, format, image count, and pack count identify the offer.
HARMLESS: “Body only” word order, warranty wording, translated optical terms, rounded dimensions, omitted descriptive specifications, and price.
VARIANT: Body generation, sensor/model suffix, lens mount, focal range, aperture, stabilization, colour, body-only versus lens kit, included battery/charger, film format/count, and camera pack count.
SAME MEANS: The same camera, lens, film, or camera-accessory SKU with the same kit contents.""",

    "audio": """IDENTIFIES: Brand and exact headset, headphone, earbud, or charging-case model are decisive. Otherwise require product line, wearing style, wired/wireless connection, channel format, platform certification, and colour.
HARMLESS: Headphone/headset terminology, language, noise-cancellation marketing, reordered connectivity details, missing battery-life claims, and price.
VARIANT: Model generation, mono/stereo, in-ear/over-ear, wired versus wireless, connector, Microsoft/UC certification, colour, charging-case type, refurbished status, and included stand or power pack.
SAME MEANS: The same audio-device SKU, generation, colour, connectivity, condition, and bundle.""",

    "mobile_phone": """IDENTIFIES: Maker, model name/number, generation, storage, RAM, SIM configuration, and colour together identify a phone; a unique full model code can be decisive alone.
HARMLESS: Language, reordered specifications, screen or camera marketing, rounded dimensions, missing network details, and price.
VARIANT: Model suffix, regional version, storage, RAM, SIM count, network generation, colour, carrier lock, and bundled accessories.
SAME MEANS: The same phone hardware variant and regional/storage/colour configuration as sold.""",

    "power_equipment": """IDENTIFIES: Exact UPS, inverter, battery-cartridge, adapter, charger, or charging-case code is decisive. Otherwise require brand, family, voltage/VA/watt rating, rack size, compatible device family, and included battery count.
HARMLESS: Translated electrical terms, punctuation, rounded wattage, warranty prose, omitted connector lists, and price.
VARIANT: Capacity, voltage, rack height, regional plug, battery-cartridge number, connector, compatible generation, charger-only versus charger-plus-battery, battery count, and wired versus wireless charging case.
SAME MEANS: The same power-product SKU with the same ratings, compatibility, and included batteries or accessories.""",

    "display": """IDENTIFIES: Exact monitor, panel, replacement-screen, or privacy-filter model is decisive. Otherwise require brand, diagonal or physical dimensions, aspect ratio, resolution/panel type, and intended device.
HARMLESS: Inch/centimetre conversion, translated display terms, quote formatting, reordered connector lists, rounded dimensions, and price.
VARIANT: Screen size, resolution, curvature, panel technology, colour, response-rate model, privacy level/finish, aspect ratio, device-specific cut, and bare panel versus complete monitor.
SAME MEANS: The same display or screen-accessory SKU with identical dimensions and technical variant.""",

    "mounting_hardware": """IDENTIFIES: Exact RAM/RAP or analogous part code is decisive. Otherwise require mount family, ball diameter, arm/base type, clamp or suction mechanism, and holder compatibility.
HARMLESS: “Ball” versus “orb,” metric/inch conversion, material marketing, reordered component descriptions, missing fastener details, and price.
VARIANT: Ball size, arm length, base type, clamp range, holder size, coating, packed kit versus single component, and included balls, arms, plates, or fasteners.
SAME MEANS: The same mounting component or complete mount kit with the same dimensions and included pieces.""",

    "cycling": """IDENTIFIES: Manufacturer plus exact component or tyre model is strongest. For tyres require model, diameter, width, casing/compound and folding/tubeless construction; for drivetrain parts require series, speed count, fit, and model code.
HARMLESS: Inch formatting, translated bicycle terms, colour synonyms, reordered technology labels, missing marketing prose, and price.
VARIANT: Wheel diameter, tyre width, compound, casing, tubeless/folding status, gear count/range, cage length, pedal standard, left/right fit, colour, and model generation.
SAME MEANS: The same bicycle component in the same size, fit, technology, and retail configuration.""",

    "home_garden": """IDENTIFIES: Exact model code is decisive for appliances and grills. Furniture requires named range, item type, dimensions, material, unit count, and colour; appliance capacity or burner count corroborates.
HARMLESS: Language, reordered dimensions, lifestyle copy, minor rounding, missing assembly details, retailer wording, and price.
VARIANT: Dimensions, colour, material, burner or oven count, built-in versus freestanding/cart-only, furniture piece count, mattress size/thickness, included cover, and model suffix.
SAME MEANS: The same appliance or home/garden item in the same size, colour, construction, and set composition.""",

    "pet_product": """IDENTIFIES: Brand or range plus product type, height/dimensions, intended animal, colour, material, and unit count identify the item; an exact model code is decisive.
HARMLESS: Cat/dog lifestyle prose, “tower/tree/post” wording, unit conversion, reordered dimensions, and price.
VARIANT: Intended animal, height or size, colour, material, level count, included steps/condo, formula or scent for grooming products, and pack quantity.
SAME MEANS: The same pet product in the same size, design, colour, formula, and package quantity.""",

    "apparel": """IDENTIFIES: Brand plus style/model code is decisive. Otherwise require garment or accessory type, team/design, intended wearer, size, colour, material, and cut.
HARMLESS: Language, fashion prose, colour-word order, omitted fabric percentages, retailer wording, and price.
VARIANT: Size, colour, team/logo, fit, gendered cut, sleeve or strap style, material, personalized text, and single item versus multipack.
SAME MEANS: The same apparel style in the same size, colour, design, and customization.""",

    "food_supplement": """IDENTIFIES: Brand, named formula/product, strength or volume, dosage form, and count identify the offer; a manufacturer product code can be decisive.
HARMLESS: Health or tasting claims, language, decimal-comma formatting, reordered ingredients, omitted certifications, and price.
VARIANT: Flavour or variety, strength, bottle volume, capsule/softgel count, dosage form, formula/ingredient version, alcohol expression, personalized packaging, and multipack quantity.
SAME MEANS: The same consumable formula or drink expression in the same strength, size, and package count.""",

    "games_media_stationery": """IDENTIFIES: Exact title, franchise/series, release or expansion, product format, edition, and product number identify the item. For notebook refills, refill number, ruling/paper type, and size are key.
HARMLESS: Language, punctuation, subtitle order, synopsis text, cover-description omissions, and price.
VARIANT: Expansion, edition, release date, language when content differs, physical versus digital format, pack/deck type, card count, print finish, paper ruling, refill size, and bundle count.
SAME MEANS: The same published, collectible, or stationery edition and package, not merely the same series or story.""",

    "other": """IDENTIFIES: Prefer an exact manufacturer model, catalogue number, SKU, or standardized reference. If absent, require agreement on brand, named product line, functional product type, and all prominent measurable attributes; a bare generic title is insufficient.
HARMLESS: Language, word order, capitalization, punctuation, retailer boilerplate, missing descriptions, obviously unrelated brand-field noise, formatting, and price.
VARIANT: Any model suffix, size, capacity, colour, material, compatibility, generation, edition, condition, authenticity, personalization, pack count, or included accessory that changes what is sold.
SAME MEANS: The records denote the same specific sellable product configuration, not merely similar products or members of one family."""
}
