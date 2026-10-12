"""Independent offline pose oracle; never imported by the native frame loop.

Uses quaternion vector rotation and matrix blending, independently of the C++
expanded TRS / weighted transformed-point implementation. Double precision.
"""
import numpy as np


def rotate(q, vectors):
    q = np.asarray(q, dtype='f8')
    q = q / np.linalg.norm(q)
    v = np.asarray(vectors, dtype='f8')
    return v + 2*np.cross(q[:3], np.cross(q[:3], v) + q[3]*v)


def interpolate_rotation(a, b, fraction):
    a, b = a/np.linalg.norm(a), b/np.linalg.norm(b)
    dot = float(a@b)
    if dot < 0:
        b, dot = -b, -dot
    if dot > .9995:
        q = (1-fraction)*a + fraction*b
    else:
        angle = np.arccos(np.clip(dot, -1, 1))
        q = np.sin((1-fraction)*angle)/np.sin(angle)*a + np.sin(fraction*angle)/np.sin(angle)*b
    return q/np.linalg.norm(q)


def pose(asset, clip, time):
    values = {}
    for c in ([] if clip is None else asset['clips'][clip]['channels']):
        t, v = c['times'], c['values']
        if time <= t[0]:
            value = v[0]
        elif time >= t[-1]:
            value = v[-1]
        else:
            j = int(np.searchsorted(t, time, side='right'))
            f = (time-t[j-1])/(t[j]-t[j-1])
            value = (v[j-1] if not c['interpolation'] else
                     interpolate_rotation(v[j-1], v[j], f) if c['path'] == 1 else
                     np.array([np.interp(time, t, v[:, k]) for k in range(v.shape[1])]))
        values[c['node'], c['path']] = value
    locals_ = []
    for i, n in enumerate(asset['nodes']):
        if 'matrix' in n:
            m = n['matrix']
        else:
            m = np.eye(4)
            m[:3, :3] = rotate(values.get((i, 1), n['q']), np.eye(3)).T
            m[:3, :3] *= values.get((i, 2), n['s'])
            m[:3, 3] = values.get((i, 0), n['t'])
        locals_.append(m)
    worlds = []
    for i in range(len(locals_)):
        chain = []
        while i != -1:
            chain.append(i)
            i = asset['nodes'][i]['parent']
        world = np.eye(4)
        for j in reversed(chain):
            world = world @ locals_[j]
        worlds.append(world)
    positions = np.column_stack([asset['positions'].astype('f8'), np.ones(len(asset['positions']))])
    if not asset['joints']:
        return (positions @ worlds[asset['mesh_node']].T)[:, :3]
    palette = np.asarray(worlds)[asset['joints']] @ asset['inverse_bind']
    # Blend matrices first; C++ transforms each point before blending.
    blended = np.einsum('vi,vijk->vjk', asset['weights'].astype('f8'), palette[asset['joint_data']])
    blended /= asset['weights'].astype('f8').sum(axis=1)[:, None, None]
    return np.einsum('vij,vj->vi', blended, positions)[:, :3]
