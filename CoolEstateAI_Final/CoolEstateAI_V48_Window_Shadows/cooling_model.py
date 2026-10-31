"""Shared illustrative scoring functions. NOT physical thermal simulation."""

def risk(greenery: float, shading: float, density: float) -> float:
    return round(.45 * (100 - greenery) + .35 * (100 - shading) + .20 * density, 1)

def facade_exposure(wwr: float, horizontal_m: float, vertical_m: float) -> float:
    return round(max(0, min(100, 35 + .6 * (wwr - 40) - 10 * horizontal_m - 7 * vertical_m)), 1)
