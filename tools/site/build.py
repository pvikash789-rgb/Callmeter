"""Assemble the public pages.

Usage: python3 tools/site/build.py docs

journal-head.html + journal-body.html -> docs/index.html      (build journal)
log-head.html     + log-body.html     -> docs/decisions.html  (decision log)
journal-head.html + note-body.html    -> docs/note.html       (one-page note)
Every page gets the same nav and the attribution footer the ServiceNow
trademark guidelines ask for on any page that uses their marks.
"""
import sys
from pathlib import Path

SRC = Path(__file__).parent
REPO = "https://github.com/pvikash789-rgb/Callmeter"
out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
out.mkdir(parents=True, exist_ok=True)

HEAD = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'

FOOTER = """<div class="wrap" style="padding-block:0 40px">
<p class="legal">Callmeter is an independent open-source project. It is not affiliated with, sponsored by or endorsed by ServiceNow, Inc. ServiceNow, the ServiceNow logo, Now, and other ServiceNow marks are trademarks and/or registered trademarks of ServiceNow, Inc., in the United States and/or other countries. Other company and product names may be trademarks of the respective companies with which they are associated.</p>
</div>
"""


def nav(other, label):
    return (f'<nav style="max-width:860px;margin:0 auto;padding:16px 16px 0;font-family:var(--mono);font-size:.8rem">'
            f'<a href="{other}">{label} &rarr;</a> &middot; <a href="{REPO}">Code on GitHub</a></nav>\n')


def page(head, body, other, label):
    return (HEAD + (SRC / head).read_text() + "</head>\n<body>\n" + nav(other, label)
            + (SRC / body).read_text().replace("{{REPO}}", REPO) + FOOTER + "</body>\n</html>\n")


(out / "index.html").write_text(page("journal-head.html", "journal-body.html", "decisions.html", "Decision log"))
(out / "decisions.html").write_text(page("log-head.html", "log-body.html", "index.html", "Build journal"))
note_head = (SRC / "journal-head.html").read_text().replace("<title>Callmeter Build Journal</title>", "<title>Callmeter One-Page Note</title>")
(SRC / ".note-head.html").write_text(note_head)
(out / "note.html").write_text(page(".note-head.html", "note-body.html", "index.html", "Build journal"))
(SRC / ".note-head.html").unlink()
print("built", out)
