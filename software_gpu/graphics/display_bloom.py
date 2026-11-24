"""Soft-knee highlight bloom for a display-referred straight-alpha sRGB framebuffer."""
import hashlib
import math
import sqlite3
from contextlib import closing

import numpy as np

from ..learning import configured_learner, implementation_id, scope_key
from .framebuffer import Framebuffer


# Separable binomial kernel, with unit sum in each direction.
_WEIGHTS = (1, 8, 28, 56, 70, 56, 28, 8, 1)
_RADIUS = len(_WEIGHTS) // 2
_SRGB = np.arange(256, dtype=np.float64) / 255
_LINEAR = np.where(_SRGB <= .04045, _SRGB / 12.92, ((_SRGB + .055) / 1.055) ** 2.4)


def _blur(source, block_rows):
    height, width = source.shape[:2]
    padded = np.pad(source, ((0, 0), (_RADIUS, _RADIUS), (0, 0)), mode='edge')
    horizontal = np.zeros_like(source)
    for offset, weight in enumerate(_WEIGHTS):
        horizontal += padded[:, offset:offset + width] * (weight / 256)
    padded = np.pad(horizontal, ((_RADIUS, _RADIUS), (0, 0), (0, 0)), mode='edge')
    result = np.zeros_like(source)
    for start in range(0, height, block_rows):
        stop = min(start + block_rows, height)
        for offset, weight in enumerate(_WEIGHTS):
            result[start:stop] += padded[start + offset:stop + offset] * (weight / 256)
    return result


# First linear intensity that can round to an sRGB byte of 255.
_CLIP = ((254.5 / 255 + .055) / 1.055) ** 2.4
_GAIN_STEPS = 256


def _fit_gain(linear, glow, rgba, intensity, cached):
    delta = glow * intensity
    eligible = (rgba[..., :3] < 255) & (rgba[..., 3:] > 0) & (delta > 0)
    headroom = _CLIP - linear[eligible]
    added = delta[eligible]
    budget = len(headroom) // 100

    def clipped(step):
        return int(np.count_nonzero(added * (step / _GAIN_STEPS) >= headroom))

    full = clipped(_GAIN_STEPS)
    if full <= budget:
        step = _GAIN_STEPS
    elif (type(cached) is int and 0 <= cached < _GAIN_STEPS and clipped(cached) <= budget
          and clipped(cached + 1) > budget):
        step = cached
    else:
        # Fit the strongest permitted bloom against this frame's channel headroom.
        low, high = 0, _GAIN_STEPS
        while high - low > 1:
            mid = (low + high) // 2
            if clipped(mid) <= budget:
                low = mid
            else:
                high = mid
        step = low
    return dict(gain_step=step, gain_steps=_GAIN_STEPS, effective_intensity=intensity * step / _GAIN_STEPS,
                eligible_channels=len(headroom), budget=budget, clipped_requested=full,
                clipped_selected=clipped(step))


def _quality_weight(path, key, step=None):
    # Auxiliary bounded table in the configured local learner DB. Unique keys make
    # concurrent cold fits converge on the same weight for this exact input.
    with closing(sqlite3.connect(path, timeout=2)) as db, db:
        if step is None:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bloom_weights'").fetchone():
                return None
            row = db.execute('SELECT gain_step FROM bloom_weights WHERE frame_key=?', (key,)).fetchone()
            return row[0] if row else None
        db.execute('CREATE TABLE IF NOT EXISTS bloom_weights (frame_key TEXT UNIQUE, gain_step INTEGER NOT NULL)')
        db.execute('INSERT INTO bloom_weights VALUES (?,?) ON CONFLICT(frame_key) DO UPDATE SET gain_step=excluded.gain_step',
                   (key, step))
        db.execute('DELETE FROM bloom_weights WHERE rowid < '
                   '(SELECT rowid FROM bloom_weights ORDER BY rowid DESC LIMIT 1 OFFSET 127)')


def apply_display_bloom(fb: Framebuffer, *, threshold=.22, knee=.10, intensity=.85):
    """Add a smooth halo in linear light, keeping coverage, depth and exposure intact.

    Threshold and knee use relative linear luminance in [0, 1]; intensity is
    additive gain. The learner times two equivalent filter traversal orders.
    """
    if not (0 <= threshold <= 1 and 0 < knee <= 1 and 0 <= intensity <= 16
            and all(math.isfinite(x) for x in (threshold, knee, intensity))):
        raise ValueError('DISPLAY_BLOOM_PARAMETERS')
    if fb.width < 1 or fb.height < 1:
        raise ValueError('DISPLAY_BLOOM_DIMENSIONS')
    linear = _LINEAR[fb.color_buffer[..., :3]]
    luma = .2126 * linear[..., 0] + .7152 * linear[..., 1] + .0722 * linear[..., 2]
    excess = luma - threshold
    soft = np.clip(excess + knee, 0, 2 * knee) ** 2 / (4 * knee)
    gain = np.maximum(soft, excess) / np.maximum(luma, 1e-12)
    source = linear * (gain * (fb.color_buffer[..., 3] / 255))[..., None]

    learner = configured_learner()
    cached = None
    if learner is not None:
        key = scope_key(stage='display-bloom', implementation=implementation_id(__file__),
                        variant='whole-vs-32-rows', width=fb.width, height=fb.height,
                        numpy=np.__version__, threshold=threshold, knee=knee, intensity=intensity)
        digest = hashlib.sha256(key.encode())
        digest.update(np.ascontiguousarray(fb.color_buffer))
        frame_key = digest.hexdigest()
        try:
            cached = _quality_weight(learner.path, frame_key)
        except sqlite3.Error:
            pass

    def render(striped):
        glow = _blur(source, 32 if striped else fb.height)
        fit = _fit_gain(linear, glow, fb.color_buffer, intensity, cached)
        color = np.minimum(1, linear + glow * fit['effective_intensity'])
        srgb = np.where(color <= .0031308, 12.92 * color, 1.055 * color ** (1 / 2.4) - .055)
        out = Framebuffer(fb.width, fb.height)
        out.color_buffer[..., :3] = np.rint(srgb * 255).astype(np.uint8)
        out.color_buffer[..., 3] = fb.color_buffer[..., 3]
        out.depth_buffer[...] = fb.depth_buffer
        out.bloom_quality = fit
        return out

    def fingerprint(out):
        digest = hashlib.sha256(out.color_buffer)
        digest.update(out.depth_buffer)
        return digest.hexdigest()

    if learner is None:
        out = render(False)
        receipt = {'outcome': 'disabled', 'served': 'reference'}
        out.bloom_quality['weight_state'] = 'ephemeral'
    else:
        out, receipt = learner.execute(key, render, fingerprint)
        step = out.bloom_quality['gain_step']
        state = 'reused' if step == cached else 'fitted'
        if state == 'fitted':
            try:
                _quality_weight(learner.path, frame_key, step)
            except sqlite3.Error:
                state = 'ephemeral'
        out.bloom_quality.update(frame_key=frame_key, weight_state=state)
    out.last_bloom_learning_receipt = receipt
    return out
