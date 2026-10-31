# CoolEstate AI V4.8 — Projected Window Shadows

- Keeps all V4.7 functions and local Buildings.sg data workflow.
- Toggle **Show projected shadows on windows** (enabled by default).
- Computes sun-facing facades and projects actual overhang/fin cuboid vertices onto vertical glazing using the solar direction, clips each shadow to its window, and draws the resulting dark-blue polygons.
- Repeats separately on every 3 m storey; both shade depths and date/time update the shadows.
- Shadow coverage is estimated from the union of projected polygons via a 28 × 28 per-window sampling grid, not a full ray-tracing simulation.
- No neighboring buildings, terrain, glazing optics, diffuse light, or annual thermal simulation are modeled.

## Run
Copy the previous version's `data/` folder (including the licensed Buildings.sg dataset) into this folder.

```
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Test: Clementi, 200 m, Design only, WWR 50%, horizontal 1.5 m, vertical 1.0 m; compare 09:00, 12:00 and 16:00 SGT.
