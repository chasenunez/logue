#!/usr/bin/env python3
"""
logue.py – A lightweight terminal logbook with Git integration.

Edits in this version:
 - Fix entry box so the border is solid (no right-side gap).
 - Hide tags and location from the on-screen "Today's Entries" log display.
 - Add persistent header above entry box:
     logue: September 8th 2025; Location
"""

import argparse
import curses
import datetime
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Dict, Any


# -------------------- Paths --------------------
SCRIPT_DIR = Path(__file__).resolve().parent
LOGFILE = SCRIPT_DIR / "logue.json"


# -------------------- JSON Handling --------------------
def load_logs() -> List[Dict[str, Any]]:
    if not LOGFILE.exists():
        return []
    try:
        with LOGFILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading log file: {e}", file=sys.stderr)
        return []


def save_logs(data: List[Dict[str, Any]]) -> None:
    with LOGFILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -------------------- Git Handling --------------------
def git_commit_and_push() -> None:
    try:
        subprocess.run(["git", "add", str(LOGFILE.name)], check=True, cwd=SCRIPT_DIR)
        subprocess.run(["git", "commit", "-m", "logue: update"], check=True, cwd=SCRIPT_DIR)
        subprocess.run(["git", "push"], check=True, cwd=SCRIPT_DIR)
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Git operation failed: {e}", file=sys.stderr)
        print(
            "If authentication fails after reboot, set a GitHub token with:\n"
            "  git remote set-url origin https://<USERNAME>:<TOKEN>@github.com/<USERNAME>/<REPO>.git",
            file=sys.stderr,
        )


# -------------------- Tag Extraction --------------------
def extract_tags(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"#(\w+)", text)]


# -------------------- Search Functions --------------------
def search_by_date(date_prefix: str) -> None:
    logs = load_logs()
    matches = [e for e in logs if e["timestamp"].startswith(date_prefix)]
    if matches:
        for e in matches:
            tags = f" [tags: {', '.join(e.get('tags', []))}]" if e.get("tags") else ""
            location = f" [location: {e.get('location','')}]"
            print(f"{e['timestamp']}: {e['text']}{tags}{location}")
    else:
        print(f"No entries found for {date_prefix}")


def search_by_tag(tag: str) -> None:
    logs = load_logs()
    tag = tag.lower()
    matches = [e for e in logs if tag in [t.lower() for t in e.get("tags", [])]]
    if matches:
        for e in matches:
            print(f"{e['timestamp']}: {e['text']} [tags: {', '.join(e.get('tags', []))}] [location: {e.get('location','')}]")
    else:
        print(f"No entries found for tag #{tag}")


# -------------------- Ordinal date helper --------------------
def ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    elif n % 10 == 1:
        return f"{n}st"
    elif n % 10 == 2:
        return f"{n}nd"
    elif n % 10 == 3:
        return f"{n}rd"
    else:
        return f"{n}th"


# -------------------- Input Handling --------------------
def get_singleline_input(stdscr, y, x, max_width) -> str:
    """Single-line input editor with arrow keys and horizontal scrolling."""
    buffer: List[str] = []
    cursor_pos = 0
    scroll = 0
    visible = max(1, max_width)

    while True:
        # Ensure cursor is visible in window
        if cursor_pos < scroll:
            scroll = cursor_pos
        elif cursor_pos > scroll + visible - 1:
            scroll = cursor_pos - (visible - 1)

        view = "".join(buffer)[scroll:scroll + visible]

        stdscr.move(y, x)
        stdscr.clrtoeol()
        try:
            stdscr.addstr(y, x, view)
        except curses.error:
            pass

        cursor_col = x + max(0, cursor_pos - scroll)
        max_y, max_x = stdscr.getmaxyx()
        cursor_col = min(cursor_col, max_x - 1)
        try:
            stdscr.move(y, cursor_col)
        except curses.error:
            stdscr.move(max(0, min(max_y - 1, y)), max(0, cursor_col))

        ch = stdscr.getch()

        if ch in (10, 13):  # Enter
            return "".join(buffer).strip()
        elif ch == 27:  # ESC
            return ""
        elif ch in (8, 127, curses.KEY_BACKSPACE):
            if cursor_pos > 0:
                buffer.pop(cursor_pos - 1)
                cursor_pos -= 1
        elif ch == curses.KEY_LEFT and cursor_pos > 0:
            cursor_pos -= 1
        elif ch == curses.KEY_RIGHT and cursor_pos < len(buffer):
            cursor_pos += 1
        elif 32 <= ch <= 126:  # printable
            buffer.insert(cursor_pos, chr(ch))
            cursor_pos += 1


# -------------------- Interactive Mode --------------------
def interactive_mode(stdscr) -> None:
    sys.stdout.write("\x1b]2;logue\x07")
    sys.stdout.flush()

    curses.cbreak()
    curses.noecho()
    stdscr.keypad(True)

    # Colors (fallback to bold if not available)
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)    # headers
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # labels
        curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)   # logs
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)   # input
        header_attr, label_attr, log_attr, input_attr = (
            curses.color_pair(1),
            curses.color_pair(2),
            curses.color_pair(3),
            curses.color_pair(4),
        )
    else:
        header_attr = label_attr = log_attr = input_attr = curses.A_BOLD

    # Ask location once
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    prompt_loc = "Enter location (optional, press Enter to skip): "
    stdscr.addstr(0, 2, prompt_loc, label_attr)
    stdscr.refresh()
    location = get_singleline_input(stdscr, 0, 2 + len(prompt_loc), width - len(prompt_loc) - 4).strip()

    location_tags: List[str] = []
    if location:
        raw = location.lower()
        underscore = raw.replace(" ", "_")
        location_tags = list({raw, underscore})

    # Prepare date string with ordinal suffix
    today = datetime.date.today()
    date_str = f"{ordinal(today.day)} {today.strftime('%B')} {today.year}"

    logs = load_logs()
    today_prefix = today.strftime("%Y_%m_%d")
    session_entries = [e for e in logs if e["timestamp"].startswith(today_prefix)]

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Persistent header line
        header_text = f"logue: {date_str}"
        if location:
            header_text += f"; {location}"
        stdscr.addstr(0, 2, header_text, header_attr)

        # Box dimensions for entry
        box_top, box_left = 2, 2
        box_width = max(20, width - 4)
        box_height = 3

        # Draw box (solid)
        try:
            stdscr.addch(box_top, box_left, curses.ACS_ULCORNER)
            stdscr.hline(box_top, box_left + 1, curses.ACS_HLINE, box_width - 2)
            stdscr.addch(box_top, box_left + box_width - 1, curses.ACS_URCORNER)
            stdscr.vline(box_top + 1, box_left, curses.ACS_VLINE, box_height - 2)
            stdscr.vline(box_top + 1, box_left + box_width - 1, curses.ACS_VLINE, box_height - 2)
            stdscr.addch(box_top + box_height - 1, box_left, curses.ACS_LLCORNER)
            stdscr.hline(box_top + box_height - 1, box_left + 1, curses.ACS_HLINE, box_width - 2)
            stdscr.addch(box_top + box_height - 1, box_left + box_width - 1, curses.ACS_LRCORNER)
        except curses.error:
            pass

        # Prompt inside box
        prompt_text = "Current entry: "
        prompt_y = box_top + 1
        prompt_x = box_left + 2
        stdscr.addstr(prompt_y, prompt_x, prompt_text, label_attr)

        input_x = prompt_x + len(prompt_text)
        input_visible_width = max(8, box_left + box_width - input_x - 2)

        # Show today's entries
        log_start_y = box_top + box_height + 1
        stdscr.addstr(log_start_y, 2, "Today's Entries:", header_attr)
        line = log_start_y + 1
        box_height_logs = max(0, height - log_start_y - 2)

        for entry in reversed(session_entries[-(box_height_logs - 1):]):
            try:
                ts = datetime.datetime.strptime(entry["timestamp"], "%Y_%m_%d_%H_%M_%S")
                time_str = ts.strftime("%H:%M")
            except Exception:
                time_str = entry.get("timestamp", "")[-8:-3]

            if line < height - 1:
                stdscr.addstr(line, 4, f"{time_str}", label_attr)

            display = f" - {entry['text']}"
            wrap_width = max(10, width - 14)
            for wl in textwrap.wrap(display, wrap_width):
                if line < height - 1:
                    stdscr.addstr(line, 12, wl, log_attr)
                    line += 1
            if line < height - 1:
                line += 1

        stdscr.refresh()

        # Input inside box
        stdscr.attron(input_attr)
        note = get_singleline_input(stdscr, prompt_y, input_x, input_visible_width)
        stdscr.attroff(input_attr)

        if not note:
            break

        now_exact = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        tags = extract_tags(note)
        for lt in location_tags:
            if lt not in tags:
                tags.append(lt)

        entry = {"timestamp": now_exact, "text": note, "tags": tags, "location": location}
        logs.append(entry)
        session_entries.append(entry)
        save_logs(logs)
        git_commit_and_push()


# -------------------- Main --------------------
def main():
    parser = argparse.ArgumentParser(description="logue: simple terminal logbook with git")
    parser.add_argument("--search", metavar="YYYY_MM_DD", help="Search entries by date")
    parser.add_argument("--search-tag", metavar="TAG", help="Search entries by tag (without #)")
    args = parser.parse_args()

    if args.search:
        search_by_date(args.search)
        return
    if args.search_tag:
        search_by_tag(args.search_tag)
        return

    curses.wrapper(interactive_mode)


if __name__ == "__main__":
    main()
