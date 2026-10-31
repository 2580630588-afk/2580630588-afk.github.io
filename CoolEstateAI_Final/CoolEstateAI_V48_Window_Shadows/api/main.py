"""Read-only public API for CoolEstate AI. Data is illustrative, not climate simulation."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from cooling_model import risk, facade_exposure

ROOT = Path(__file__).resolve().parents[1]
ESTATES = {'Jurong West': (1.3398,103.7048), 'Clementi': (1.3151,103.7651), 'Tampines': (1.3535,103.9447)}
app = FastAPI(title='CoolEstate AI Public API',version='1.0.0',description='Urban cooling concept explorer. Scores are heuristic design proxies, not measured thermal comfort, temperature or validated physical simulations.', contact={'name':'CoolEstate AI project'})
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['GET','POST'],allow_headers=['Content-Type'])

class Scenario(BaseModel):
    estate: str = Field(default='Clementi', description='Jurong West, Clementi, or Tampines')
    greenery: float = Field(default=30, ge=0, le=100)
    shading: float = Field(default=25, ge=0, le=100)
    density: float = Field(default=65, ge=0, le=100)
    wwr: float = Field(default=40, ge=20, le=80, description='Window-to-wall ratio in percent')
    horizontal_shading_m: float = Field(default=0, ge=0, le=2.5)
    vertical_shading_m: float = Field(default=0, ge=0, le=2.0)

@app.get('/',tags=['Discoverability'])
def home():
    return {'name':'CoolEstate AI API','docs':'/docs','openapi':'/openapi.json','project':'/v1/project','llms':'/llms.txt','notice':'Illustrative scores; no measured or simulated temperatures.'}

@app.get('/health',tags=['Discoverability'])
def health(): return {'status':'ok'}

@app.get('/llms.txt',response_class=PlainTextResponse,tags=['Discoverability'])
def llms(): return (ROOT/'public'/'llms.txt').read_text(encoding='utf-8')

@app.get('/v1/project',tags=['Discoverability'])
def project():
    return {'name':'CoolEstate AI','purpose':'Explore illustrative urban cooling and facade design scenarios in Singapore HDB estates','estates':list(ESTATES),'dashboard':'Streamlit dashboard (set URL after deployment)','data_source':'Buildings.sg local GeoJSON when provided; heights may be estimated','model_type':'Heuristic, not a validated physical model','outdoor_risk_formula':'0.45*(100-greenery)+0.35*(100-shading)+0.20*density','facade_proxy_formula':'clip(35+0.6*(wwr-40)-10*horizontal_shading_m-7*vertical_shading_m,0,100)','limitations':['Not actual air temperature or UTCI','No solar path, CFD or thermal simulation','Proposed vegetation and shading positions are schematic'],'endpoints':['/v1/estates','/v1/scenarios/evaluate','/v1/buildings','/openapi.json']}

@app.get('/v1/estates',tags=['Estates'])
def estates(): return {'estates':[{'name':name,'latitude':lat,'longitude':lon} for name,(lat,lon) in ESTATES.items()]}

@app.post('/v1/scenarios/evaluate',tags=['Scenarios'])
def evaluate(s:Scenario):
    if s.estate not in ESTATES: raise HTTPException(status_code=422,detail=f'Unknown estate. Choose from {list(ESTATES)}')
    baseline_risk=risk(30,25,s.density)
    design_risk=risk(s.greenery,s.shading,s.density)
    baseline_facade=facade_exposure(40,0,0)
    design_facade=facade_exposure(s.wwr,s.horizontal_shading_m,s.vertical_shading_m)
    recommendations=[]
    if s.greenery<45: recommendations.append('Explore more tree canopy on pedestrian routes.')
    if s.shading<50: recommendations.append('Explore covered walkways and shaded seating.')
    if s.wwr>55: recommendations.append('Review glazing ratio and solar gains subject to daylight needs.')
    if s.horizontal_shading_m<.8: recommendations.append('Evaluate horizontal shading with orientation-specific solar studies.')
    return {'estate':s.estate,'input':s.model_dump(),'baseline':{'outdoor_risk_index':baseline_risk,'facade_solar_exposure_proxy':baseline_facade},'design':{'outdoor_risk_index':design_risk,'facade_solar_exposure_proxy':design_facade},'difference':{'outdoor_risk_index_points':round(design_risk-baseline_risk,1),'facade_proxy_points':round(design_facade-baseline_facade,1)},'recommendations':recommendations,'units':'Index points out of 100, not degrees Celsius','method':'Illustrative heuristic; not calibrated, validated, or measured'}

@app.get('/v1/buildings',tags=['Buildings'])
def buildings(estate: Annotated[str,Query(description='Estate name')]='Clementi',limit:Annotated[int,Query(ge=1,le=300)]=100):
    if estate not in ESTATES: raise HTTPException(status_code=422,detail='Unknown estate')
    file=ROOT/'data'/'estates'/(estate.lower().replace(' ','_')+'.geojson')
    if not file.exists(): raise HTTPException(status_code=503,detail='No local building extract deployed. Run scripts/prepare_estates.py with sg_buildings_v5.zip and commit data/estates/*.geojson.')
    payload=json.loads(file.read_text(encoding='utf-8'))
    features=payload.get('features',[])[:limit]
    return {'type':'FeatureCollection','features':features,'metadata':{'estate':estate,'total_available':len(payload.get('features',[])),'returned':len(features),'source':'Buildings.sg (check source attribution and redistribution license)','heights':'Source values or estimates; not uniformly surveyed'}}
