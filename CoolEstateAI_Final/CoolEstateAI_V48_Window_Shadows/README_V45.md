# CoolEstate AI V4.5 — Per-floor Facades

- Repeats glazing, horizontal overhangs, and vertical fins independently for each complete 3 m floor.
- Keeps a sill and spandrel gap so glazing and shading do not cross storey boundaries.
- Applies height exaggeration consistently to storey heights.
- Keeps outward projections of shading panels, original Buildings.sg data loading, and AI API components.
- WWR remains an illustrative control rather than a physically precise facade area calculation.

## Run

Copy your existing `data/sg_buildings_v5.zip` or `data/estates/*.geojson` into this project's `data` directory.

```
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Test at 200 m, Design only, 10 buildings, WWR 50%, horizontal 1.5 m, vertical 1.0 m.
