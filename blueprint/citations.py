"""Loader for the Citations (Citeseer x DBLP) record-linkage benchmark (Magellan).

Two real bibliographic systems with ORGANIC noise (parsing errors, author-name
variance, venue abbreviations) — no synthetic perturbation. Gold: complete pair
list (558,787 pairs; "has complete gold" per Sparkly Sec 4.5). Used as "BC" in
Sparkly (PVLDB 2023) and DeepBlocker (PVLDB 2021).

Both tables share the id space, so ids are namespaced ("c<id>" / "d<id>").
Standard record shape:

    id            <- "c"+id (citeseer) / "d"+id (dblp)
    cluster_id    <- transitive closure of the gold pair list (complete gold)
    source_domain <- "citeseer" | "dblp"
    brand         <- authors    (strong identifier, like artist/brand)
    title         <- title
    description   <- journal
    year          <- year       (extra field; serializers may use it)
"""
import csv
from pathlib import Path
from typing import Any, Dict, List, Union

PathLike = Union[str, Path]


def load_citations(
    citeseer_path: PathLike,
    dblp_path: PathLike,
    matches_path: PathLike,
) -> List[Dict[str, Any]]:
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    with Path(matches_path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            a, b = "c" + row["id1"].strip(), "d" + row["id2"].strip()
            parent.setdefault(a, a)
            parent.setdefault(b, b)
            parent[find(a)] = find(b)

    records: List[Dict[str, Any]] = []
    for path, prefix, source in ((citeseer_path, "c", "citeseer"), (dblp_path, "d", "dblp")):
        with Path(path).open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                rid = prefix + row["id"].strip()
                records.append(
                    {
                        "id": rid,
                        "cluster_id": find(rid) if rid in parent else rid,
                        "source_domain": source,
                        "brand": _clean(row.get("authors")),
                        "title": _clean(row.get("title")),
                        "description": _clean(row.get("journal")),
                        "year": _clean(row.get("year")),
                        "price": None,
                    }
                )
    return records


def _clean(value: Any) -> Any:
    text = (value or "").strip()
    return text or None
