"""Independent scalar oracle for the AREMDL03 attribute/sampler/PBR contract."""
from __future__ import annotations
import math


def perspective_attribute(lambdas, clip_w, values):
    denominator = sum(lam / w for lam, w in zip(lambdas, clip_w))
    if not math.isfinite(denominator) or denominator <= 1e-12:
        raise ValueError('MODEL_SURFACE_RECIPROCAL_W')
    return [sum(lambdas[i] * values[i][k] / clip_w[i] for i in range(3)) / denominator
            for k in range(len(values[0]))]


def srgb_to_linear(x):
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def linear_to_srgb(x):
    x = max(0.0, x)
    return 12.92*x if x <= 0.0031308 else 1.055*x**(1/2.4)-0.055


def normalize(v):
    n = math.sqrt(sum(x*x for x in v))
    if n <= 1e-10:
        raise ValueError('zero vector')
    return [x/n for x in v]


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def cook_torrance(base, metallic, roughness, normal, tangent, bitangent,
                  world=(0,0,0), camera=(0,0,4), light_direction=(-.42,.82,.38),
                  radiance=(3.2,3.0,2.8), ambient=.035, normal_map=(1,.0039215686274509665,1),
                  normal_scale=.5):
    """Fixed-lighting GGX / Schlick direct BRDF and diffuse ambient term."""
    n = normalize([(2*normal_map[0]-1)*normal_scale,
                   (2*normal_map[1]-1)*normal_scale,2*normal_map[2]-1])
    n = normalize([tangent[k]*n[0]+bitangent[k]*n[1]+normal[k]*n[2] for k in range(3)])
    v = normalize([camera[k]-world[k] for k in range(3)])
    if dot(n,v) < 0:
        n = [-x for x in n]
    l = normalize(light_direction)
    h = normalize([v[k]+l[k] for k in range(3)])
    nv=max(0.0,dot(n,v)); nl=max(0.0,dot(n,l)); nh=max(0.0,dot(n,h)); vh=max(0.0,dot(v,h))
    roughness=min(1.0,max(.045,roughness)); metallic=min(1.0,max(0.0,metallic))
    alpha=roughness*roughness; alpha2=alpha*alpha
    term=nh*nh*(alpha2-1.0)+1.0
    D=alpha2/(math.pi*term*term+1e-12)
    k=(roughness+1.0)**2/8.0
    G=(nv/(nv*(1-k)+k+1e-12))*(nl/(nl*(1-k)+k+1e-12))
    fresnel=(max(0.0,1.0-vh))**5
    result=[]
    for c in range(3):
        f0=.04*(1-metallic)+base[c]*metallic
        F=f0+(1-f0)*fresnel
        spec=D*G*F/(4*nv*nl+1e-8)
        diffuse=(1-F)*(1-metallic)*base[c]/math.pi
        result.append((diffuse+spec)*radiance[c]*nl+base[c]*(1-metallic)*ambient)
    return result
