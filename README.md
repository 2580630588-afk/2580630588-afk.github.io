# BPS5231 window strategy transfer study

Start with `deliverables/操作步骤与答辩指南.md`.

Submission: editable slides, three-page paper, source code and a 144-case completed simulation experiment.
Outcome is **cooling thermal demand**, not measured EUI or actual HVAC electricity.

## Reproduce analysis
```
python -m pip install -r requirements.txt
python scripts/study.py analyze
python scripts/summarize.py
```

## Reproduce simulation
Download EnergyPlus 24.2 from its official GitHub release. Original IDF and IWEC weather are included with attribution.
```
python scripts/study.py prepare
python scripts/study.py run --energyplus /absolute/path/to/energyplus --scope pilot --workers 2
python scripts/study.py run --energyplus /absolute/path/to/energyplus --scope full --workers 2
python scripts/study.py analyze
python scripts/summarize.py
python scripts/build_documents.py
```

The bundled CSV outputs allow reproduction of the ML evaluation without EnergyPlus. Model binaries, node_modules and large intermediate SQL files are excluded from the ZIP. All 144 generated IDF files and compact simulation logs are included. `scripts/build_slides.mjs` is optional and uses `@oai/artifact-tool` 2.8.84; editing the delivered PPTX requires no build tooling.

## Scope and provenance
Office template: https://github.com/City-Syntax/buildings.sg/blob/main/download/06_Office_SGP_2025_V5.idf
Weather: https://github.com/ladybug-tools/uwg/blob/master/resources/SGP_Singapore.486980_IWEC.epw
Source hashes: `results/input_hashes.json`. Engine provenance: `results/full_provenance.json`.
Generated data are research simulations under stated assumptions. Cite upstream model/data providers; no new licence is asserted over upstream assets.
