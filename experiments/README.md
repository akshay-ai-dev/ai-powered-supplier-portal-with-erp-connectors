# Experiments

A place to try out a feature or idea before it goes into `backend/` or `frontend/`. Nothing here ships.

## Structure

Each experiment gets its own folder:

```
experiments/
└── <experiment_name>/
    ├── script.py          # the code being tried out
    ├── FINDINGS.md        # system design worked out for the feature
    └── API_REFERENCE.md   # APIs and tech-stack references gathered for the feature
```

## Starting a new experiment

1. Copy `sample_experiment/` and rename it after the feature, e.g. `packing_list_prefill/`.
2. Write the feature's functional and non-functional requirements at the top of `API_REFERENCE.md`, then gather references (see that file).
3. Work out `FINDINGS.md` before writing any serious code.
4. Build the experiment in `script.py`, and update `FINDINGS.md` with what you learn.
