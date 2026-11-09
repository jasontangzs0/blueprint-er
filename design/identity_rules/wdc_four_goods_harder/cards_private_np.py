import re

TYPES = [
    "apparel",
    "sports_gear",
    "automotive_part",
    "vehicle",
    "commercial_equipment",
    "furniture_home",
    "industrial_part_tool",
    "real_estate",
    "other",
]

def type_of(r: dict) -> str:
    text = " ".join(str(r.get(k) or "") for k in ("title", "brand", "description")).casefold()
    text = re.sub(r"\s+", " ", text)

    if re.search(
        r"\b(?:property|properties|apartment|apartments|flat|flats|suite|villa|"
        r"estate|homes?|bedroom|bath home|lakefront|parcel lot|for market)\b|"
        r"\b\d{2,5}\s+(?:ne|nw|se|sw|north|south|east|west)?\s*\d+(?:st|nd|rd|th)\s+st\b",
        text,
    ):
        return "real_estate"

    if re.search(
        r"\b(?:lease specials?|lease a|for sale in|auto sales|motors llc|"
        r"inventory id|transfer van|motorized bicycle|e-велосипед|electric bicycle)\b",
        text,
    ):
        return "vehicle"

    if re.search(
        r"\b(?:brake pads?|brake caliper|brake disc|rotor upgrade|clutch kit|"
        r"control arm|struts?|suspension|shock(?:s)?\s*&\s*springs|muffler|exhaust|"
        r"carburetor|air filters?|oil filters?|engine oil|fuel tank|transmission|"
        r"drive shaft|window regulator|windshield|wiper|rear view mirror|"
        r"wheel(?:s)?\s*-\s*[a-z0-9]|tires?|all-season tire|disc guard|"
        r"cooling fan|steering column|door lock|rear window|front left|front right|"
        r"rear lower|oem\s*#|replaces oem|genuine (?:bmw|audi)|"
        r"base (?:coupe|sedan|wagon|convertible|hatchback)|"
        r"motorcycle|snowmobile|scooter|atv|dirt bike)\b",
        text,
    ):
        return "automotive_part"

    if re.search(
        r"\b(?:restaurant|food service|eatery|culinary depot|kitchen depot|"
        r"restaurant supply|draft beer dispenser|gas range|convection oven|"
        r"charbroiler|booster heater|chef base|work table|meal tray|dishwasher|"
        r"cup dispenser|lid dispenser|drink mixer|cooker|commercial range|"
        r"storage unit cooling|counter coolers?|plate dinnerware|sweep handle|"
        r"brush grip|refuse (?:basket|bin))\b",
        text,
    ):
        return "commercial_equipment"

    if re.search(
        r"\b(?:sofa|couch|lounge chair|seatmodule|shelf unit|wall system|"
        r"cabinet|drawer chest|table\b|chairs?|storebox|storebins|rug|"
        r"cushion cover|throws?|blankets?|bed(?:ding)?|garland|flag banner|"
        r"\bbanner\b|dinner plate|bowls?|wine cup|tray\b|shoe tray|"
        r"rack\b|folio periodical holder|ikea|boconcept)\b",
        text,
    ):
        return "furniture_home"

    if re.search(
        r"\b(?:baseball glove|softball glove|training glove|goalkeeper gloves?|"
        r"keeper gloves?|snowboard|snow goggle|goggles|golf balls?|"
        r"helmet|faceguard|rifle bag|scope mount|scope mask|bike rack|"
        r"fork-mount rack|bicycle|hybrid bikes?|cycling|chainset|"
        r"football outfit|soccer|fastpitch|baseball (?:club|rod)|"
        r"ammunition|ammo crate|pistol grip|holster|hunting|"
        r"athletic equipment|sports equipment)\b",
        text,
    ):
        return "sports_gear"

    if re.search(
        r"\b(?:dress|gown|shirt|t-shirt|tee\b|polo(?:shirt)?|blouse|top\b|"
        r"jacket|coat|hoodie|sweater|pullover|cardigan|fleece|jeans|pants|"
        r"trousers|shorts|skirt|leggings|treggings|bodysuit|romper|jumpsuit|"
        r"briefs?|underwear|baselayer|socks?|cap\b|hat\b|beanie|scarf|shawl|"
        r"cloak|belt\b|swimsuit|uniform|apparel|clothing|bekleidung|"
        r"camiseta|pantalon(?:es)?|vestido|maglia|felpa|giacca|"
        r"trouse|trous\b|ladies top|women'?s black set)\b",
        text,
    ):
        return "apparel"

    if re.search(
        r"\b(?:bolt|bushing|bearing|gasket|seal kit|sensor|switch device|"
        r"thermal switch|lubricant|washer|dowel|sleeve|clamp|cable|"
        r"starter line|mounting board|protective cover|support bar|"
        r"mallet|wrench|battery|paint|spray|rust remover|rust dissolver|"
        r"replacement part|spare part|genuine part|part number|item code|"
        r"gearbox|generator|heater|engine\b|tiller|work table|"
        r"ref\.\s*[a-z0-9-]+|cod\.[a-z0-9-]+)\b",
        text,
    ):
        return "industrial_part_tool"

    return "other"


CARDS = {
    "apparel": """IDENTIFIES: Brand plus named line/model and garment type identify; a distinctive retailer title can suffice when essentially exact. Printed style codes are decisive alone when complete.
HARMLESS: Translation, word order, duplicated garment words, retailer/category text, missing brand, minor description changes, currency, and price are harmless.
VARIANT: Garment type, model/line, style code, colour or print, gender/age range, sleeve or leg form, fit, size, and pack/set count make different entities. Similar generic descriptions do not override these differences.
SAME MEANS: The same branded clothing style in the same dataset-level colour/design and demographic configuration, regardless of shop wording or price.""",

    "sports_gear": """IDENTIFIES: Manufacturer and exact model/style code are strongest; a complete distinctive model name plus equipment type needs corroboration from dimensions or description. A unique SKU is decisive alone.
HARMLESS: Language, seller suffixes, reordered wording, duplicated category labels, price, and compatible-use prose are harmless.
VARIANT: Model suffix/code, sport or equipment type, handedness, position, size or length, colourway, youth/adult designation, generation, and included-piece count make different entities. Near-identical glove, helmet, goggle, or uniform descriptions are not enough when codes or colours differ.
SAME MEANS: The same sporting product model in the same size, side, colourway, generation, and package configuration.""",

    "automotive_part": """IDENTIFIES: Exact manufacturer/OEM/aftermarket part number is decisive alone. Otherwise require part type plus brand and matching position, dimensions, or fitment range; a vehicle name alone is not an identifier.
HARMLESS: Retailer text, language, price, repeated codes, “genuine” wording, and incidental vehicle examples may vary. Different vehicle listings are harmless for a clearly identical universal product or identical part number.
VARIANT: Part number, component type, front/rear/left/right position, dimensions, material, engine/application code, fitment-defining year range, kit contents, and model suffix make different entities.
SAME MEANS: The same physical replacement or accessory part with the same functional specification, position, fitment-defining code, and package.""",

    "vehicle": """IDENTIFIES: VIN or inventory identifier is decisive alone. Otherwise require make, model, model year, trim, and vehicle type; seller name or listing location only corroborates.
HARMLESS: Dealer wording, finance or lease language, price, location formatting, promotional claims, and omitted descriptive features are harmless.
VARIANT: VIN/inventory ID, model year, make/model, trim, body style, engine or propulsion, and materially different configuration make different entities. A shared model name does not merge separate listed vehicles.
SAME MEANS: The same specific vehicle listing when uniquely inventoried, or the same year-make-model-trim configuration where the data describes an offer rather than an individual unit.""",

    "commercial_equipment": """IDENTIFIES: Brand plus manufacturer model/SKU is normally decisive; an exact model code alone is decisive when clearly presented. Without a code, require equipment type and matching dimensions, capacity, power, fuel, and configuration.
HARMLESS: Distributor names, category breadcrumbs, boilerplate availability text, language, duplicated measurements, missing price, and price differences are harmless.
VARIANT: Model code, width, capacity, voltage, wattage, gas type, burner/deck/drawer count, mounting style, finish, or included accessories make different entities. Similar templated descriptions do not establish identity.
SAME MEANS: The same commercial appliance or supply item with the same manufacturer model and operating/configuration specifications.""",

    "furniture_home": """IDENTIFIES: Collection/product name plus maker and object type identifies; a catalog code is decisive alone. For generic home goods, require matching material, dimensions, colour/pattern, and set count.
HARMLESS: Translation, retailer/category wording, word order, repeated nouns, room-use prose, price, and missing descriptions are harmless.
VARIANT: Furniture module or configuration, dimensions, material, colour/pattern, number of seats/inserts/drawers, indoor/outdoor version, and pack count make different entities. Products from one collection are not automatically the same.
SAME MEANS: The same furniture or household article in the same physical configuration, dimensions, finish, and set quantity.""",

    "industrial_part_tool": """IDENTIFIES: Manufacturer part, catalog, reference, or item code is decisive alone. Otherwise require matching brand, precise part/tool type, dimensions, material, and function; generic words such as bolt or sensor need corroboration.
HARMLESS: Language, supplier names, HTML, reordered specifications, duplicated codes, price, and unrelated application examples are harmless.
VARIANT: Any code suffix, dimensions, thread or connector form, voltage/current, material, orientation, capacity, colour when functional, kit contents, and revision make different entities. Adjacent catalog references are distinct even when descriptions are nearly identical.
SAME MEANS: The same catalogued component, consumable, or tool with the same technical specification and supplied contents.""",

    "real_estate": """IDENTIFIES: Full street address or property/listing identifier is decisive alone when consistent. Otherwise require matching building/project, unit number, locality, and property description.
HARMLESS: Agent/site wording, promotional prose, punctuation, abbreviated street directions, price omission, and ordinary description updates are harmless.
VARIANT: Street number, street name, unit or suite, listing ID, city/community, parcel, and materially different bedroom/bath configuration make different entities. Similar house descriptions or the same agency do not imply identity.
SAME MEANS: The same physical property or unit at the same address, not merely a similar home or development.""",

    "other": """IDENTIFIES: Prefer an exact product, catalog, ISBN-like, GTIN, or style code; a complete distinctive brand-and-model name can identify with corroborating description. For uncoded goods, require close agreement on product type and salient specifications.
HARMLESS: Shop names, category breadcrumbs, translation, word order, HTML, missing fields, duplicated words, currency, and price are harmless. Exact descriptive copies may corroborate identity.
VARIANT: Different model/code, product type, edition or generation, dimensions, capacity, colour/design, material, compatibility, pack count, or included components make different entities.
SAME MEANS: The records denote the same catalogued real-world product in the same dataset-relevant configuration, rather than merely sharing wording or a brand."""
}
