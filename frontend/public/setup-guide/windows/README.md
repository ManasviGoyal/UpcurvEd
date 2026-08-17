# Windows setup-guide screenshots

Drop PNGs here using the exact filenames below. The Setup Guide already points at
these paths — each shows a dashed "Screenshot coming soon" placeholder until the file
exists, then renders automatically. No code change needed.

| Filename | Guide section | What it should show | Status |
| --- | --- | --- | --- |
| `01-downloaded-installer.png` | Open the installer | Downloads folder with `UpcurvEd-<version>-win-x64.exe` selected | ✅ added |
| `02-smartscreen-warning.png` | Get past the SmartScreen warning | Blue "Windows protected your PC" screen before expanding — shows the **More info** link | ✅ added |
| `03-smartscreen-run-anyway.png` | Get past the SmartScreen warning | Same screen after clicking **More info** — App / Unknown publisher and the **Run anyway** button | ✅ added |
| `04-installing.png` | Finish installation | "UpcurvEd Setup — Installing, please wait…" with the progress bar | ✅ added |
| `05-start-menu.png` | Open the app on Windows | UpcurvEd in the Start menu, or its desktop shortcut | ✅ added |

All Windows screenshots are in place. The final "It should look like this" shot of the
running app comes from `../common/app-running.png`, shared with the macOS walkthrough —
the window is identical on both platforms.

Shared screenshots (the download page, and the in-app Settings screens) live in
`../common/` and are used by both platforms — don't duplicate them here.

## Notes

- The installer is a **one-click NSIS build** (`electron-builder.yml` sets no `nsis`
  block, so `oneClick: true` / `perMachine: false` apply). There is no UAC prompt and
  no install-location picker — the guide's steps reflect that. If that config changes,
  the steps need updating too.
- Screenshots captured against 0.2.0 will show that version in the filename and title
  bar while the guide text says 1.0.0. Recapture after a 1.0.0 build if the mismatch
  matters.
