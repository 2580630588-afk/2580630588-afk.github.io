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

def risk(g,s,d): return round(.45*(100-g)+.35*(100-s)+.2*d,1)

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
    show_facade=st.checkbox('Show 3D facade elements',value=True)
    st.caption('WWR and fins represent concept facade geometry; they are not surveyed building features.')
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
def facade_exposure(wwr_pct, horizontal_m, vertical_m):
    return round(max(0,min(100, 35 + 0.6*(wwr_pct-40) - 10*horizontal_m - 7*vertical_m)),1)
facade_base=facade_exposure(40,0,0)
facade_design=facade_exposure(wwr,horizontal_depth,vertical_depth)

a,b,c=st.columns(3)
a.metric('Baseline risk index',f'{base}/100')
b.metric('Design risk index',f'{design}/100',delta=f'{design-base:+.1f} points',delta_color='inverse')
c.metric('Outdoor risk index reduction',f'{base-design:+.1f} points')
st.caption(f'Facade solar-exposure proxy (separate from outdoor heat risk): baseline {facade_base:.1f}/100 → design {facade_design:.1f}/100. Lower is better; illustrative only.')
st.info('Risk index is a heuristic design score, NOT an observed air temperature, UTCI, or simulated cooling in °C. Building colors illustrate the scenario score, not measured building-level heat.')

lat,lon=ESTATES[estate]
st.markdown('### 🗺️ Singapore building data')
if BUILDINGSG_FILE.exists():
    dataset_bytes=BUILDINGSG_FILE.read_bytes()
else:
    uploaded=st.file_uploader('Upload buildings.sg sg_buildings_v5.zip (or GeoJSON) once',type=['zip','geojson','json'])
    if uploaded is not None:
        dataset_bytes=uploaded.getvalue()
        BUILDINGSG_FILE.write_bytes(dataset_bytes)
        st.success('Dataset saved locally for future sessions.')
    else:
        dataset_bytes=None

if dataset_bytes:
    try:
        with st.spinner('Loading local Singapore building geometry...'):
            features=read_buildings_sg(dataset_bytes)
            buildings=clip_buildings(features,lat,lon,radius)
        data_mode='buildings.sg'
        st.success(f'{len(buildings)} buildings in {estate} · {len(features):,} total features loaded locally from Buildings.sg · no live Overpass calls')
        if not buildings: st.warning('No buildings found in the selected area. Check GeoJSON coordinate system (must be WGS84 longitude/latitude).')
    except Exception as e:
        buildings=[];data_mode='error'
        st.error(f'Could not read Buildings.sg dataset: {e}')
else:
    buildings=[];data_mode='missing'
    st.warning('Please download sg_buildings_v5.zip from the Buildings.sg GitHub repository and upload it above. No fake buildings are displayed.')

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

def facade_geometry(rows, max_buildings, window_ratio, horizontal_m, vertical_m):
    """Generate visible 3D paths on a long facade edge. Geometry is illustrative.

    Deck.gl PathLayer accepts [longitude, latitude, altitude] coordinates.
    Horizontal louvres and vertical fins use simplified line glyphs (not solids).
    """
    windows=[]; horizontal=[]; vertical=[]
    # Select larger/taller buildings first for legibility, cap complexity.
    candidates=sorted(rows,key=lambda r:r['height'],reverse=True)[:max_buildings]
    for row in candidates:
        polygon=row['polygon']
        if len(polygon)<3: continue
        edges=[]
        for a,b in zip(polygon[:-1],polygon[1:]):
            dx=(b[0]-a[0])*111000*math.cos(math.radians(a[1]))
            dy=(b[1]-a[1])*111000
            edges.append((math.hypot(dx,dy),a,b))
        if not edges:continue
        length,a,b=max(edges,key=lambda x:x[0])
        if length<5:continue
        height=row['height']*exaggeration
        floors=max(1,min(12,int(height/3.6)))
        # Window bars: their length varies with WWR. The proxy does not model full facade glazing.
        count=max(2,min(10,int(length/7)))
        for j in range(count):
            t=(j+0.5)/count
            x=a[0]+(b[0]-a[0])*t; y=a[1]+(b[1]-a[1])*t
            bottom=height*0.14
            top=bottom+(height*0.76)*(window_ratio/100)
            windows.append({'path':[[x,y,bottom],[x,y,top]],'name':row['name']})
        # Shade geometry placed at the top of a visible window zone, offset outward in plan.
        midz=height*0.70
        length_factor=horizontal_m/2.5
        if horizontal_m>0:
            nx=-(b[1]-a[1]); ny=(b[0]-a[0]); norm=math.hypot(nx,ny) or 1
            # Use local metre-to-degree conversion; direction is purely conceptual.
            offset_e=(nx/norm)*horizontal_m
            offset_n=(ny/norm)*horizontal_m
            ax=a[0]+offset_e/(111000*math.cos(math.radians(a[1])))
            ay=a[1]+offset_n/111000
            bx=b[0]+offset_e/(111000*math.cos(math.radians(b[1])))
            by=b[1]+offset_n/111000
            horizontal.append({'path':[[a[0],a[1],midz],[ax,ay,midz],[bx,by,midz],[b[0],b[1],midz]],'name':row['name']})
        if vertical_m>0:
            for t in [0.2,0.4,0.6,0.8]:
                x=a[0]+(b[0]-a[0])*t;y=a[1]+(b[1]-a[1])*t
                vertical.append({'path':[[x,y,height*.18],[x,y,height*.18+height*.65]],'name':row['name']})
    return windows,horizontal,vertical

def draw_map(rows,key,proposed=False):
    layers=[]
    if rows:
        layers.append(pdk.Layer('PolygonLayer',id=f'buildings-{key}',data=pd.DataFrame(rows),
            get_polygon='polygon',get_elevation='display_height',get_fill_color='color',
            extruded=True,pickable=True,auto_highlight=True,opacity=.83))
    if proposed and show_facade and rows:
        windows,horizontal,vertical=facade_geometry(rows,facade_scope,wwr,horizontal_depth,vertical_depth)
        if windows:
            layers.append(pdk.Layer('PathLayer',id=f'windows-{key}',data=windows,get_path='path',get_color=[53,180,245,245],get_width=4,width_min_pixels=2,pickable=True))
        if horizontal:
            layers.append(pdk.Layer('PathLayer',id=f'horizontal-{key}',data=horizontal,get_path='path',get_color=[255,218,71,255],get_width=7,width_min_pixels=3,pickable=True))
        if vertical:
            layers.append(pdk.Layer('PathLayer',id=f'vertical-{key}',data=vertical,get_path='path',get_color=[210,95,235,255],get_width=6,width_min_pixels=3,pickable=True))
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
st.caption('Facade windows, horizontal shades and vertical fins are schematic line representations, not accurate facade BIM or physically simulated shading. Proposed trees and shade are schematic 3D markers and may overlap buildings or roads; they do not represent buildable locations. Building footprints: Buildings.sg (City Syntax Lab, NUS; upstream sources include OSM). Heights: source attributes or estimates. Spatial color variation is a deterministic illustrative proxy based on geometry and position, NOT building-level observations, UTCI, CFD, or a validated temperature model. The two maps are independently navigable.')

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
    st.markdown('**Buildings:** Buildings.sg GeoJSON (City Syntax Lab, NUS), stored locally in `data/sg_buildings_v5.zip`; no Overpass requests. Cite Buildings.sg and original data contributors; verify source license before redistribution. **Building heights:** OSM height tags when available; estimated from building:levels × 3m otherwise; 12m fallback where both are missing. **Risk score:** weighted heuristic from user-provided design scores; not calibrated against air temperature or thermal comfort. **Map:** CARTO Positron basemap. **Spatial colors:** optional deterministic geometry/location variation for storytelling only, not physical heat simulation. **Trees and shade:** schematic proposed placements, not sourced from OSM, not validated for constructability or shadow geometry. **Facade controls:** geometric illustrations and a separate heuristic solar-exposure proxy; no orientation-specific sun-path analysis, daylight simulation, energy model or indoor thermal comfort validation. **No building-specific heat measurements are claimed.**')
