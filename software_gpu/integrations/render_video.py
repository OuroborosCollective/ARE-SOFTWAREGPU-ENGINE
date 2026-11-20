"""Encode ordered Blender or ARE frames to H.264 MP4 or FFV1 Matroska."""
import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from software_gpu.learning import bucket, configured_learner, implementation_id, scope_key


def media_binaries():
    # Prefer the matched, versioned studio installation. The ffmpeg directory
    # also owns its ffprobe, preventing an accidental mix of installations.
    for name in ("ffmpeg-9.1", "ffmpeg"):
        found = shutil.which(name)
        if found:
            encoder = Path(found).resolve()
            probe = encoder.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if probe.is_file():
                return encoder, probe
    raise FileNotFoundError("Matching ffmpeg and ffprobe executables are required on PATH")


def encode_frames(out, frames, rate, ffmpeg, ffprobe):
    out = Path(out).absolute()
    if rate <= 0 or not frames:
        raise ValueError("A positive frame rate and at least one frame are required")
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"Output already exists: {out}")
    if not out.parent.is_dir() or out.suffix.lower() not in (".mp4", ".mkv"):
        raise ValueError("Choose a .mp4 or .mkv file in an existing directory")
    extension = frames[0].suffix.lower()
    if extension not in (".png", ".ppm", ".bmp", ".jpg", ".jpeg", ".tif", ".tiff", ".exr"):
        raise ValueError("Input must be a PNG, PPM, BMP, JPEG, TIFF or EXR sequence")
    for frame in frames:
        if frame.suffix.lower() != extension or not frame.is_file():
            raise ValueError(f"Missing frame or different image format: {frame}")

    if out.suffix.lower() == ".mp4":
        encode = ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264",
                  "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        expected_codec = "h264"
    else:
        encode = ["-c:v", "ffv1", "-level", "3", "-g", "1"]
        expected_codec = "ffv1"

    learner = configured_learner()
    with tempfile.TemporaryDirectory(prefix=".are-media-", dir=out.parent) as tmp:
        work = Path(tmp)
        for i, frame in enumerate(frames):
            link = work / f"{i:08d}{extension}"
            try:
                link.symlink_to(frame.resolve())
            except OSError:
                # Windows installations may not allow unprivileged symlinks.
                shutil.copyfile(frame, link)

        def run(single_decoder_thread):
            result = work / (str(int(single_decoder_thread)) + out.suffix.lower())
            decoder = ["-threads", "1"] if single_decoder_thread else []
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-filter_threads", "1",
                            "-f", "image2", "-framerate", str(rate), "-start_number", "0",
                            *decoder, "-i", "%08d" + extension, *encode, "-threads", "2", result],
                           cwd=work, check=True)
            report = json.loads(subprocess.check_output([
                ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,nb_read_frames,avg_frame_rate",
                "-of", "json", result]))
            stream, = report["streams"]
            if (int(stream["nb_read_frames"]) != len(frames)
                    or stream["codec_name"] != expected_codec or Fraction(stream["avg_frame_rate"]) != rate):
                raise ValueError(f"Video readback mismatch: {stream}")
            return result, stream

        def fingerprint(result):
            video, _ = result
            digest = hashlib.sha256()
            # Stream the decoded frame hashes (including timestamps) to bound memory.
            with subprocess.Popen([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", video,
                                   "-map", "0:v:0", "-threads", "1", "-f", "framehash",
                                   "-hash", "sha256", "-"], stdout=subprocess.PIPE) as proc:
                for block in iter(lambda: proc.stdout.read(65536), b""):
                    digest.update(block)
                if proc.wait():
                    raise ValueError("Decoded frame hash failed")
            return digest.hexdigest()

        def publish(result):
            if os.name == "nt":
                # Windows rename fails if another process has published this name.
                os.rename(result[0], out)
            else:
                os.link(result[0], out)

        if learner is None:
            result = run(False)
            publish(result)
            return {"output": str(out), **result[1]}

        total_bytes = sum(frame.stat().st_size for frame in frames)
        key = scope_key(stage="ffmpeg", implementation=implementation_id(__file__, ffmpeg, ffprobe),
                        variant="single-input-thread", codec=expected_codec, image=extension,
                        frames=bucket(len(frames)), input_bytes=bucket(total_bytes), fps=str(rate))
        result, receipt = learner.execute(key, run, fingerprint, publish)
        return {"output": str(out), **result[1], "learning": receipt}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fps", default="24", help="Positive rate, e.g. 12 or 30000/1001")
    parser.add_argument("output", type=Path, help="New .mp4 or .mkv file")
    parser.add_argument("frames", type=Path, nargs="+", help="Images in playback order")
    args = parser.parse_args(argv)
    try:
        result = encode_frames(args.output, args.frames, Fraction(args.fps), *media_binaries())
        print(json.dumps(result))
    except (OSError, subprocess.CalledProcessError, KeyError, ValueError, ZeroDivisionError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
