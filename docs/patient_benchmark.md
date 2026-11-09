# The patient-linkage benchmark

A synthetic dataset of patient registrations for evaluating entity resolution where the records
may not be shared. It holds 50,043 records of 45,305 people, with 4,949 true pairs and a largest
cluster of four records. No record describes a real person.

The paper's Section 4 gives the rationale. This document gives what is needed to use the data or
to rebuild it. The generator is `blueprint/patients.py`, with `blueprint/synthea.py`,
`blueprint/names.py` and the corruption tables in `blueprint/geco/`. The command-line entry point
is `scripts/patients_build.py`.

## Files (`data/patients/`)

| File | Content |
|---|---|
| `records.csv` | One row per registration |
| `gold_clusters.txt` | One line per person with two or more records, record ids separated by spaces |
| `datasheet.json` | Every generator parameter (`params`), summary statistics (`stats`) and the profile of each source (`sources`) |
| `provenance.jsonl.gz` | Every change the generator applied to each record |
| `records.jsonl.gz` | The records as JSON |

`records.csv` also carries the true `cluster_id`, the source and three clinical columns. A matcher
must be given only the demographic attributes: `first`, `middle`, `last`, `birthdate`, `gender`,
`ssn`, `address`, `city` and `zip`.

## From simulated patients to records

| Step | Count |
|---|---|
| Patients in the Synthea export | 57,412 |
| Patients used (the first 39,000 of the export) | 39,000 |
| Similar but distinct people added: 3,895 siblings, 1,232 twins, 1,903 namesakes, 774 same-name parents | 7,804 |
| People in total | 46,804 |
| People who receive at least one record | 45,305 |
| Records | 50,043 |

## How a record is generated

A registration is what one organisation recorded about one person at one date. Two records of
one person can differ because the person changed, because the two sources record differently, or
because of a clerical error. The generator applies these layers in turn.

| Layer | What happens | Basis |
|---|---|---|
| Life history | Maiden surname before the simulated marriage date and married surname after it; moves from age 18, with the new address taken from another patient; nicknames and anglicised first names for some patients | Simulator (marriage); Census mover rate |
| Sources | One record per organisation visited, written at the first visit from the person's state at that date. The organisation with the most visits always keeps the record; any other keeps it with probability 0.01 | Chosen so that most people have one record |
| Source profile | Whether the SSN is collected in full, as its last four digits or not at all, and how often it is blank; middle name in full, as an initial or absent; date format; accents; how Hispanic double surnames are written | Deng et al. 2023; Culbertson et al. 2017 |
| Secondary sources | State registry, reference laboratory (initials, birth year, zip), pharmacy and claims extract, each holding a subset of the attributes | Field sets by type of site |
| Clerical error | Blank values, placeholders, typing errors, transposed digits, swapped name fields, placeholder names for newborns | Just et al. 2016; Joffe et al. 2014 |
| Similar but distinct people | Siblings at the same address, twins sharing a birth date and an address, a parent with a child's name, unrelated people with the same name and birth date, shared placeholder SSNs, and records carrying another person's address or birth date | Horon et al. 2022; McCoy et al. 2013; Zech et al. 2016 |
| Repeat registrations | The same source registers a patient again years later under a new identifier | Joffe et al. 2014; ONC 2014 |

First names are redrawn from Social Security baby-name frequencies by year and sex, and surnames
from the 2010 Census surname table conditioned on the simulated race and ethnicity, so that
namesakes occur at realistic rates.

## Parameters of the released build

All values are in `datasheet.json` under `params`. The main rates are below, as per-record
probabilities unless stated.

| Parameter | Value |
|---|---|
| Middle name blank / reduced to an initial | 0.18 / 0.06 |
| SSN missing at a site | 0.05 to 0.40, varying by site |
| SSN blank / placeholder / typing error | 0.06 / 0.07 / 0.01 |
| First name typing error / blank | 0.08 / 0.02 |
| First and last swapped / first and middle swapped | 0.009 / 0.005 |
| Last name typing error / blank | 0.05 / 0.006 |
| Birth date day / year / month wrong, day and month swapped | 0.015 / 0.0125 / 0.007 / 0.0008 |
| Gender blank / flipped | 0.005 / 0.025 |
| Address missing / typing error | 0.03 / 0.03 |
| Zip missing / typing error | 0.02 / 0.015 |
| Moves per year from age 18 | 0.12 |
| Patients with a nickname / an anglicised first name | 0.06 / 0.25 |
| Sibling / twin / same-name parent / namesake, per patient | 0.10 / 0.031 / 0.02 / 0.05 |
| Repeat registration | 0.06 |
| Registry, laboratory, pharmacy and claims, share of people each | 0.005 |

## Calibration

The share of true pairs whose two records disagree on an attribute, against the measurements of
Just et al. (2016) on 398,939 confirmed duplicate pairs. The benchmark rate is over the true pairs
in which both records carry the attribute.

| Attribute | Measured | Benchmark |
|---|---|---|
| First name | 0.226 | 0.197 |
| Middle name | 0.580 | 0.469 |
| Last name | 0.237 | 0.258 |
| Birth date | 0.062 | 0.068 |
| Gender | 0.060 | 0.057 |
| SSN | 0.530 | 0.515 |

## Rebuilding

The build needs three inputs that are not stored in this repository.

1. A Synthea CSV export. The released build used commit `d9d07a6` of
   [Synthea](https://github.com/synthetichealth/synthea), Java 17, seed 29, clinician seed
   1792200775099 and reference date 2026-10-17:

   ```
   java -jar synthea-with-dependencies.jar -p 50000 -s 29 -cs 1792200775099 -r 20261017 \
        --exporter.csv.export true --exporter.fhir.export false \
        --exporter.hospital.fhir.export false --exporter.practitioner.fhir.export false Massachusetts
   ```

   The export must include `encounters.csv` and `organizations.csv`. Asking for 50,000 living
   patients produced 57,412 in total, 7,412 of them deceased.

2. `data/external/names/baby-names.csv`, the Social Security baby-name file for 1880 to 2008
   as packaged in [hadley/data-baby-names](https://github.com/hadley/data-baby-names).

3. `data/external/names/census/Names_2010Census.csv`, from the
   [2010 Census surname files](https://www.census.gov/topics/population/genealogy/data/2010_surnames.html).

Then, from the repository root (the names files are read relative to the working directory):

```
PYTHONHASHSEED=1 PYTHONPATH=. python scripts/patients_build.py --raw <export>/csv \
    --out data/patients_rebuilt --preset calibrated_upper_matched --seed 29 \
    --custodians 0 --secondary 0.01 --limit 39000
```

Starting from the export used for the paper, this command reproduces the records, the gold clusters
and the provenance byte for byte. The rebuilt `datasheet.json` records one parameter added to the
generator after the release (`go_live_years`, unused here). `PYTHONHASHSEED=1` matters: under another hash seed the statistics and the gold clusters are
unchanged, but 5 of the 50,043 records differ by one character of a typing error. Synthea itself
was not rerun to test whether the export can be reproduced from these settings.

## Limits

The benchmark is synthetic throughout. Each rate parameter is tied to a published measurement,
but the nickname table, the construction of households and the attribute sets of the sources are
design choices, and the realism of the whole has not been measured against real patient data.
The middle-name rate is 0.11 below its measurement because the per-record rates were calibrated
at a higher duplicate density, at which the pair rate is 0.60. The parameters that govern
namesakes, moves, siblings and same-name parents are set at the upper end of their measured
ranges.
