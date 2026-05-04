---
name: wiki-finalize-ingest
description: Dispatched by wiki-ingest after all batches complete to merge logs, rebuild indexes, and run post-processing. Do not invoke directly unless all batch-log files are present.
model: sonnet
skills:
  - wiki-finalize-ingest
  - wiki-lint
---

Follow the wiki-finalize-ingest skill to merge batch logs, rebuild Wiki indexes, and run all post-processing steps.
