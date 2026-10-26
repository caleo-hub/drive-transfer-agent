# Final export review

Validated on 2026-10-26. Final materials are in English and use neutral fictional names: Demo, Brand, Photos and Videos.

## Technical checks

- Exactly 45.000 seconds; 1,350 decoded frames at a constant 30 fps.
- 1080 × 1350; H.264; YUV 4:2:0; MP4 fast-start; no audio stream.
- Full FFmpeg decode completed without errors.
- Cover: PNG, 1080 × 1350.
- Final MP4 size: 4,158,256 bytes.
- Final MP4 SHA-256: `92355b88eedfb92253fb628ff1b596ce67962b8d7606794e3c1b00b565e6d939`.

Detailed probe results and assertions are saved in `export-validation.json`.

## Visual and content review

Inspected lossless composition frames, every second extracted from the final MP4, the frames immediately before and after all ten cuts, and the final frame. The enlarged task cards use smooth vertical camera movement; cropping is intentional. The full request is held after the typing sequence. The final question remains on screen for six seconds. Titles, captions and the simulation disclosure remain outside the moving UI crop.

The persistent “Demo with simulated data” label passed comparison against the cover at 45 one-second samples. The source composition places this label independently of all scene changes. English labels were checked against captured DOM text. The demo-only localization includes the audit label, placeholder and typing language; spellcheck underlines are disabled in the recording context. The default application language is unchanged.

The three folder paths are `mega:Demo/Brand`, `mega:Demo/Photos` and `mega:Demo/Videos`. The request uses a fictional `DEMO_FOLDERS` source ID. Counts and sizes are consistent: 12 + 24 + 6 = 42 files and 20 + 100 + 120 = 240 MiB. Capacity is a simulated 50 GiB. Progress is expressly accelerated and simulated. The closing result shows size-based verification; the video states that this does not prove byte-for-byte equality.

The visible plan, queue, preflight and task components are the current React implementation. Captured actions invoke the actual preflight and approval buttons against local mock routes. Product sources and public APIs were not changed for this production. All new material is confined to `docs/linkedin-demo/`.

## Isolation and preservation

- No backend, real model, Google Drive account, MEGA account or real transfer was used.
- API requests were intercepted and fulfilled with fixtures; unexpected endpoints fail the recorder.
- External page requests were blocked. The only blocked external origin recorded was Google Fonts.
- Browser page errors: zero.
- Original `docs/demo.mp4` SHA-256 before and after: `a62d27de394f35d52dbc0d7cd64f0995aca754022a5251e2ae7d9b92e9ea458c`.
- Nothing was published to LinkedIn.

This review validates the promotional export and simulated workflow, not cloud-provider integration or real transfer performance.
