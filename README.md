# Blueprint: privacy-preserving entity resolution with large language models

Code, datasets and run records for the paper *Privacy-preserving entity resolution with large
language models* (Z. Tang and M. Kejriwal).

Blueprint separates the design of a resolution from its execution. A hosted model (the design
model) writes the identity rules and the blocking keys from records and pairs that a privacy
filter has rewritten. A local model (the matching model) performs all matching, first over the
records and then over the resolved entities.

## Contents

| Path | What it holds |
|---|---|
| `blueprint/` | The method: prompts, privacy filter, evidence sampling, scoring, the model client, and the dataset generators |
| `scripts/` | Command-line entry points: the pipeline, the baselines, the card experiment and the dataset builders |
| `data/wdc-four-domains/`, `data/wdc-multi/`, `data/patients/` | The three datasets built for the paper |
| `data/public-subsets/` | Record identifiers of the evaluated subsets of the three public benchmarks |
| `design/identity_rules/` | The identity rules the design model wrote for each dataset, with the rewritten inputs it received |
| `runs/` | Scores, blocking keys, exposure reports and partitions of every reported run |
| `baselines/llmcer/` | The adaptation of the LLM-CER implementation used as a baseline |
| `docs/patient_benchmark.md` | Documentation of the patient benchmark: how records are generated, its parameters and how to rebuild it |
| `tests/` | Tests of the dataset generators |

The complete model answers of every run (about 2 GB uncompressed) are distributed as a release
asset, `blueprint-run-logs.tar.gz`, and not stored in the repository.

## Names used in the code

The code was written before the paper's vocabulary was fixed. The two correspond as follows.

| In the paper | In the code and the run records |
|---|---|
| Blueprint | `reper`, REP-ER |
| identity rules (kinds, classifier, cards) | identity theory, cards, `TYPES` / `type_of` / `CARDS` |
| privacy filter, validator | `privatize`, the check |
| record round, entity round | round 1, round 2 (`keyreps`) |
| conventional blocker | round 0, BM25 blocks |
| representative | `rep` |
| the form of a value | shape |
| dataset | collection |

Datasets carry these identifiers in file and folder names.

| In the paper | Identifier |
|---|---|
| WDC | `wdc_s` |
| WDC-Four-Domains | `wdc_four_domains` |
| WDC-Multi | `wdc_four_goods_harder` |
| Citations | `cit_51k` |
| Songs | `songs_50k` |
| Patients | `patients50k_matched` |

Matching models: `gpt-oss-120b` (open-weight) and `gpt-5-nano` (closed). Design model: `gpt-5.6-sol`.

## Datasets

**WDC-Four-Domains** (`data/wdc-four-domains/`): 10,000 product listings of 2,485 products from
the four human-verified categories of the WDC product corpus v2 (computers, cameras, watches,
shoes). `records.csv`, `gold_clusters.txt` (one line per product with two or more listings),
`test_pairs.csv` (the 4,376 verified pairs, 1,198 positive), `build_info.json`. Built by
`scripts/wdc_four_domains_build.py`.

**WDC-Multi** (`data/wdc-multi/`): 10,000 listings from four further categories of the same
corpus (clothing, home and garden, sports and outdoors, automotive); half of the products with
copies are listed in more than one language. `records.csv`, `gold_clusters.txt`,
`identifiers.jsonl`, `build_info.json`. Built by `scripts/wdc_four_goods_harder_build.py`.

**Patients** (`data/patients/`): 50,043 synthetic patient registrations of 45,305 people, with
4,949 true pairs. `records.csv` (the matcher is given first, middle and last name, birth date,
gender, SSN, address, city and zip), `gold_clusters.txt`, `datasheet.json` (every parameter with
its reference measurement, and the statistics of the dataset), `provenance.jsonl.gz` (every
change applied to every record) and `records.jsonl.gz`. All values are synthetic: the people
come from the Synthea simulator and no record describes a real person. Built by
`scripts/patients_build.py` from a Synthea export; the generator is `blueprint/patients.py`.
`docs/patient_benchmark.md` documents it and gives the exact commands. A rebuild needs a Synthea
export and two public name tables, which are not stored here.

The two WDC datasets are derived from the WDC product corpus (Primpeli, Peeters and Bizer,
2019), whose text originates from public web pages; please cite the corpus when using them.

**Public benchmarks.** The WDC benchmark, the Million Song Dataset and the CiteSeer-DBLP records
are available from their original sources. `data/public-subsets/` gives the gold clusters, and
hence the record identifiers, of the subsets evaluated; `scripts/songs_subset.py` and
`scripts/citations_subset.py` rebuild the Songs and Citations subsets from the original files.

## Running the method

```
pip install -e .
cp .env.example .env      # endpoint, key and default model of any OpenAI-compatible service
```

The two steps of a run are documented at the top of each script, with every option.

1. Identity rules: `scripts/identity_cards.py` samples records and near-duplicate pairs, passes
   them through the privacy filter and asks the design model for the kinds, the classifier and
   the cards.
2. Resolution: `scripts/reper.py` runs the record round, asks the design model for the blocking
   keys from the rewritten decisions of that round, and runs the entity round.

A run that uses the hosted design model sends it only rewritten records and pairs. What was
sent, retried, replaced or withheld is written next to the results.

The baselines are `scripts/select_sample.py` (select prompt), `scripts/batched_run.py` (batched
pairwise prompt) and the LLM-CER implementation of its authors with the adaptation in
`baselines/llmcer/`. `scripts/bm25_pairs.py` writes the candidate pairs the two prompt baselines
judge. `scripts/pairing_probe.py` runs the card experiment.

## Run records

`runs/` holds, for every reported run, the files small enough for a repository.

| Folder | Runs | Reported in |
|---|---|---|
| `runs/blueprint/` | The twelve Blueprint runs | Tables 5 and 7, appendix tables |
| `runs/recorded_uncut_and_second_round/` | The same runs as recorded, with uncut candidate lists and the trial of a second entity round | Sections 6.1 and 6.5 |
| `runs/ablation_partition/` | The alternative design that partitions key blocks | Table 9 |
| `runs/ablation_single_records/` | The entity round repeated over single records on WDC | Section 6.4 |
| `runs/card_experiment/` | The anchored decision under four cards | Table 6 |
| `runs/card_runs_closed_model/` | Record round of the closed model on Songs with no card and with the card from real records | Section 6.2 |
| `runs/baselines/` | Select prompt, batched pairwise prompt and LLM-CER | Table 5, appendix tables |

In a run folder, `summary.json` gives the scores after each round and the cost;
`keys_r2.json` the blocking key functions the design model wrote;
`keys_r2_evidence_private.json` the rewritten evidence it received;
`privatize_r2_report.json` the exposure report of that call; and `partition_r1.json.gz` and
`partition_r2.json.gz` the clusters after the record round and the entity round.

The release asset adds, for every run, the candidate lists and the complete answer of every
matching call, from which each run can be replayed without a model.

## Tests

```
python -m pytest
```

## Licence

The code is released under the MIT licence (`LICENSE`), with two exceptions: `blueprint/geco/` is
third-party code under the Mozilla Public License 2.0 (see its `LICENSE` and `NOTICE.md`), and
the patch in `baselines/llmcer/` modifies code released by the LLM-CER authors under the licence
in `LICENSE-LLMCER`.

The data we created is released under CC BY 4.0 (`LICENSE-DATA.md`). Record text that originates
elsewhere, in particular the product listings of the two WDC datasets, stays under the terms of
its source; `LICENSE-DATA.md` lists what is and is not covered.

## Citation

Z. Tang and M. Kejriwal. Privacy-preserving entity resolution with large language models.
Manuscript, 2026.
