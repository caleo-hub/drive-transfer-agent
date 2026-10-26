# Drive Transfer Agent — LinkedIn demo

English promotional demo, produced locally on 2026-10-26. Nothing was published.

- `drive-transfer-agent-linkedin.mp4`: final 45-second, 1080 × 1350, 30 fps H.264 video; silent; 1,350 frames; YUV 4:2:0 and MP4 fast-start.
- `capa.png`: 1080 × 1350 cover.
- `postagem.md`: first-person LinkedIn copy in English.
- `record-linkedin.mjs`: Playwright capture, simulated API fixtures, English demo localization, timeline and FFmpeg export.
- `composition.html`: video typography, framing and smooth camera movement.
- `validate-video.py`: full-stream validation, disclosure checks and extraction of every second and cut; requires Python and Pillow.
- `ui/`: generated screenshots of the real React components, including typing and progress (recreated locally, excluded from Git).
- `validation/`: committed export validation and review; scene frames and the capture/network manifest are generated locally and excluded from Git.

## Reproduce

Requires Node.js 22+, the project's installed `web/node_modules` (`npm ci` in `web`), Google Chrome and FFmpeg/FFprobe on PATH. No Python backend, API key, account, model call or transfer service is required.

From the repository root:

```powershell
# Optional when Chrome or FFmpeg is installed elsewhere:
$env:DTA_CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
$env:FFMPEG = 'C:/ffmpeg/bin/ffmpeg.exe'

node docs/linkedin-demo/record-linkedin.mjs --preview
node docs/linkedin-demo/record-linkedin.mjs
ffprobe -v error -count_frames -show_streams -show_format -of json docs/linkedin-demo/drive-transfer-agent-linkedin.mp4
ffmpeg -v error -i docs/linkedin-demo/drive-transfer-agent-linkedin.mp4 -f null -
# Optional: produce the full validation report and contact sheets (Python + Pillow).
python docs/linkedin-demo/validate-video.py
```

The recorder starts a Vite server bound to `127.0.0.1:4187`, opens an isolated headless Chrome context, fulfills every `/api/` call with fictional fixtures and blocks external requests. An unknown API endpoint fails the recording. EventSource is replaced with simulated job snapshots. The Vite process and browser close after recording. The current product sources are read directly; no API or product behavior is modified. Public Google font requests are blocked and the product's sans-serif fallback is used.

English strings are applied only to text nodes in the isolated recording page. The normal application remains in Portuguese. The real input, plan, queue and task components are captured, including actual preflight and execute button interactions against mocked responses. The editorial composition crops and magnifies those components; it is not a separate product UI.

Output timing is deterministic: the composition is rendered at 30 frames per second and exactly 1,350 images are sent to FFmpeg. Progress is accelerated and simulated, not a throughput benchmark. All account states, folder names, source IDs, sizes and statuses are fixtures. The fictional Drive URL is never opened. The MEGA link is never followed.

## Timeline

| Time | Content |
|---|---|
| 00–05 | “I turned file transfers into a conversation.” |
| 05–15 | Fictional request: Brand, Photos and Videos → Demo on MEGA |
| 15–25 | Queue, exact paths, size and space check, approval |
| 25–33 | Task progress and the three queued folders |
| 33–36 | MEGA size-based verification and its limit |
| 36–39 | Simulated result: 42 files copied |
| 39–45 | Drive → PC or MEGA; plan and track through chat; closing question |

“Demo with simulated data” stays visible throughout, including on the cover. MEGA verification is explicitly described as size-based, without claiming byte-for-byte equality. Original files remain untouched; the recorder checks the SHA-256 of `docs/demo.mp4` before and after execution.

Original demo SHA-256: `a62d27de394f35d52dbc0d7cd64f0995aca754022a5251e2ae7d9b92e9ea458c`.

This is a presentation of implemented workflows, not evidence that cloud logins or real transfers were validated. See the repository's `docs/validation.md` and `docs/ferramentas-e-planejamento.md` for implementation scope.
