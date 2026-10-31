"""Direct-beam shadows projected from 3D facade shade solids onto glazing.
Local x is metres along wall, y is outward normal, z is metres up.
Only local facade self-shading is represented (no occlusion from other buildings).
"""
import math


def _hull(points):
    pts = sorted(set((round(x, 7), round(z, 7)) for x, z in points))
    if len(pts) < 3:
        return []
    def cross(o,a,b): return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lo=[]
    for p in pts:
        while len(lo)>1 and cross(lo[-2],lo[-1],p)<=0: lo.pop()
        lo.append(p)
    hi=[]
    for p in reversed(pts):
        while len(hi)>1 and cross(hi[-2],hi[-1],p)<=0: hi.pop()
        hi.append(p)
    return lo[:-1]+hi[:-1]


def _clip(poly, xmin, xmax, zmin, zmax):
    for axis, limit, keep_greater in [(0,xmin,True),(0,xmax,False),(1,zmin,True),(1,zmax,False)]:
        if not poly: return []
        result=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            av=a[axis]-limit; bv=b[axis]-limit
            ina=av>=-1e-9 if keep_greater else av<=1e-9
            inb=bv>=-1e-9 if keep_greater else bv<=1e-9
            if ina != inb:
                t=(limit-a[axis])/(b[axis]-a[axis])
                result.append((a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])))
            if inb: result.append(b)
        poly=result
    return poly


def _contains(poly,x,z):
    inside=False
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if (a[1]>z)!=(b[1]>z) and x < (b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0]:
            inside=not inside
    return inside


def project_shade_shadows(elevation, sun_azimuth, wall_azimuth, width, zbottom, ztop,
                          horizontal_depth, vertical_depth, shade_z_bottom, shade_z_top,
                          fin_z_bottom, fin_z_top, floor_scale=1.0):
    """Return clipped shadow polygons in (wall-x metres, display-z metres), coverage, sunlit.
    Window local x spans [0,width]. All dimensions except z are physical metres.
    """
    if elevation<=0 or width<=0 or ztop<=zbottom: return [],0.0,False
    rel=math.radians((sun_azimuth-wall_azimuth+180)%360-180)
    normal=math.cos(math.radians(elevation))*math.cos(rel)
    if normal<=1e-5: return [],0.0,False
    tangential=math.cos(math.radians(elevation))*math.sin(rel)
    upward=math.sin(math.radians(elevation))
    # A ray from the shade back to the glazing moves opposite to sun direction.
    # Shade surfaces are outside glazing by a strictly positive normal offset.
    def projected_cuboid(xlo,xhi,zlo,zhi,near,far):
        pts=[]
        for x in (xlo,xhi):
            for z in (zlo,zhi):
                for d in (near,far):
                    pts.append((x-d*tangential/normal, z-d*upward/normal*floor_scale))
        return _clip(_hull(pts),0,width,zbottom,ztop)
    polys=[]
    if horizontal_depth>0:
        p=projected_cuboid(-.12,width+.12,shade_z_bottom,shade_z_top,
                           .02,.02+horizontal_depth)
        if len(p)>=3: polys.append(p)
    if vertical_depth>0:
        for x in (0,width):
            p=projected_cuboid(x-.08,x+.08,fin_z_bottom,fin_z_top,
                               .03,.03+vertical_depth)
            if len(p)>=3: polys.append(p)
    # Union coverage estimated on a deterministic fine grid, avoiding double counting
    # overlapping overhang and fin shadows. Rendering uses clipped true polygons.
    n=28
    covered=sum(any(_contains(p,width*(i+.5)/n,zbottom+(ztop-zbottom)*(j+.5)/n)
                    for p in polys) for i in range(n) for j in range(n))
    return polys,covered/(n*n),True
