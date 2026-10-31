"""Approximate NOAA solar geometry and schematic facade shading, no weather inputs."""
import math
from datetime import datetime

def solar_position(lat, lon, local_dt, utc_offset=8):
    """Return solar elevation and azimuth (degrees, clockwise from north).
    NOAA fractional-year approximation; suitable for conceptual visualization.
    """
    n=local_dt.timetuple().tm_yday
    hour=local_dt.hour+local_dt.minute/60+local_dt.second/3600
    gamma=2*math.pi/365*(n-1+(hour-12)/24)
    eq=229.18*(0.000075+0.001868*math.cos(gamma)-0.032077*math.sin(gamma)-0.014615*math.cos(2*gamma)-0.040849*math.sin(2*gamma))
    decl=(0.006918-0.399912*math.cos(gamma)+0.070257*math.sin(gamma)-0.006758*math.cos(2*gamma)+0.000907*math.sin(2*gamma)-0.002697*math.cos(3*gamma)+0.00148*math.sin(3*gamma))
    tst=(hour*60+eq+4*lon-60*utc_offset)%1440
    ha=math.radians(tst/4-180)
    phi=math.radians(lat)
    sin_el=math.sin(phi)*math.sin(decl)+math.cos(phi)*math.cos(decl)*math.cos(ha)
    elevation=math.degrees(math.asin(max(-1,min(1,sin_el))))
    east=-math.cos(decl)*math.sin(ha)
    north=math.cos(phi)*math.sin(decl)-math.sin(phi)*math.cos(decl)*math.cos(ha)
    azimuth=(math.degrees(math.atan2(east,north))+360)%360
    return elevation,azimuth

def shade_fractions(elevation, sun_azimuth, wall_azimuth, horizontal_depth, vertical_depth, window_height, window_width):
    """Schematic direct-beam shadow fractions on one window (no obstruction/sky model).
    Returns (horizontal_fraction, vertical_fraction, combined_fraction, facing_sun).
    """
    if elevation<=0: return 0.,0.,0.,False
    relative=math.radians((sun_azimuth-wall_azimuth+180)%360-180)
    cos_rel=math.cos(relative)
    if cos_rel<=0: return 0.,0.,0.,False
    elev=math.radians(elevation)
    # Wall-normal sun incidence: high altitude creates larger overhang shadows.
    h=min(1., max(0., horizontal_depth*math.tan(elev)/(max(.08,cos_rel)*max(.2,window_height))))
    # Low-angle oblique sun produces a larger side-fin shadow.
    v=min(1., max(0., vertical_depth*abs(math.tan(relative))/max(.3,window_width)))
    return h,v,1-(1-h)*(1-v),True
