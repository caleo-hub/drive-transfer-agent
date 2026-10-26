"""Validate the final export and extract a review of every second and every cut."""
import hashlib
import json
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

HERE = Path(__file__).resolve().parent
OUT = HERE / 'validation'
VIDEO = HERE / 'drive-transfer-agent-linkedin.mp4'
OUT.mkdir(exist_ok=True)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True).stdout


probe = json.loads(run('ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                       '-show_format', '-of', 'json', str(VIDEO)))
v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
assert v['codec_name'] == 'h264'
assert (v['width'], v['height']) == (1080, 1350)
assert Fraction(v['avg_frame_rate']) == 30
assert Fraction(v['r_frame_rate']) == 30
assert int(v['nb_read_frames']) == 1350
assert Fraction(v['duration']) == 45
assert Fraction(probe['format']['duration']) == 45
assert v['pix_fmt'] == 'yuv420p'
assert not any(s['codec_type'] == 'audio' for s in probe['streams'])
assert Image.open(HERE / 'capa.png').size == (1080, 1350)

decoded = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-i', str(VIDEO),
                          '-f', 'null', '-'], capture_output=True, check=True)
assert not decoded.stderr.strip(), decoded.stderr.decode(errors='replace')
run('ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', str(VIDEO), '-vf', 'fps=1',
    '-q:v', '2', str(OUT / 'second-%02d.jpg'))

# Compare the persistent simulation disclosure against the lossless cover.
roi = (725, 77, 1004, 116)
reference = Image.open(HERE / 'capa.png').convert('RGB').crop(roi)
badge_errors = []
frames = sorted(OUT.glob('second-*.jpg'))
assert len(frames) == 45
for f in frames:
    image = Image.open(f).convert('RGB')
    mse = sum(ImageStat.Stat(ImageChops.difference(reference, image.crop(roi))).mean) / 3
    assert mse < 15, (f.name, mse)
    badge_errors.append(round(mse, 3))

for batch in range(3):
    sheet = Image.new('RGB', (1080, 1900), '#ffffff')
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(frames[batch*15:(batch+1)*15]):
        x, y = (i % 3)*360, (i // 3)*380
        image = Image.open(f).convert('RGB')
        image.thumbnail((288, 360))
        sheet.paste(image, (x+36, y))
        draw.text((x+40, y+361), f'{batch*15+i:02d}-{batch*15+i+1:02d} s', fill='black')
    sheet.save(OUT / f'video-contact-{batch+1}.jpg', quality=95)

boundaries = [5, 9, 15, 17, 20.5, 23, 25, 33, 36, 39]
for t in boundaries:
    for suffix, timestamp in [('before', t-1/30), ('after', t)]:
        run('ffmpeg', '-v', 'error', '-y', '-ss', str(timestamp), '-i', str(VIDEO),
            '-frames:v', '1', '-q:v', '2', str(OUT / f'cut-{t}-{suffix}.jpg'))
run('ffmpeg', '-v', 'error', '-y', '-ss', str(1349/30), '-i', str(VIDEO),
    '-frames:v', '1', str(OUT / 'last-frame.png'))

original = HERE.parent / 'demo.mp4'
original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
assert original_hash == 'a62d27de394f35d52dbc0d7cd64f0995aca754022a5251e2ae7d9b92e9ea458c'
report = {
    'status': 'passed', 'duration_seconds': 45, 'decoded_frames': 1350,
    'resolution': [1080, 1350], 'fps': '30/1', 'codec': 'h264',
    'pixel_format': v['pix_fmt'], 'audio_tracks': 0,
    'full_decode_errors': 0, 'cover_resolution': [1080, 1350],
    'simulation_badge_samples_passed': len(badge_errors),
    'max_badge_mean_pixel_error': max(badge_errors),
    'original_demo_sha256': original_hash,
    'final_video_sha256': hashlib.sha256(VIDEO.read_bytes()).hexdigest(),
    'final_video_bytes': VIDEO.stat().st_size,
    'probe': probe,
}
report['probe']['format']['filename'] = 'docs/linkedin-demo/' + VIDEO.name
(OUT / 'export-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({k: value for k, value in report.items() if k != 'probe'}, indent=2))
