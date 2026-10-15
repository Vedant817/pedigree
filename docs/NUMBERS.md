# NUMBERS - the only allowed source of numbers in README, blog and video

Every measurement printed in README.md, docs/BLOG-DRAFT.md and the demo video script
must appear below, with the script that produced it. `make check` enforces this via
`scripts/check_numbers.py`; `scripts/extract_numbers.py` appends eval results (once
`make eval` exists, F-14). Unflattering values are kept - never rounded away.

<!-- NUMBERS:BEGIN -->
falkordb_version = 4.22.1
falkordb_module_version = 42201
python_min = 3.11
tracks_entered = 2
<!-- NUMBERS:END -->

## How to add a number

1. Produce it with a committed script (evals/, scripts/) - never by hand.
2. Add `key = value  # source: script/file, date` inside the block above.
3. Run `make check`.
