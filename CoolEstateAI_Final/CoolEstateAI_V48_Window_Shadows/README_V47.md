# CoolEstate AI V4.7 — Building Cast Shadows

- Removed the 3D sun-direction line and marker.
- Replaced decorative window shadow patches with building footprint ground shadow projections.
- Date and Singapore local time still control sun altitude/azimuth.
- The Before and After maps display the same building shadows because buildings are unchanged. Facade shading affects only the separate schematic facade proxy, not building-scale ground shadows.
- Ground shadow polygons are an approximate convex envelope of the building footprint and roof projection. They do not account for occlusion, terrain, tree shadows, or actual shading from facade fins. Building height exaggeration does not affect calculated shadows. At solar elevation <= 2 degrees, shadows are hidden.

## Run
Copy your existing `data/` folder to this project, then run:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
