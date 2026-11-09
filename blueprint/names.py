"""Real-frequency names for the patient benchmark.

Synthea's names are nearly unique (990 distinct first names among 1,171 patients in the
public sample), which hands every matcher a secret key no registry has. This module
redraws names from the public frequency tables so that namesakes and near-namesakes
arise at their real rates:

  - first names: SSA baby-name counts by year and sex (top 1,000 per year, ~90% of
    births; mirror of the SSA file, 1880-2008; later years use 2008)
  - surnames: 2010 Census surname file with per-group shares, so the draw is
    conditioned on Synthea's race/ethnicity (Hispanic, White, Black, Asian/Pacific,
    American Indian/Alaska Native, two or more)

Files: data/external/names/baby-names.csv, data/external/names/census/Names_2010Census.csv.
Absent files -> ``available()`` is False and the builder keeps Synthea's names.
"""
from __future__ import annotations

import bisect
import csv
import itertools
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

NAMES_DIR = Path("data/external/names")
FIRST_FILE = NAMES_DIR / "baby-names.csv"
SURNAME_FILE = NAMES_DIR / "census" / "Names_2010Census.csv"

_GROUP_COL = {"white": "pctwhite", "black": "pctblack", "api": "pctapi", "aian": "pctaian",
              "2prace": "pct2prace", "hispanic": "pcthispanic"}


def available() -> bool:
    return FIRST_FILE.exists() and SURNAME_FILE.exists()


def group_of(race: str, ethnicity: str) -> str:
    """Map Synthea RACE / ETHNICITY to a Census surname group."""
    if (ethnicity or "").lower() == "hispanic":
        return "hispanic"
    return {"white": "white", "black": "black", "asian": "api", "native": "aian"}.get((race or "").lower(), "2prace")


class _Table:
    """Weighted sampler over (names, cumulative weights)."""

    def __init__(self, names: Sequence[str], weights: Sequence[float]):
        self.names = list(names)
        self.cum = list(itertools.accumulate(weights))

    def draw(self, rng: random.Random) -> str:
        if not self.names:
            return ""
        u = rng.random() * self.cum[-1]
        return self.names[bisect.bisect_left(self.cum, u)]


class NameTables:
    def __init__(self, first_file: Path = FIRST_FILE, surname_file: Path = SURNAME_FILE, max_surnames: int = 60000):
        by_year: Dict[Tuple[str, int], Tuple[List[str], List[float]]] = defaultdict(lambda: ([], []))
        with first_file.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                sex = "M" if row["sex"] == "boy" else "F"
                key = (sex, int(row["year"]))
                by_year[key][0].append(row["name"])
                by_year[key][1].append(float(row["percent"]))
        self.first: Dict[Tuple[str, int], _Table] = {k: _Table(*v) for k, v in by_year.items()}
        self.years = sorted({y for _, y in self.first})
        groups: Dict[str, Tuple[List[str], List[float]]] = {g: ([], []) for g in _GROUP_COL}
        with surname_file.open(encoding="utf-8") as handle:
            for i, row in enumerate(csv.DictReader(handle)):
                if i >= max_surnames or row["name"] == "ALL OTHER NAMES":
                    break
                name = row["name"].title()
                count = float(row["count"])
                for g, col in _GROUP_COL.items():
                    pct = row.get(col, "")
                    try:
                        w = count * float(pct) / 100.0
                    except ValueError:                       # "(S)" suppressed cells
                        w = 0.0
                    if w > 0:
                        groups[g][0].append(name)
                        groups[g][1].append(w)
        self.surname: Dict[str, _Table] = {g: _Table(*v) for g, v in groups.items()}

    def first_name(self, sex: str, birth_year: int, rng: random.Random) -> str:
        year = min(max(birth_year, self.years[0]), self.years[-1])
        table = self.first.get((sex if sex in ("M", "F") else "F", year))
        return table.draw(rng) if table else ""

    def surname_for(self, race: str, ethnicity: str, rng: random.Random) -> str:
        return self.surname[group_of(race, ethnicity)].draw(rng)


# --------------------------------------------------------------------------- #
# Population-diversity conventions (source 3 of hardness). The SSA and Census tables
# carry no accents, so accented canonical forms are restored here for the names that
# have them; sources then keep or drop accents by their own convention. Anglicised
# forms are what an English-speaking registration desk often writes down.
# --------------------------------------------------------------------------- #
ACCENTED: Dict[str, str] = {
    "Jose": "José", "Maria": "María", "Jesus": "Jesús", "Angel": "Ángel", "Andres": "Andrés", "Nicolas": "Nicolás",
    "Sebastian": "Sebastián", "Martin": "Martín", "Raul": "Raúl", "Ramon": "Ramón", "Tomas": "Tomás",
    "Veronica": "Verónica", "Monica": "Mónica", "Ines": "Inés", "Lucia": "Lucía", "Sofia": "Sofía", "Adrian": "Adrián",
    "Ivan": "Iván", "Joaquin": "Joaquín", "Ruben": "Rubén", "Julian": "Julián", "Fabian": "Fabián", "Damian": "Damián",
    "Cesar": "César", "Hector": "Héctor", "Oscar": "Óscar", "Victor": "Víctor", "Agustin": "Agustín", "Benjamin": "Benjamín",
    "Rocio": "Rocío", "Belen": "Belén", "Ines": "Inés", "Aaron": "Aarón", "Efrain": "Efraín", "Joaquina": "Joaquina",
    "Jimenez": "Jiménez", "Hernandez": "Hernández", "Rodriguez": "Rodríguez", "Garcia": "García", "Gonzalez": "González",
    "Martinez": "Martínez", "Lopez": "López", "Perez": "Pérez", "Sanchez": "Sánchez", "Ramirez": "Ramírez", "Gomez": "Gómez",
    "Diaz": "Díaz", "Vasquez": "Vásquez", "Vazquez": "Vázquez", "Munoz": "Muñoz", "Nunez": "Núñez", "Pena": "Peña",
    "Ibanez": "Ibáñez", "Suarez": "Suárez", "Marquez": "Márquez", "Alvarez": "Álvarez", "Dominguez": "Domínguez",
    "Fernandez": "Fernández", "Gutierrez": "Gutiérrez", "Cardenas": "Cárdenas", "Chavez": "Chávez", "Velazquez": "Velázquez",
    "Velasquez": "Velásquez", "Rios": "Ríos", "Juarez": "Juárez", "Ordonez": "Ordóñez", "Yanez": "Yáñez", "Farias": "Farías",
    "Benitez": "Benítez", "Mendez": "Méndez", "Galvez": "Gálvez", "Lemus": "Lemus",
}

ANGLICISED: Dict[str, str] = {
    "José": "Joseph", "Juan": "John", "Guillermo": "William", "Miguel": "Michael", "Jorge": "George", "Pedro": "Peter",
    "Pablo": "Paul", "Francisco": "Frank", "Ana": "Anna", "María": "Mary", "Luis": "Louis", "Carlos": "Charles",
    "Andrés": "Andrew", "Esteban": "Steven", "Ricardo": "Richard", "Roberto": "Robert", "Enrique": "Henry", "Rafael": "Ralph",
    "Tomás": "Thomas", "Teresa": "Theresa", "Catalina": "Catherine", "Isabel": "Elizabeth", "Margarita": "Margaret",
    "Alejandro": "Alexander", "Antonio": "Anthony", "Nicolás": "Nicholas", "Cristina": "Christine", "Elena": "Helen",
    "Mateo": "Matthew", "Martín": "Martin", "Julián": "Julian", "Sebastián": "Sebastian", "Adrián": "Adrian",
    "Iván": "Ivan", "Rubén": "Ruben", "Raúl": "Raul", "Ramón": "Raymond", "Jesús": "Jesse", "Ángel": "Angel",
    "Lucía": "Lucy", "Sofía": "Sophia", "Verónica": "Veronica", "Mónica": "Monica", "Inés": "Agnes", "Rocío": "Rocio",
    "Héctor": "Hector", "Óscar": "Oscar", "Víctor": "Victor", "César": "Cesar", "Benjamín": "Benjamin", "Daniel": "Daniel",
    "Gabriel": "Gabriel", "Samuel": "Samuel", "Diego": "James", "Santiago": "James", "Manuel": "Manuel", "Fernando": "Ferdinand",
    "Eduardo": "Edward", "Alberto": "Albert", "Arturo": "Arthur", "Vicente": "Vincent", "Felipe": "Philip", "Marcos": "Mark",
    "Lorenzo": "Lawrence", "Ignacio": "Ignatius", "Jaime": "James", "Gerardo": "Gerald", "Rodrigo": "Roderick",
    "Rosa": "Rose", "Juana": "Jane", "Josefa": "Josephine", "Josefina": "Josephine", "Luisa": "Louise", "Carmen": "Carmen",
    "Dolores": "Dolores", "Marta": "Martha", "Beatriz": "Beatrice", "Susana": "Susan", "Silvia": "Sylvia", "Raquel": "Rachel",
    "Esperanza": "Hope", "Paula": "Paula", "Mercedes": "Mercedes", "Alicia": "Alice", "Adela": "Adele", "Eugenia": "Eugenia",
}


def accented(name: str) -> str:
    return ACCENTED.get(name, name)


_CACHE: Optional[NameTables] = None


def tables() -> Optional[NameTables]:
    global _CACHE
    if _CACHE is None and available():
        _CACHE = NameTables()
    return _CACHE
