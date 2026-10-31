# CoolEstate AI V4.6 — Solar & Facade Shading Explorer

Based on the working V4.5 floor-by-floor facade version. Adds a Singapore local date/time selector, NOAA approximate solar elevation and azimuth, a gold 3D sun-direction indicator, dark-blue projected direct-beam shade patches on each window, and a sun-facing glazing shade-percentage summary.

## Run (Windows)
1. Copy your **existing `data/` directory** into this project. Building GeoJSON is not bundled.
2. `python -m pip install -r requirements.txt`
3. `python -m streamlit run app.py`
4. Set **Design only**, **Clementi**, radius **200 m**, WWR **50%**, horizontal shade **1.5 m**, vertical fin **1.0 m**; choose **21 June**, **14:00 SGT**. Try 09:00 vs 16:00 and facade orientation East/West.

## Important limitations
- Solar angles use the approximate NOAA fractional-year formula; no live weather is used.
- The window shade patches are a **simplified geometric direct-beam proxy**, not raytraced shadows, actual irradiance, energy savings, UTCI or temperature changes.
- Shade estimates omit building-to-building obstructions, diffuse light, vegetation, reflections, true window construction, and precise facade geometry.
- Buildings.sg footprint data must be supplied separately and reused according to its licensing conditions.
- Outdoor heat-risk score remains separate from facade shading.
- The two map views remain independently navigable.
