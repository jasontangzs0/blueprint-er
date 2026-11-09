import re

TYPES = [
    "network_equipment",
    "data_storage",
    "memory_card",
    "computer_memory",
    "printer_supply",
    "watch",
    "camera",
    "camera_lens",
    "audio",
    "computer_component",
    "power_equipment",
    "mounting_hardware",
    "bicycle_component",
    "collectible_card_product",
    "furniture_appliance",
    "other",
]

def type_of(r: dict) -> str:
    text = " ".join(str(r.get(k, "") or "") for k in
                    ("title", "brand", "description")).lower()

    def has(pattern):
        return re.search(pattern, text, re.I) is not None

    if has(r"\b(switch|router|access point|network hub|repeater|jetstream|"
           r"catalyst|unifi managed|ethernet switch|gigabit poe|nexus \d{3,4}y)\b"):
        return "network_equipment"

    if has(r"\b(ink cartridge|toner cartridge|inkjet canister|printer ribbon|"
           r"monochrome ribbon|ink module|tinte|ultrachrome|inkpatroon|"
           r"toner|printer ink)\b"):
        return "printer_supply"

    if has(r"\b(microsd|sdxc|sdhc|compactflash|cf memory card|"
           r"sd card|memory card)\b"):
        return "memory_card"

    if has(r"\b(ddr[3457m]?|so[\s-]?dimm|sodimm|udimm|dimm|"
           r"desktop memory|memory module|ram)\b") and not has(
           r"\b(ram-b-|ram®|socket arm|ball base|mount)\b"):
        return "computer_memory"

    if has(r"\b(ssd|hdd|hard drive|solid state|solid disk|nas drive|"
           r"usb flash|flash drive|pendrive|mobile drive|portable drive|"
           r"external drive|internal drive|data tape)\b"):
        return "data_storage"

    if has(r"\b(lens|nikkor|vario-tessar)\b") and has(
           r"\b(\d+(?:-\d+)?\s*mm|f\s*/?\s*\d|camera|canon|nikon|"
           r"sigma|rf\b|xf\b|af-s|e-mount|ef\b)\b"):
        return "camera_lens"

    if has(r"\b(camera|webcam|camview|mirrorless|dslr|cctv|"
           r"video camera|bullet camera|instant camera|zenmuse)\b"):
        return "camera"

    if has(r"\b(watch|chronograph|timepiece|chronometer|mens timer|"
           r"women's clock|automatic clock)\b") and not has(
           r"\b(replacement band|watch band|replacement strap)\b"):
        return "watch"

    if has(r"\b(headphone|headset|earphone|earbuds|airpods|skypods|"
           r"soundbuds|eargear|charging case for)\b"):
        return "audio"

    if has(r"\b(ups|inverter|charger|power adapter|power adaptor|"
           r"replacement battery cartridge|battery charger|powerpack|"
           r"power module)\b"):
        return "power_equipment"

    if has(r"\b(ram-b-|rap-b-|tough-claw|x-grip|suction cup base|"
           r"socket arm|socket brace|ball adapter|ball connector|"
           r"clamp base|rail mount|handlebar rail mount|v-bolt base|"
           r"mount with|mounting base)\b"):
        return "mounting_hardware"

    if has(r"\b(rear derailleur|shifter|disc brake|brake rotor|"
           r"brake pads|bike chain|bicycle cassette|clipless.*pedal|"
           r"spd.*pedal|mtb pedals|road pedal|tubeless ready|"
           r"\btire\b|\btyre\b)\b"):
        return "bicycle_component"

    if has(r"\b(graphics card|geforce|radeon|rtx|gtx|motherboard|"
           r"\bcpu\b|core i[279]|processor|pc case|computer case|"
           r"mid[\s-]?tower|atx case|cpu cooler|liquid cooling|"
           r"case fan|gaming mouse|gaming keyboard|led monitor|"
           r"lcd monitor|privacy filter|screen protector)\b"):
        return "computer_component"

    if has(r"\b(tcg|trading card|collectible card|elite trainer|"
           r"trainer pack|booster pack|fighter pack|card game)\b"):
        return "collectible_card_product"

    if has(r"\b(oven|grill|ceiling fan|mattress|bedframe|sofa|"
           r"dining set|furniture set|storage crate|storage box|"
           r"cat tree|dog tower|scratching post|bar chair|table)\b"):
        return "furniture_appliance"

    return "other"


CARDS = {
    "network_equipment": """IDENTIFIES: An exact manufacturer part number or full switch/router model is decisive when it denotes network equipment. Otherwise require brand, family, port count and management/PoE/SFP configuration together.
HARMLESS: Hyphens, translated “switch/hub” wording, rack-mount descriptions, omitted brand, reordered specifications and price.
VARIANT: Model suffix, port count, uplink type, PoE capability or budget, managed class, speed, software/license tier and pack count.
SAME MEANS: The same network device SKU with the same physical ports and feature/license configuration.""",

    "data_storage": """IDENTIFIES: An exact drive or flash-device part number is decisive. Without one, require product line plus capacity, medium (HDD/SSD/flash/tape), interface and form factor; security features can corroborate.
HARMLESS: GB/TB formatting, translated internal/external wording, rounded transfer rates, retailer warranty text, missing brand and price.
VARIANT: Capacity, HDD versus SSD, interface generation, form factor, RPM, colour when sold as a choice, fingerprint/security version, generation and multipack.
SAME MEANS: The same storage-device SKU at the same capacity and interface/configuration.""",

    "memory_card": """IDENTIFIES: Exact card part number is decisive. Otherwise require line, card format, capacity and speed-class combination; quoted read/write speed supports but rarely identifies alone.
HARMLESS: SD-adapter wording when the adapter is standard/included inconsistently, speed punctuation, unit formatting, language, warranty and price.
VARIANT: Capacity, SD/microSD/CF format, UHS generation, V/A/U class, endurance or Pro/Plus line, bundled adapter when explicitly a different package, and pack count.
SAME MEANS: The same removable-memory card SKU and retail bundle.""",

    "computer_memory": """IDENTIFIES: Exact module/kit code is decisive. Otherwise require line, total capacity, module count, DDR generation, DIMM form and speed; ECC and timings corroborate.
HARMLESS: MHz versus MT/s, punctuation, pin-count omissions, translated memory wording, retailer branding and price.
VARIANT: Total capacity, number of sticks, per-stick capacity, DDR generation, DIMM/SO-DIMM/UDIMM form, ECC/buffering, speed, latency, voltage, colour and kit composition.
SAME MEANS: The same RAM module or factory kit with identical electrical and package configuration.""",

    "printer_supply": """IDENTIFIES: Exact cartridge/ribbon/ink code is decisive even if printer compatibility is worded differently. Otherwise require maker/family, colour, supply type, yield tier and compatible printer series.
HARMLESS: “Genuine/original” placement, translated colour names, compatibility-list order, approximate yield, missing brand, packaging prose and price.
VARIANT: Cartridge code, ink versus toner versus ribbon, colour, standard/high/extra-high yield, volume, page/print yield tier, compatible series and multipack contents.
SAME MEANS: The same consumable SKU, colour, yield and package quantity.""",

    "watch": """IDENTIFIES: A complete watch reference such as dotted or hyphenated model code is decisive. Without it, require brand, collection/model, movement and matching case/dial/strap description.
HARMLESS: Men’s/women’s marketing, “watch/clock/timer” translation, retailer authenticity prose, rounded case dimensions, missing brand and price.
VARIANT: Reference suffix, replica versus authentic product, movement, case size/material, dial colour, strap or bracelet, chronograph/diver edition and limited edition.
SAME MEANS: The same watch reference and sold configuration, not merely the same collection.""",

    "camera": """IDENTIFIES: Exact camera body/security-camera model is decisive. Otherwise require brand, series and generation, with body style or sensor/security-camera form corroborating.
HARMLESS: Body-only word order, translated feature prose, omitted resolution, retailer warranty, missing or noisy brand and price.
VARIANT: Model generation/suffix, body-only versus lens kit, included lens, colour, regional kit, camera form, sensor version, optical zoom, pack count and included PoE/accessories.
SAME MEANS: The same camera model in the same body, kit and package configuration.""",

    "camera_lens": """IDENTIFIES: Exact lens part number is decisive. Otherwise require mount/fit, focal length or range, maximum aperture and model-family markers such as RF, XF, AF-S, Art or OIS.
HARMLESS: Aperture punctuation, millimetre spacing, “lens” omission, warranty duration, translated prose, missing brand and price.
VARIANT: Mount/fit, focal length, aperture, generation suffix, stabilization, macro/zoom/prime design, weather sealing and bundled add-ons.
SAME MEANS: The same optical lens model for the same mount and retail bundle.""",

    "audio": """IDENTIFIES: Exact headset/earbud model or part code is decisive. Otherwise require brand/family, generation, wearing style and wired/wireless configuration; included stand or charging case must agree.
HARMLESS: Headphone/headset terminology, colour-word order, platform marketing, connector prose, missing brand and price.
VARIANT: Model/generation, mono versus stereo, in-ear versus over-ear, wired versus wireless, ANC, platform certification, colour, charging-case type, charging stand and refurbished status.
SAME MEANS: The same audio-device SKU with the same connectivity, accessories and condition.""",

    "computer_component": """IDENTIFIES: Exact board, GPU, CPU, case, cooler, peripheral or display part number is decisive within its component class. Otherwise require brand/family plus core model and principal specifications.
HARMLESS: Specification order, clock rounding, connector prose, translated component names, retailer warranty, erroneous seller brand and price.
VARIANT: Chip/model suffix, generation, memory size, OC edition, socket, case size/colour, fan count, cooler size, display size/resolution, keyboard layout, privacy-filter dimensions and bundle.
SAME MEANS: The same computer-component SKU, revision and sold configuration.""",

    "power_equipment": """IDENTIFIES: Exact UPS, inverter, adapter, charger or battery-cartridge code is decisive; cartridge numbers remain decisive despite omitted brands. Otherwise require family, electrical rating and compatibility.
HARMLESS: VA/W ordering, translated charger wording, punctuation, compatibility-list order, warranty prose, missing brand and price.
VARIANT: Model or cartridge number, voltage, VA/W rating, rack height, plug/region, supported device generation, battery count, charger-only versus charger-plus-battery, and package quantity.
SAME MEANS: The same power product or replacement module with identical rating, compatibility and bundle contents.""",

    "mounting_hardware": """IDENTIFIES: Exact RAM/RAP-style part number is decisive. Otherwise require component type, ball size, arm/base design and attachment mechanism; dimensions corroborate.
HARMLESS: Rounded inch dimensions, ball/sphere wording, hyphenation, material prose, reordered compatibility lists, missing brand and price.
VARIANT: Ball diameter, arm length, base type, suction/clamp/V-bolt mechanism, holder type, rail range, material/finish and single component versus complete mount kit.
SAME MEANS: The same mounting component or kit with the same interfaces and dimensions.""",

    "bicycle_component": """IDENTIFIES: Exact component code is decisive. Without it, require component class, product line and mechanical specification such as speed count, cage, rotor/tire size or pedal system.
HARMLESS: Inch formatting, colour-word order, translated cycling terms, descriptive performance prose, missing brand and price.
VARIANT: Speed count, cage length, compatibility group, rotor or tire dimensions, compound/casing, folding/tubeless construction, axle or cleat system, colour and included quantity.
SAME MEANS: The same bicycle-component SKU in the same size and mechanical configuration.""",

    "collectible_card_product": """IDENTIFIES: Game, set/release and named product format together identify the item; an exact product code is decisive. Product-format words such as trainer box, booster pack or fighter pack are essential.
HARMLESS: Punctuation, localized set-name wording, franchise word order, promotional prose and price.
VARIANT: Set/release, trainer versus booster product, number of packs, included token/promo card, language, edition, deck/fighter identity and sealed bundle contents.
SAME MEANS: The same sealed card-game product from the same release with identical advertised contents.""",

    "furniture_appliance": """IDENTIFIES: Exact model/SKU is decisive. Otherwise require product family, object type, dimensions or unit count, material and colour; appliance fuel or installation style also matters.
HARMLESS: Metric/imperial rounding, lifestyle prose, word order, retailer brand, missing dimensions and price.
VARIANT: Size, colour, material, number of pieces/burners/tiers, indoor versus outdoor version, built-in versus freestanding, fuel type, included cover/cart and model suffix.
SAME MEANS: The same furniture or appliance model in the same size, finish and package composition.""",

    "other": """IDENTIFIES: Prefer an exact, class-appropriate manufacturer model, reference, SKU or part code; it is decisive only when product type is also consistent. Otherwise require agreement on brand/family, product class and the main sellable specifications.
HARMLESS: Price, language, capitalization, punctuation, word order, retailer prose, warranty text, missing fields and clearly erroneous seller-brand values.
VARIANT: Size, capacity, colour, flavour/scent, dosage, edition, generation, model suffix, compatibility, condition, personalization, pack count and accessory/bundle contents.
SAME MEANS: The same retail product SKU or indistinguishable sold configuration, not merely related products or accessories."""
}
