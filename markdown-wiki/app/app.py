import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
import markdown as md

WIKI_DIR = Path(os.environ.get("WIKI_DIR", "/share/wiki"))
STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR))
logger = logging.getLogger("markdown_wiki")
logging.basicConfig(level=logging.INFO)


DEFAULT_HOME_MD = """# Welcome to Markdown Wiki

This is a simple read-only Markdown viewer.

- Put your Markdown files in `/share/wiki`
- Only files ending in `.md` are shown
- Subfolders are ignored

Example:

```markdown
# My Notes

- Item 1
- Item 2
```
"""


def to_title(filename: str) -> str:
    stem = Path(filename).stem
    return stem.replace("_", " ").replace("-", " ")


def is_valid_filename(filename: str) -> bool:
    if not filename:
        return False

    candidate = Path(filename)
    if candidate.is_absolute():
        return False
    if candidate.name != filename:
        return False
    if not filename.lower().endswith(".md"):
        return False
    if "/" in filename or "\\" in filename:
        return False
    return True


def list_markdown_files() -> list[Path]:
    if not WIKI_DIR.exists():
        return []

    files = [
        p
        for p in WIKI_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".md"
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def ensure_wiki_dir() -> None:
    WIKI_DIR.mkdir(parents=True, exist_ok=True)

    markdown_files = list_markdown_files()
    if not markdown_files:
        home_file = WIKI_DIR / "Home.md"
        home_file.write_text(DEFAULT_HOME_MD, encoding="utf-8")
        logger.info("Created default wiki page at %s", home_file)


def resolve_markdown_file(filename: str) -> Path:
    if not is_valid_filename(filename):
        raise ValueError("Invalid filename")

    requested = (WIKI_DIR / filename).resolve()
    wiki_root = WIKI_DIR.resolve()

    if requested.parent != wiki_root:
        raise ValueError("Invalid filename")
    if requested.suffix.lower() != ".md":
        raise ValueError("Invalid filename")

    return requested


@app.after_request
def add_no_cache_headers(response):
    if response.status_code < 500 and request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/files")
def api_files():
    files = list_markdown_files()
    payload = [{"filename": p.name, "title": to_title(p.name)} for p in files]
    return jsonify(payload)


@app.route("/api/page/<path:filename>")
def api_page(filename: str):
    try:
        resolved = resolve_markdown_file(filename)
    except ValueError:
        return jsonify({"error": "Invalid filename"}), 400

    if not resolved.exists() or not resolved.is_file():
        return jsonify({"error": "File not found"}), 404

    try:
        text = resolved.read_text(encoding="utf-8")
        html = md.markdown(
            text,
            extensions=["fenced_code", "tables", "toc", "sane_lists"],
        )
        return jsonify(
            {
                "filename": resolved.name,
                "title": to_title(resolved.name),
                "html": html,
            }
        )
    except UnicodeDecodeError:
        return jsonify({"error": "Unable to decode file as UTF-8"}), 400
    except Exception:  # pragma: no cover
        logger.exception("Unexpected error rendering %s", filename)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/<path:filename>")
def static_files(filename: str):
    static_file = (STATIC_DIR / filename).resolve()
    static_root = STATIC_DIR.resolve()

    if static_file.parent != static_root:
        return jsonify({"error": "Not found"}), 404
    if not static_file.exists() or not static_file.is_file():
        return jsonify({"error": "Not found"}), 404

    return send_from_directory(app.static_folder, filename)


def startup() -> None:
    ensure_wiki_dir()
    count = len(list_markdown_files())
    logger.info("Markdown Wiki started")
    logger.info("Wiki directory: %s", WIKI_DIR.resolve())
    logger.info("Markdown files found: %d", count)


startup()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)
