# CoolEstate AI V4 — Facade design controls

## Run on Windows

```bat
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Local buildings.sg data

If you already uploaded `sg_buildings_v5.zip` in the previous project, copy it from the previous `data` folder into this version's `data` folder (create it if needed). Otherwise upload the ZIP through the dashboard once.

## New controls

- Window-to-wall ratio (WWR), 20–80%: adjusts blue window marker height on selected facade edges.
- Horizontal shading depth, 0–2.5 m: adds yellow projected canopy outlines.
- Vertical fin depth, 0–2.0 m: enables purple vertical fin markers. (Visual line thickness is fixed; depth is reflected in proxy score, not represented as full 3D solid fin.)
- Facade visualization building count: caps rendering workload.
- Solar exposure proxy: illustrative separate metric; **not** temperature, UTCI, energy, or daylight simulation.

The base outdoor heat-risk score is intentionally **not** changed by facade sliders, because facade WWR does not directly imply a validated outdoor cooling effect. Facade geometry is concept art, not BIM.
