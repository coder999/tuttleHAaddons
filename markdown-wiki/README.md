# Markdown Wiki Home Assistant Add-on

Markdown Wiki is a minimal, read-only Home Assistant add-on that renders Markdown files from `/share/wiki` with a simple left sidebar.

## Disclaimer

Use this project at your own risk.

- This add-on is provided as-is, without warranties of any kind.
- You are responsible for validating behavior in your own Home Assistant environment.
- The maintainers are not liable for data loss, downtime, misconfiguration, or any damages resulting from use.

## Features

- Flask backend + vanilla JavaScript frontend
- Home Assistant Ingress compatible
- Reads only `.md` files directly in `/share/wiki`
- Flat folder only (no subfolders)
- No editing, no auth, no database

## Folder Layout

```text
markdown-wiki/
  config.yaml
  Dockerfile
  run.sh
  app/
    app.py
    requirements.txt
    static/
      index.html
      style.css
      app.js
```

## Install as a Local Home Assistant Add-on

1. On your Home Assistant host, create a local add-on folder if it does not exist:

   - `/addons/local/`

2. Copy the entire `markdown-wiki` folder into:

   - `/addons/local/markdown-wiki`

3. In Home Assistant:

   - Go to **Settings -> Add-ons -> Add-on Store**
   - Open the menu (three dots) and click **Reload**
   - Open **Markdown Wiki**
   - Click **Install**
   - Start the add-on

4. Optionally enable **Start on boot** and **Show in sidebar**.

## Where to Put Markdown Files

Put your files in:

- `/share/wiki`

Only files ending in `.md` directly in that folder are listed.

## Example Markdown File

Create `/share/wiki/Home.md`:

```markdown
# Home

Welcome to your wiki.

## Quick Links

- [Home Assistant](https://www.home-assistant.io/)

## Notes

- This wiki is read-only.
- Add more `.md` files in `/share/wiki`.
```

## API Overview

- `GET /` serves the SPA
- `GET /api/files` returns available Markdown files
- `GET /api/page/<filename>` returns rendered HTML for a Markdown file
- `GET /health` returns `{ "status": "ok" }`

## Known Limitations

- Flat folder only (no nested folders)
- Read-only viewer
- No search
- No editing

## Troubleshooting

- Sidebar is empty:
  - Verify files are inside `/share/wiki`
  - Verify filenames end with `.md`
  - Click **Refresh** in the sidebar

- Ingress page loads but API calls fail:
  - Ensure frontend requests use relative URLs (already configured)
  - Fully reload the browser tab after updating the add-on

- Changes to markdown not showing:
  - Click **Refresh** in the sidebar
  - Browser cache should be bypassed by API no-cache headers, but a hard reload can help

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
