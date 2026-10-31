import streamlit as st
import pandas as pd
import pydeck as pdk
import requests
import math
import time
import copy
import random
import json
import zipfile
import io
import os
from cooling_model import risk, facade_exposure
from solar_model import solar_position, shade_fractions
from facade_shadows import project_shade_shadows
from datetime import date, datetime, time as dt_time
from pathlib import Path

st.set_page_config(page_title='CoolEstate AI | Urban Cooling Digital Twin',layout='wide',page_icon='🌳')
st.markdown("""<style>
.block-container {padding-top:1.4rem; max-width:1550px;}
h1,h2,h3 {letter-spacing:-0.035em;}
[data-testid="stMetric"] {background:#f2f7f6;border:1px solid #e0ebe8;border-radius:12px;padding:12px 16px;}
[data-testid="stSidebar"] {background:#f5f8f7;}
</style>""", unsafe_allow_html=True)
ESTATES={'Jurong West':(1.3398,103.7048),'Clementi':(1.3151,103.7651),'Tampines':(1.3535,103.9447)}
ENDPOINTS=['https://overpass.private.coffee/api/interpreter','https://overpass.kumi.systems/api/interpreter','https://overpass-api.de/api/interpreter','https://overpass.nchc.org.tw/api/interpreter']


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def cache_path(estate, radius):
    safe = estate.lower().replace(" ", "_")
    return DATA_DIR / f"{safe}_{radius}m_osm.json"


def fetch_osm(lat,lon,radius):
    # Keep requests short: a failed public endpoint should never block the dashboard for minutes.
    dy=radius/111000
    dx=radius/(111000*math.cos(math.radians(lat)))
    bbox=f'{lat-dy:.6f},{lon-dx:.6f},{lat+dy:.6f},{lon+dx:.6f}'
    query=f'[out:json][timeout:12];way["building"]({bbox});out geom;'
    failures=[]
    headers={'User-Agent':'CoolEstateAI/3.0 (urban cooling hackathon prototype)', 'Accept':'application/json'}
    # Use only two endpoints per attempt. Users can retry later if both are busy.
    for url in [ENDPOINTS[2], ENDPOINTS[0]]:
        try:
            response=requests.get(url,params={'data':query},timeout=(4,14),headers=headers)
            response.raise_for_status()
            payload=response.json()
            if not isinstance(payload,dict) or not isinstance(payload.get('elements'),list):
                raise ValueError('Unexpected Overpass response format')
            return payload['elements'],url
        except (requests.RequestException,ValueError) as ex:
            failures.append(f'{url}: {type(ex).__name__}: {str(ex)[:180]}')
    raise RuntimeError('\n'.join(failures))


def parse_osm_elements(elements):
    buildings=[]
    for el in elements[:1800]:
        geo=el.get('geometry',[])
        if len(geo)<4: continue
        poly=[[pt['lon'],pt['lat']] for pt in geo]
        if poly[0]!=poly[-1]: poly.append(poly[0])
        tags=el.get('tags',{})
        height=None; quality='unknown'
        try:
            height=float(str(tags.get('height','')).replace('m','').strip()); quality='OSM height'
        except (ValueError,TypeError): pass
        if height is None:
            try:
                height=float(tags['building:levels'])*3.0; quality='levels × 3m estimate'
            except (ValueError,KeyError,TypeError): height=12.0; quality='12m display fallback'
        height=max(3,min(height,250))
        buildings.append({'polygon':poly,'height':height,'name':tags.get('name') or tags.get('addr:street') or f'OSM building {el["id"]}', 'source':quality,'osm_id':el['id']})
    return buildings


def read_local_osm(estate, radius):
    path=cache_path(estate,radius)
    if not path.exists(): return None
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
        if payload.get('buildings'):
            return payload['buildings'], payload.get('source','Local OSM cache'), path
    except (OSError,ValueError,TypeError):
        return None
    return None


def save_local_osm(estate, radius, buildings, source):
    path=cache_path(estate,radius)
    payload={'estate':estate,'radius_m':radius,'source':source,'saved_at':time.strftime('%Y-%m-%d %H:%M:%S'),'buildings':buildings}
    path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    return path


def offline_demo_buildings(lat, lon, radius):
    """Schematic fallback blocks for UI continuity; these are NOT real OSM footprints."""
    rng=random.Random(f'offline-{lat:.4f}-{lon:.4f}-{radius}')
    rows=[]
    count=24
    span=max(90, radius*0.58)
    for i in range(count):
        col=i%6; row=i//6
        east=(col-2.5)*span/3 + rng.uniform(-12,12)
        north=(row-1.5)*span/2 + rng.uniform(-10,10)
        cx=lon+east/(111000*math.cos(math.radians(lat)))
        cy=lat+north/111000
        w=rng.uniform(18,34); h=rng.uniform(18,38)
        dx=w/(2*111000*math.cos(math.radians(lat))); dy=h/(2*111000)
        poly=[[cx-dx,cy-dy],[cx+dx,cy-dy],[cx+dx,cy+dy],[cx-dx,cy+dy],[cx-dx,cy-dy]]
        rows.append({'polygon':poly,'height':rng.choice([12,18,24,30,36,45]),'name':f'Illustrative offline block {i+1}', 'source':'Schematic fallback (not surveyed)', 'osm_id':f'DEMO-{i+1}'})
    return rows



BUILDINGSG_FILE = DATA_DIR / "sg_buildings_v5.zip"

def parse_height(props):
    for key in ("height", "building_height", "Height", "avg_height", "Avg_height", "measuredHeight"):
        try:
            val=float(str(props.get(key, "")).lower().replace("m", "").strip())
            if 2 <= val <= 350: return val, f"Dataset: {key}"
        except (TypeError,ValueError): pass
    for key in ("building_levels", "building:levels", "levels", "storeys", "number_of_storeys"):
        try:
            val=float(props.get(key)) * 3
            if 2 <= val <= 350: return val, f"Estimated: {key} × 3 m"
        except (TypeError,ValueError): pass
    return 12., "12 m visualization fallback"

@st.cache_data(show_spinner=False)
def read_buildings_sg(file_bytes):
    if file_bytes[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            candidates=[n for n in z.namelist() if n.lower().endswith(('.geojson','.json')) and not n.startswith('__MACOSX')]
            if not candidates: raise ValueError('ZIP does not contain GeoJSON')
            with z.open(max(candidates,key=lambda n:z.getinfo(n).file_size)) as f:
                data=json.load(f)
    else: data=json.loads(file_bytes)
    if data.get('type') != 'FeatureCollection': raise ValueError('Expected a GeoJSON FeatureCollection')
    return data['features']

def clip_buildings(features, lat, lon, radius):
    dy=radius/111000
    dx=radius/(111000*math.cos(math.radians(lat)))
    result=[]
    for f in features:
        geom=f.get('geometry') or {}; typ=geom.get('type')
        if typ not in ('Polygon','MultiPolygon'):continue
        polys=[geom.get('coordinates',[])] if typ=='Polygon' else geom.get('coordinates',[])
        props=f.get('properties') or {}
        h,quality=parse_height(props)
        for poly in polys:
            if not poly or not poly[0]: continue
            outer=poly[0]
            if len(outer)<4:continue
            # Fast bounding-box intersection, not a full geometric clip.
            xs=[p[0] for p in outer];ys=[p[1] for p in outer]
            if max(xs)<lon-dx or min(xs)>lon+dx or max(ys)<lat-dy or min(ys)>lat+dy:continue
            if not (-180<=min(xs)<=180 and -90<=min(ys)<=90): continue
            result.append({'polygon':outer,'height':h,
                'name':str(props.get('name') or props.get('addr_housenumber') or props.get('id') or 'Singapore building'),
                'source':quality,'osm_id':str(props.get('id') or props.get('osm_id') or 'Buildings.sg')})
            if len(result)>=5000:return result
    return result

st.title('🌳 CoolEstate AI')
st.caption('Urban Cooling Digital Twin · Buildings.sg open building dataset · Conceptual interventions · Scenario explorer')
with st.sidebar:
    st.header('📍 Estate Selection')
    estate=st.selectbox('Select area',list(ESTATES))
    radius=st.select_slider('Map radius (m)',options=[200,300,500,750,1000,1500],value=500)
    st.header('🌿 Design Controls')
    greenery=st.slider('Greenery score',0,100,30,5)
    shading=st.slider('Shading score',0,100,25,5)
    density=65
    st.caption('Scores are illustrative, not measured site values.')
    st.header('🏢 Facade Design Controls')
    wwr=st.slider('Window-to-wall ratio (WWR, %)',20,80,40,5)
    horizontal_depth=st.slider('Horizontal shading depth (m)',0.0,2.5,0.8,0.1)
    vertical_depth=st.slider('Vertical fin depth (m)',0.0,2.0,0.5,0.1)
    facade_scope=st.slider('Buildings with facade visualization',10,100,45,5)
    facade_orientation=st.selectbox('Facade orientation', ['All orientations','North','East','South','West'],index=0,help='Select facade outward-facing direction; this is geometric orientation, not a solar simulation.')
    show_facade=st.checkbox('Show 3D facade elements',value=True)
    st.caption('3 m per storey: windows and shades repeat on each complete floor. Facade geometry is illustrative, not surveyed.')
    st.header('☀️ Sun & Shading Explorer')
    solar_date=st.date_input('Simulation date (Singapore)',value=date(2026,6,21))
    solar_hour=st.slider('Local time (SGT, 24h)',6.0,19.0,14.0,0.25)
    show_building_shadows=st.checkbox('Show building cast shadows',value=True)
    show_window_shadows=st.checkbox('Show projected shadows on windows', value=True, help='Direct-sun projections of horizontal overhangs and vertical fins onto each window.')
    st.caption('Ground shadows use building footprints, heights and calculated sun angles. Approximate geometric projection, not ray tracing.')
    st.header('🌳 Proposed interventions')
    show_trees=st.checkbox('Show proposed 3D trees',value=True)
    show_shade=st.checkbox('Show proposed shaded walkways',value=True)
    tree_count=st.slider('New trees (conceptual)',0,120,45,5)
    shade_count=st.slider('Shaded walkway segments',0,24,10,2)
    st.caption('Intervention locations are conceptual, not surveyed or engineering-verified.')
    st.header('🗺️ 3D Controls')
    map_mode=st.radio('3D scenario view',['Side by side','Baseline only','Design only'],index=0)
    spatial_variation=st.checkbox('Show illustrative building-level variation',value=True,help='Variation is based on building height and geographic position, not measured heat.')
    pitch=st.slider('Map tilt',0,75,55,5)
    exaggeration=st.slider('Height exaggeration',1.0,3.0,1.5,0.25)
    st.caption('OSM contributors · ODbL 1.0 · successful downloads are saved locally')
    st.caption('Building geometry: local Buildings.sg dataset (no Overpass requests).')

base=risk(30,25,density);design=risk(greenery,shading,density)
# Distinct facade-only illustrative solar-exposure proxy; not outdoor heat comfort.
facade_base=facade_exposure(40,0,0)
facade_design=facade_exposure(wwr,horizontal_depth,vertical_depth)

a,b,c=st.columns(3)
a.metric('Baseline risk index',f'{base}/100')
b.metric('Design risk index',f'{design}/100',delta=f'{design-base:+.1f} points',delta_color='inverse')
c.metric('Outdoor risk index reduction',f'{base-design:+.1f} points')
st.caption(f'Facade solar-exposure proxy (separate from outdoor heat risk): baseline {facade_base:.1f}/100 → design {facade_design:.1f}/100. Lower is better; illustrative only.')
st.info('Risk index is a heuristic design score, NOT an observed air temperature, UTCI, or simulated cooling in °C. Building colors illustrate the scenario score, not measured building-level heat.')

lat,lon=ESTATES[estate]
solar_dt=datetime.combine(solar_date,dt_time(hour=int(solar_hour),minute=int(round((solar_hour%1)*60))))
sun_elevation,sun_azimuth=solar_position(lat,lon,solar_dt)
sa,sb,sc=st.columns(3)
sa.metric('☀️ Solar altitude',f'{sun_elevation:.1f}°')
sb.metric('🧭 Solar azimuth',f'{sun_azimuth:.1f}°')
sc.metric('Sunlight', 'Above horizon' if sun_elevation>0 else 'Below horizon')
st.caption(f'{solar_date.isoformat()} · {solar_dt.strftime("%H:%M")} SGT (UTC+8) · azimuth clockwise from north · NOAA approximate solar position')

st.markdown('### 🗺️ Singapore building data')
estate_extract = DATA_DIR / 'estates' / (estate.lower().replace(' ', '_') + '.geojson')
if estate_extract.exists():
    try:
        with st.spinner('Loading local estate building extract...'):
            features = read_buildings_sg(estate_extract.read_bytes())
            buildings = clip_buildings(features, lat, lon, radius)
        data_mode = 'buildings.sg extract'
        st.success(f'{len(buildings)} buildings in {estate} · offline Buildings.sg estate extract · no live Overpass calls')
    except Exception as e:
        buildings=[]; data_mode='error'
        st.error(f'Could not read estate extract: {e}')
else:
    if BUILDINGSG_FILE.exists():
        dataset_bytes=BUILDINGSG_FILE.read_bytes()
    else:
        uploaded=st.file_uploader('Upload buildings.sg sg_buildings_v5.zip (or GeoJSON)',type=['zip','geojson','json'])
        if uploaded is not None:
            dataset_bytes=uploaded.getvalue()
            BUILDINGSG_FILE.write_bytes(dataset_bytes)
            st.info('Dataset saved on this running instance. Cloud uploads may disappear after redeploy/restart; commit licensed estate extracts for reliable deployment.')
        else:
            dataset_bytes=None
    if dataset_bytes:
        try:
            with st.spinner('Loading local Singapore building geometry...'):
                features=read_buildings_sg(dataset_bytes)
                buildings=clip_buildings(features,lat,lon,radius)
            data_mode='buildings.sg'
            st.success(f'{len(buildings)} buildings in {estate} · {len(features):,} total features loaded locally from Buildings.sg · no live Overpass calls')
        except Exception as e:
            buildings=[];data_mode='error'
            st.error(f'Could not read Buildings.sg dataset: {e}')
    else:
        buildings=[];data_mode='missing'
        st.warning('Add data/estates/*.geojson to the repository, or upload a Buildings.sg dataset here. No fake buildings are displayed.')

# P0: transparent illustrative spatial model. Real OSM geometry; modeled colors only.
def building_risk(row, greenery_score, shading_score, density_score, spatial=True):
    overall = risk(greenery_score, shading_score, density_score)
    if not spatial:
        return overall
    # Fixed per-building spatial variation ensures meaningful comparisons across scenarios.
    # These are visualization proxies, NOT site-specific measured microclimate.
    centroid_lon = sum(p[0] for p in row['polygon'][:-1]) / max(1, len(row['polygon']) - 1)
    centroid_lat = sum(p[1] for p in row['polygon'][:-1]) / max(1, len(row['polygon']) - 1)
    height_effect = 7.0 * (min(row['height'], 80.0) / 80.0 - 0.5)
    location_effect = 5.0 * math.sin(centroid_lon * 1700.0) + 4.0 * math.cos(centroid_lat * 1900.0)
    return round(max(0.0, min(100.0, overall + height_effect + location_effect)), 1)

def risk_color(value):
    if value >= 65: return [222, 83, 68, 215]
    if value >= 45: return [243, 160, 62, 215]
    return [62, 175, 115, 215]

def make_layer_rows(original, green, shade):
    result=[]
    for original_row in original:
        row=original_row.copy()
        score=building_risk(row, green, shade, density, spatial_variation)
        row['risk_score']=score
        row['risk_category']='High' if score>=65 else ('Moderate' if score>=45 else 'Low')
        row['display_height']=row['height']*exaggeration
        row['color']=risk_color(score)
        result.append(row)
    return result

baseline_rows=make_layer_rows(buildings,30,25)
design_rows=make_layer_rows(buildings,greenery,shading)
view=pdk.ViewState(latitude=lat,longitude=lon,zoom=max(12.3, 16.1-math.log2(max(radius,200)/200)),pitch=pitch,bearing=-20)
map_style='https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'
tooltip={'html':'<b>{name}</b><br/>Illustrative risk: {risk_score}/100 ({risk_category})<br/>Height: {height} m<br/>Height source: {source}<br/>OSM ID: {osm_id}', 'style':{'color':'white'}}

def proposed_infrastructure(lat,lon,radius,n_trees,n_shades):
    """Deterministic schematic placement only; not a GIS site suitability analysis."""
    rng=random.Random(f'{lat:.4f}-{lon:.4f}-{radius}')
    trees=[]; shades=[]
    usable=radius*0.76
    for i in range(n_trees):
        east=rng.uniform(-usable,usable)
        north=rng.uniform(-usable,usable)
        x=lon+east/(111000*math.cos(math.radians(lat)))
        y=lat+north/111000
        trees.append({'position':[x,y], 'canopy_position':[x,y,10], 'height':8.0,
                      'canopy_height':11.5,'canopy_radius':5.2,'label':f'Proposed tree {i+1}'})
    for i in range(n_shades):
        east=rng.uniform(-usable,usable)
        north=rng.uniform(-usable,usable)
        length=30
        width=5
        x=lon+east/(111000*math.cos(math.radians(lat)))
        y=lat+north/111000
        dx=length/(2*111000*math.cos(math.radians(lat)))
        dy=width/(2*111000)
        shades.append({'polygon':[[x-dx,y-dy],[x+dx,y-dy],[x+dx,y+dy],[x-dx,y+dy],[x-dx,y-dy]],
                       'elevation':4.2, 'label':f'Proposed covered walkway {i+1}'})
    return trees,shades

def facade_geometry(rows, max_buildings, window_ratio, horizontal_m, vertical_m, orientation='All orientations'):
    """Concept facade components with true 3D vertices in [lon, lat, metres].

    Only outward-facing longest eligible edge of each building is used.
    Horizontal shades and fins are rendered as closed, thickened prisms.
    """
    windows, horizontal, vertical, window_shadows, solar_samples = [], [], [], [], []
    candidates = sorted(rows, key=lambda r: r['display_height'], reverse=True)[:max_buildings]
    def orientation_name(nx, ny):
        if abs(nx) >= abs(ny):
            return 'East' if nx > 0 else 'West'
        return 'North' if ny > 0 else 'South'

    for row in candidates:
        polygon = row['polygon']
        if len(polygon) < 4:
            continue
        ring = polygon[:-1] if polygon[0] == polygon[-1] else polygon
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        lat_scale = 111000
        lon_scale = 111000 * math.cos(math.radians(cy))
        edges = []
        for a, b in zip(ring, ring[1:] + ring[:1]):
            dx, dy = (b[0]-a[0])*lon_scale, (b[1]-a[1])*lat_scale
            length = math.hypot(dx, dy)
            if length < 8:
                continue
            nx, ny = -dy/length, dx/length
            mx, my = (a[0]+b[0])/2, (a[1]+b[1])/2
            if nx*((mx-cx)*lon_scale)+ny*((my-cy)*lat_scale) < 0:
                nx, ny = -nx, -ny
            facing = orientation_name(nx,ny)
            if orientation != 'All orientations' and facing != orientation:
                continue
            edges.append((length,a,b,nx,ny,facing))
        if not edges:
            continue
        length,a,b,nx,ny,facing=max(edges,key=lambda e:e[0])
        wall_azimuth=(math.degrees(math.atan2(nx,ny))+360)%360

        height=row['display_height']
        if height < 8:
            continue
        def pt(t,z,offset=.35):
            return [a[0]+(b[0]-a[0])*t+nx*offset/lon_scale,
                    a[1]+(b[1]-a[1])*t+ny*offset/lat_scale,float(z)]
        def quad(p1,p2,p3,p4):
            return [p1,p2,p3,p4]
        def prism(t0,t1,z0,z1,near,far,collection,kind):
            """Physical cuboid: t runs ALONG wall, z is UP, near->far is OUTWARD.

            Each face has actual 3D [longitude, latitude, altitude] vertices.
            Distinct face colors make depth visible at oblique camera angles.
            """
            if far <= near or t1 <= t0 or z1 <= z0:
                return
            A,B,C,D=pt(t0,z0,near),pt(t1,z0,near),pt(t1,z1,near),pt(t0,z1,near)
            E,F,G,H=pt(t0,z0,far),pt(t1,z0,far),pt(t1,z1,far),pt(t0,z1,far)
            if kind == 'Horizontal shade':
                palette=[[193,132,20,255],[237,177,33,255],[255,210,67,255],
                         [224,156,24,255],[242,183,36,255],[208,143,19,255]]
            else:
                palette=[[126,58,171,255],[170,84,211,255],[151,65,194,255],
                         [192,117,231,255],[164,78,205,255],[120,48,165,255]]
            faces=[quad(A,B,C,D),quad(E,F,G,H),quad(A,B,F,E),
                   quad(D,C,G,H),quad(A,D,H,E),quad(B,C,G,F)]
            for face, color in zip(faces,palette):
                collection.append({'polygon':face,'color':color,'name':row['name'],
                                   'facing':facing,'component':kind,
                                   'projection_m':round(far-near,2)})

        # Storeys are 3.0 m in PHYSICAL height; visualization exaggeration
        # scales their vertical positions exactly as it scales the building.
        # Incomplete rooftop storeys are left unglazed to avoid spanning floors.
        floor_height_m = 3.0
        physical_height = float(row['height'])
        floor_count = int((physical_height + 1e-6) // floor_height_m)
        if floor_count < 1:
            continue
        floor_scale = height / physical_height
        count = max(2, min(8, int(length / 5.5)))
        for floor in range(floor_count):
            floor_bottom = floor * floor_height_m
            # Keep opaque spandrel / sill above and below glazing on every floor.
            # WWR is an illustrative glazing control, not an exact full-wall WWR.
            sill_m = 0.65
            available_m = 2.05
            glazing_height_m = min(available_m, max(0.45, 2.65 * window_ratio / 100.0))
            window_bottom = (floor_bottom + sill_m) * floor_scale
            window_top = (floor_bottom + sill_m + glazing_height_m) * floor_scale
            shade_top = min((floor_bottom + 2.85) * floor_scale,
                            window_top + 0.20 * floor_scale)
            fin_bottom = (floor_bottom + 0.55) * floor_scale
            fin_top = min((floor_bottom + 2.85) * floor_scale,
                          window_top + 0.15 * floor_scale)
            for j in range(count):
                t0 = (j + 0.19) / count
                t1 = (j + 0.81) / count
                windows.append({'polygon':quad(pt(t0,window_bottom,.26),
                                               pt(t1,window_bottom,.26),
                                               pt(t1,window_top,.26),
                                               pt(t0,window_top,.26)),
                                'name':row['name'],'facing':facing,
                                'floor':floor+1,'component':'Window glazing'})
                # Project actual cuboid vertices along incoming sunlight onto each
                # glazing plane, then clip the result to this storey/window module.
                win_width=(t1-t0)*length
                projected, combined, front = project_shade_shadows(
                    sun_elevation, sun_azimuth, wall_azimuth,
                    win_width, window_bottom, window_top,
                    horizontal_m, vertical_m,
                    shade_top-.20*floor_scale, shade_top,
                    fin_bottom, fin_top, floor_scale)
                solar_samples.append({'facing':facing,'sun_facing':front,
                                      'baseline_exposure':1.0 if front else 0.0,
                                      'proposed_exposure':(1-combined) if front else 0.0,
                                      'shade_fraction':combined if front else 0.0})
                if show_window_shadows and front:
                    for poly2d in projected:
                        # Offset 0.06 m outward from glazing to avoid z-fighting.
                        polygon3d=[pt(t0+x/length,z,.32) for x,z in poly2d]
                        window_shadows.append({'polygon':polygon3d,
                            'component':'Projected shade shadow','name':row['name'],
                            'floor':floor+1,'facing':facing})
                if horizontal_m > 0:
                    # One horizontal slab over EACH window on EACH floor.
                    prism(t0-.012,t1+.012,shade_top-.20*floor_scale,
                          shade_top,.28,.28+horizontal_m,
                          horizontal,'Horizontal shade')
                if vertical_m > 0:
                    # Each fin terminates within the SAME floor; no multi-storey fins.
                    half_t = .08 / length
                    for t in (t0,t1):
                        prism(max(0,t-half_t),min(1,t+half_t),
                              fin_bottom,fin_top,.29,.29+vertical_m,
                              vertical,'Vertical fin')
    return windows,horizontal,vertical,window_shadows,solar_samples

def convex_hull(points):
    """Convex envelope of footprint and translated roof outline (metre coordinates)."""
    pts=sorted(set((round(x,4),round(y,4)) for x,y in points))
    if len(pts)<3: return []
    def cross(o,a,b): return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower=[]
    for point in pts:
        while len(lower)>=2 and cross(lower[-2],lower[-1],point)<=0: lower.pop()
        lower.append(point)
    upper=[]
    for point in reversed(pts):
        while len(upper)>=2 and cross(upper[-2],upper[-1],point)<=0: upper.pop()
        upper.append(point)
    return lower[:-1]+upper[:-1]


def building_ground_shadows(rows, elevation, azimuth):
    """Approximate ground cast shadows from vertical extrusions, without obstructions.

    Projection uses true building heights (not visual height exaggeration).
    Low-angle projections are capped for interactive map performance.
    """
    if elevation<=2: return []
    angle=math.radians(azimuth)
    east=-math.sin(angle)
    north=-math.cos(angle)
    shadows=[]
    for row in rows[:1200]:
        ring=row['polygon']
        if len(ring)<3: continue
        h=float(row['height'])
        length=min(500.0,h/max(.035,math.tan(math.radians(elevation))))
        lat0=sum(pt[1] for pt in ring)/len(ring)
        lon0=sum(pt[0] for pt in ring)/len(ring)
        sx=111000*math.cos(math.radians(lat0))
        local=[((pt[0]-lon0)*sx,(pt[1]-lat0)*111000) for pt in ring]
        offset=(east*length,north*length)
        hull=convex_hull(local+[(x+offset[0],y+offset[1]) for x,y in local])
        if len(hull)<3: continue
        poly=[[lon0+x/sx,lat0+y/111000] for x,y in hull]
        shadows.append({'polygon':poly,'name':row['name'],'shadow_m':round(length,1)})
    return shadows


def draw_map(rows,key,proposed=False):
    layers=[]
    if rows and show_building_shadows:
        shadows=building_ground_shadows(rows,sun_elevation,sun_azimuth)
        if shadows:
            layers.append(pdk.Layer('PolygonLayer',id=f'cast-shadows-{key}',
                data=shadows,get_polygon='polygon',get_fill_color=[45,62,84,135],
                stroked=False,pickable=False,opacity=0.60))
    if rows:
        layers.append(pdk.Layer('PolygonLayer',id=f'buildings-{key}',data=pd.DataFrame(rows),
            get_polygon='polygon',get_elevation='display_height',get_fill_color='color',
            extruded=True,pickable=True,auto_highlight=True,opacity=.83))
    if proposed and show_facade and rows:
        windows,horizontal,vertical,window_shadows,solar_samples=facade_geometry(rows,facade_scope,wwr,horizontal_depth,vertical_depth,facade_orientation)
        if windows:
            layers.append(pdk.Layer('SolidPolygonLayer',id=f'window-glass-{key}',data=windows,
                get_polygon='polygon',get_fill_color=[35,176,246,238],
                _full3d=True,side='double',pickable=True,parameters={'depthTest':True,'cull':False}))
        if window_shadows:
            layers.append(pdk.Layer('SolidPolygonLayer',id=f'solar-window-shadows-{key}',
                data=window_shadows,get_polygon='polygon',get_fill_color=[13,43,102,235],
                _full3d=True,side='double',pickable=True,
                parameters={'depthTest':True,'cull':False}))
        if horizontal:
            layers.append(pdk.Layer('SolidPolygonLayer',id=f'horizontal-{key}',data=horizontal,
                get_polygon='polygon',get_fill_color='color',
                _full3d=True,side='double',pickable=True,parameters={'depthTest':True,'cull':False}))
        if vertical:
            layers.append(pdk.Layer('SolidPolygonLayer',id=f'vertical-{key}',data=vertical,
                get_polygon='polygon',get_fill_color='color',
                _full3d=True,side='double',pickable=True,parameters={'depthTest':True,'cull':False}))
    if proposed:
        trees,shades=proposed_infrastructure(lat,lon,radius,tree_count,shade_count)
        if show_trees and trees:
            layers.append(pdk.Layer('ColumnLayer',id=f'tree-trunks-{key}',data=trees,
                get_position='position',get_elevation='height',get_fill_color=[116,89,55,230],
                radius=1.15,disk_resolution=8,extruded=True,pickable=False))
            layers.append(pdk.Layer('ColumnLayer',id=f'tree-canopies-{key}',data=trees,
                get_position='position',get_elevation='canopy_height',get_fill_color=[40,156,102,205],
                radius=5.2,disk_resolution=12,extruded=True,pickable=True))
        if show_shade and shades:
            layers.append(pdk.Layer('PolygonLayer',id=f'shade-{key}',data=shades,
                get_polygon='polygon',get_elevation='elevation',get_fill_color=[57,177,208,195],
                extruded=True,pickable=True,auto_highlight=True))
    st.pydeck_chart(pdk.Deck(layers=layers,initial_view_state=view,map_style=map_style,
        tooltip=tooltip),use_container_width=True,height=530,key=f'map-{key}-{estate}-{radius}')

st.subheader('🏙️ Singapore 3D Heat-Risk Scenario Comparison')
st.caption('🌑 Dark ground polygons = approximate building shadows; dark-blue glazing patches = projected fin and overhang shadows. No sun trajectory is drawn.')
st.caption('🔴 High ≥65 · 🟠 Moderate 45–64.9 · 🟢 Low <45 · 🌳 Trees · 🟦 Walkways · 🔵 Window markers · 🟡 Horizontal shades · 🟣 Vertical fins · Illustrative only')
if map_mode=='Side by side':
    left_map,right_map=st.columns(2)
    with left_map:
        st.markdown('**BEFORE · Baseline**')
        draw_map(baseline_rows,'before')
    with right_map:
        st.markdown('**AFTER · Proposed design**')
        draw_map(design_rows,'after',proposed=True)
elif map_mode=='Baseline only':
    st.markdown('**BEFORE · Baseline**')
    draw_map(baseline_rows,'before')
else:
    st.markdown('**AFTER · Proposed design**')
    draw_map(design_rows,'after',proposed=True)

if buildings:
    counts_before=pd.Series([r['risk_category'] for r in baseline_rows]).value_counts()
    counts_after=pd.Series([r['risk_category'] for r in design_rows]).value_counts()
    st.dataframe(pd.DataFrame({'Risk category':['High','Moderate','Low'],
        'Before (buildings)':[int(counts_before.get(k,0)) for k in ['High','Moderate','Low']],
        'After (buildings)':[int(counts_after.get(k,0)) for k in ['High','Moderate','Low']]}),hide_index=True,use_container_width=True)
if design_rows and show_facade:
    _,_,_,_,samples=facade_geometry(design_rows,facade_scope,wwr,horizontal_depth,vertical_depth,facade_orientation)
    if samples:
        front=[v for v in samples if v['sun_facing']]
        st.subheader('☀️ Projected Window Shading (Direct Sun)')
        if front:
            mean_shade=100*sum(v['shade_fraction'] for v in front)/len(front)
            s1,s2,s3=st.columns(3)
            s1.metric('Sun-facing glazing modules',len(front))
            s2.metric('Projected shaded glazing',f'{mean_shade:.1f}%')
            s3.metric('Estimated direct-beam exposure',f'{100-mean_shade:.1f}%')
            st.progress(min(1.,max(0.,mean_shade/100)))
            st.caption('Projected overhang and fin shadow polygons are clipped to each window. Coverage uses a 28 × 28 sample grid per window to avoid overlap double counting. Excludes neighboring-building occlusion, diffuse radiation and annual energy modelling.')
        else:
            st.info('No selected facade faces the sun at this time, or the sun is below the horizon. Change date/time or facade orientation.')
st.caption('Building shadows are schematic ground projections from building height and solar angles; they do not model neighboring occlusion, terrain or trees. Window shadows model direct-beam self-shading from facade fins and overhangs only. Facade glazing and solid shading repeat independently on each 3 m storey (visualization height exaggeration applied); these are schematic 3D geometries, not accurate facade BIM or physically simulated shading. Orientation is based on geometric outward normals, not solar position. Proposed trees and shade are schematic 3D markers and may overlap buildings or roads; they do not represent buildable locations. Building footprints: Buildings.sg (City Syntax Lab, NUS; upstream sources include OSM). Heights: source attributes or estimates. Spatial color variation is a deterministic illustrative proxy based on geometry and position, NOT building-level observations, UTCI, CFD, or a validated temperature model. The two maps are independently navigable.')

left,right=st.columns(2)
with left:
    st.subheader('📊 Scenario Comparison')
    st.bar_chart(pd.DataFrame({'Risk index':[base,design]},index=['Baseline','Design']),horizontal=True)
    st.dataframe(pd.DataFrame({'Parameter':['Greenery','Shading','Density'],'Baseline':[30,25,density],'Design':[greenery,shading,density]}),hide_index=True,use_container_width=True)
with right:
    st.subheader('🏢 Facade Design Comparison')
    st.dataframe(pd.DataFrame({'Facade parameter':['WWR (%)','Horizontal shade depth (m)','Vertical fin depth (m)','Solar exposure proxy'],'Baseline':[40,0.0,0.0,facade_base],'Design':[wwr,horizontal_depth,vertical_depth,facade_design]}),hide_index=True,use_container_width=True)
    st.caption('A facade-oriented proxy, not UTCI, indoor temperature, energy savings or solar radiation simulation.')
    st.subheader('💡 Cooling Recommendations')
    if greenery<45:st.write('🌳 Increase tree canopy along exposed pedestrian routes.')
    else:st.write('🌳 Prioritize tree placement along high-use walkways.')
    if shading<50:st.write('⛱️ Add covered walkways and shaded seating.')
    else:st.write('⛱️ Connect shaded walking routes across the estate.')
    if wwr>55:st.write('🪟 Consider lower WWR or improved glazing to reduce facade solar exposure (subject to daylight requirements).')
    if horizontal_depth<0.8:st.write('☀️ Explore deeper horizontal shading, especially for solar-exposed facades.')
    if vertical_depth<0.5:st.write('🏢 Explore vertical fins for low-angle solar exposure.')
    st.write('🌬️ Review airflow corridors using a later CFD study before claiming ventilation benefits.')
    st.caption('Rules-based recommendations; no LLM or thermal simulation is running.')
with st.expander('Data sources and methodological limits'):
    st.markdown('**Buildings:** Buildings.sg GeoJSON (City Syntax Lab, NUS), stored locally in `data/sg_buildings_v5.zip`; no Overpass requests. Cite Buildings.sg and original data contributors; verify source license before redistribution. **Building heights:** OSM height tags when available; estimated from building:levels × 3m otherwise; 12m fallback where both are missing. **Risk score:** weighted heuristic from user-provided design scores; not calibrated against air temperature or thermal comfort. **Map:** CARTO Positron basemap. **Spatial colors:** optional deterministic geometry/location variation for storytelling only, not physical heat simulation. **Trees and shade:** schematic proposed placements, not sourced from OSM, not validated for constructability or shadow geometry. **Facade controls:** geometric illustrations and a separate heuristic solar-exposure proxy; no sun-path analysis, daylight simulation, energy model or indoor thermal comfort validation. **No building-specific heat measurements are claimed.**')


st.divider()
st.subheader('🤖 AI-readable data & API')
st.write('This dashboard is interactive for people. A separate public FastAPI service exposes machine-readable methodology, scenario calculations, estate metadata, and (if deployed) a bounded building dataset.')
api_base = os.getenv('COOLESTATE_API_URL', '').rstrip('/')
if api_base:
    st.markdown(f'[API documentation]({api_base}/docs) · [Machine-readable project info]({api_base}/v1/project) · [OpenAPI schema]({api_base}/openapi.json)')
else:
    st.caption('Set COOLESTATE_API_URL in Streamlit Cloud Secrets or environment to display your deployed API links.')
st.caption('Scores are illustrative and should not be represented as measured air temperature, UTCI, or simulated cooling.')
