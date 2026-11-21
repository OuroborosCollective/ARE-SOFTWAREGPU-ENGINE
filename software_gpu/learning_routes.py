"""Output-route calibration for local authoring only, outside simulation authority.

Only validated, deterministic, side-effect-free outputs may be candidates.
A saved weight never relaxes output parity and is never part of an image hash.
"""
import hashlib

from .learning import bucket, configured_learner, implementation_id, scope_key


def measured_bytes(stage, width, height, source, reference, candidate):
    """Return complete encoded bytes and an optional persisted learning receipt.

    Both encoders see identical, immutable source data. The learner compares
    complete bytes on its paired probes, never only metadata or dimensions.
    File I/O is intentionally performed *after* the chosen bytes are returned.
    """
    learner = configured_learner()
    if learner is None:
        return reference(), None
    key = scope_key(stage=stage, implementation=implementation_id(__file__),
                    width=bucket(width), height=bucket(height),
                    source_bytes=bucket(source), variant='whole-output-bytes-v1')
    result, receipt = learner.execute(key,
        lambda alternative: candidate() if alternative else reference(),
        lambda output: hashlib.sha256(output).hexdigest())
    return result, receipt
