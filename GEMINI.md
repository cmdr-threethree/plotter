# Project Instructions - Plotter

## Webapp Development
- **Service Worker Versioning**: Whenever modifying assets in `webapp/static/` (e.g., `app.js`, `index.html`, `styles.css`), you MUST increment the `CACHE_NAME` constant in `webapp/static/sw.js` (e.g., `plotter-v1` -> `plotter-v2`). This ensures that the Service Worker detects the change and prompts the user to update when they are online.
- **Co-authored-by**: Always include `Co-authored-by: Gemini CLI <gemini-cli@google.com>` at the end of every commit message.
