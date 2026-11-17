"""The best-game picture: saves the best game's final screen as a web page and a terminal file."""

import html
from pathlib import Path

from .screen import SGR, new_style, sgr_style

# Colours for the web page copy (close to a typical dark terminal).
HTML_COLOURS = ["#000000", "#cc0000", "#4e9a06", "#c4a000", "#3465a4", "#75507b", "#06989a", "#d3d7cf",
                "#555753", "#ef2929", "#8ae234", "#fce94f", "#729fcf", "#ad7fa8", "#34e2e2", "#eeeeec"]

HTML_FG, HTML_BG = "#d3d7cf", "#1e1e1e"


def screen_to_html(text, title, caption):
    """Turn a captured screen (text with colour codes) into a web page you can open in a browser."""
    st = new_style()
    out = []
    for line in text.split("\n"):
        pos = 0
        for m in SGR.finditer(line + "\x1b[m"):
            chunk = line[pos:m.start()]
            if chunk:  # wrap this stretch of text in a <span> with the right colours
                fg = HTML_COLOURS[st["fg"]] if st["fg"] is not None else HTML_FG
                bg = HTML_COLOURS[st["bg"]] if st["bg"] is not None else None
                if st["rev"]:  # "reverse video" swaps text and background colours
                    fg, bg = bg or HTML_BG, fg
                css = [f"color:{fg}"]
                if bg:
                    css.append(f"background:{bg}")
                if st["bold"]:
                    css.append("font-weight:bold")
                if st["dim"]:
                    css.append("opacity:0.6")
                out.append(f'<span style="{";".join(css)}">{html.escape(chunk)}</span>')
            pos = m.end()
            st = sgr_style(m.group(1), st)
        out.append("\n")
    return (f"<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title>\n<style>\n"
            f"body {{ background:{HTML_BG}; color:{HTML_FG}; font-family:sans-serif; margin:2em; }}\n"
            f"h1 {{ font-size:1.2em; margin:0 0 .3em; }}\n"
            f"p {{ margin:0 0 1em; color:#aaa; }}\n"
            f"pre {{ font-family:'DejaVu Sans Mono','Liberation Mono',monospace; font-size:15px; "
            f"line-height:1.15; margin:0; }}\n"
            f"</style></head>\n<body>\n<h1>{html.escape(title)}</h1>\n<p>{html.escape(caption)}</p>\n"
            f"<pre>{''.join(out).rstrip()}</pre>\n</body></html>\n")


def save_best_screen(base, shot, player_name):
    """Save the best game's screen as base_best.html and base_best.ans. Returns both paths."""
    lines = shot["text"].split("\n")
    while lines and not SGR.sub("", lines[-1]).strip():
        lines.pop()  # drop the empty rows under the game
    text = "\n".join(lines)
    title = f"Snake: best game of the run ({player_name})"
    caption = (f"Game {shot['game']} of {shot['games']}: score {shot['score']}, "
               f"ended by {shot['cause']} after {shot['moves']} moves, {shot['time']}")
    html_path = Path(f"{base}_best.html")
    ans_path = Path(f"{base}_best.ans")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(screen_to_html(text, title, caption))
    ans_path.write_text(f"{title}\n{caption}\n\n{text}\x1b[0m\n")
    return html_path, ans_path
