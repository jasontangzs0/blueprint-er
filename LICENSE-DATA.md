# Data licence

Copyright (c) 2026 Zhisheng Tang and Mayank Kejriwal.

The material listed under "Covered" is licensed under the Creative Commons Attribution 4.0
International licence (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/legalcode

## Covered

- `data/patients/`: the synthetic patient benchmark. No record describes a real person.
- `design/`: the identity rules and the rewritten inputs from which they were written.
- `runs/`: scores, blocking keys, exposure reports and partitions.
- `data/wdc-four-domains/` and `data/wdc-multi/`: the selection of records, the gold clusters
  and the build information only.
- `data/public-subsets/`: the gold clusters of the evaluated subsets.
- The run logs archive `blueprint-run-logs.tar.gz`: the model answers and candidate lists,
  except for the record text described below.

## Not covered

Record text that originates elsewhere stays under the terms of its source, and no rights in it
are granted here:

- the product listing text in `data/wdc-four-domains/` and `data/wdc-multi/`, and any such text
  repeated in the run records, which comes from the WDC product corpus and originally from
  public web pages;
- the song and bibliographic record text, and the WDC benchmark text, repeated in the run
  records and in the run logs archive, which come from the Million Song Dataset, the
  CiteSeer-DBLP records and the WDC benchmark.

Please cite the original sources when using this text.
