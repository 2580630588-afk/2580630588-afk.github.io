"""Extract small estate subsets from Buildings.sg ZIP for API deployment."""
import json, math, sys, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ESTATES={'Jurong West':(1.3398,103.7048),'Clementi':(1.3151,103.7651),'Tampines':(1.3535,103.9447)}

def main(path):
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.lower().endswith(('.geojson','.json'))]
        if not names: raise ValueError('No GeoJSON in ZIP')
        with z.open(max(names,key=lambda n:z.getinfo(n).file_size)) as f: dataset=json.load(f)
    if dataset.get('type')!='FeatureCollection': raise ValueError('Not a FeatureCollection')
    output=ROOT/'data'/'estates'; output.mkdir(parents=True,exist_ok=True)
    for name,(lat,lon) in ESTATES.items():
        radius=700; dy=radius/111000; dx=radius/(111000*math.cos(math.radians(lat)))
        selected=[]
        for feature in dataset['features']:
            geo=feature.get('geometry') or {}
            if geo.get('type')=='Polygon': polys=[geo.get('coordinates',[])]
            elif geo.get('type')=='MultiPolygon': polys=geo.get('coordinates',[])
            else: continue
            for polygon in polys:
                if not polygon or not polygon[0]:continue
                ring=polygon[0]
                if len(ring)<4:continue
                xs=[p[0] for p in ring];ys=[p[1] for p in ring]
                if max(xs)<lon-dx or min(xs)>lon+dx or max(ys)<lat-dy or min(ys)>lat+dy:continue
                selected.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':[ring]},'properties':feature.get('properties') or {}})
                break
            if len(selected)>=2000:break
        file=output/(name.lower().replace(' ','_')+'.geojson')
        file.write_text(json.dumps({'type':'FeatureCollection','features':selected},separators=(',',':')),encoding='utf-8')
        print(f'{name}: {len(selected)} features -> {file} ({file.stat().st_size/1e6:.2f} MB)')
if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('Usage: python scripts/prepare_estates.py data/sg_buildings_v5.zip')
    main(sys.argv[1])
