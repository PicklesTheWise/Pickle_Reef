# Pi Touch Console

The kiosk UI ships as a Tauri + SvelteKit bundle and now embeds the analytics dashboard build directly so the charts work offline on the Pi.

## Dashboard Bundle Workflow

1. Run `npm run sync:dashboard` from this directory (or `npm run build`, which calls it automatically). The script:
	- Builds the browser dashboard in `../frontend`
	- Copies the generated `dist/` bundle into `static/dashboard/`
2. Launch `npm run tauri dev` (set `VITE_DASHBOARD_URL` if you want to point at a remote dashboard instead of the bundled one).

Any time you change the dashboard app, re-run the sync step so the kiosk picks up the new charts.

## Recommended IDE Setup

[VS Code](https://code.visualstudio.com/) + [Svelte](https://marketplace.visualstudio.com/items?itemName=svelte.svelte-vscode) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer).
