# CoolEstate AI V4.4 — outward-projecting shading geometry

This is a surgical update to the user-uploaded `app(2).py`.

## Fix
- Blue glazing is a vertical rectangle parallel to the wall.
- Yellow horizontal shade is a 0.20 m thick horizontal cuboid extending outward by the slider depth.
- Purple vertical fins are 0.16 m thick vertical cuboids extending outward by the slider depth.
- Each of the six prism faces is separately shaded to communicate depth.
- Depth testing is enabled to reduce through-building overlays.
- Facade outward normal is computed from the footprint edge and approximate centroid.

## Windows
1. Copy the `data` directory from your working project into this folder (the full Buildings.sg dataset is NOT bundled).
2. `python -m pip install -r requirements.txt`
3. `python -m streamlit run app.py`
4. Test Clementi, 200m, Design only, horizontal=2m, vertical=1.5m, WWR=60%, zoom and orbit.

## Limits
The facade geometry and risk scores are conceptual and are not BIM or validated solar/thermal simulation. Only `app.py` was supplied for this update; other supporting files are carried over from the prior AI Ready package. Browser rendering has not been verified.
