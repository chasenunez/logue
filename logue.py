#!/usr/bin/env python3
"""
logue.py – Terminal logbook with Git integration.

Patched to add a left-hand Catalogue (sidebar) which lists all past entries
and allows navigation and viewing of any entry. Use Tab or F2 to toggle focus
between the entry input box and the Catalogue.
"""

import argparse
import curses
import datetime
import json
import sys
import re
import subprocess
import textwrap
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# ------------ Config ------------
TASKS_GAP = 1  # blank lines between today's tasks and tomorrow's header

# token returned by input routine when user requests focus switch
SWITCH_FOCUS_TOKEN = "__SWITCH_FOCUS__"

# ---------------- Paths ----------------
SCRIPT_DIR = Path(__file__).resolve().parent
COLD_STORAGE_DIR = Path.home() / "Documents" / "log_cold_storage"
COLD_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = COLD_STORAGE_DIR / "logue.json"

COLD_REPO_URL = "https://github.com/chasenunez/log_cold_storage.git"

# ------------ Data storage ------------
def load_data() -> dict:
    if not LOGFILE.exists():
        return {"entries": [], "tasks": {}}
    try:
        with LOGFILE.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            return {"entries": obj.get("entries", []), "tasks": obj.get("tasks", {})}
        return {"entries": [], "tasks": {}}
    except Exception as e:
        print(f"[ERROR] Failed to load log file: {e}", file=sys.stderr)
        return {"entries": [], "tasks": {}}

def save_data(data: dict) -> None:
    with LOGFILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    git_commit_and_push()

def git_commit_and_push() -> None:
    import subprocess
    import sys

    try:
        subprocess.run(["git", "init"], cwd=COLD_STORAGE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        remotes = subprocess.run(["git", "remote"], cwd=COLD_STORAGE_DIR, capture_output=True, text=True)
        if "origin" not in remotes.stdout:
            subprocess.run(["git", "remote", "add", "origin", COLD_REPO_URL], cwd=COLD_STORAGE_DIR)

        subprocess.run(
            ["git", "add", str(LOGFILE.name)],
            check=True,
            cwd=COLD_STORAGE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "commit", "-m", "logue: update"],
            check=True,
            cwd=COLD_STORAGE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            check=True,
            cwd=COLD_STORAGE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Git operation failed: {e}", file=sys.stderr)
        print(
            "If authentication fails, ensure the remote repo exists and credentials are set.\n"
            f"Remote URL: {COLD_REPO_URL}",
            file=sys.stderr,
        )

# ------------ Helpers ------------
def extract_tags(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"#(\w+)", text)]

def extract_tasks_and_clean_text(text: str) -> Tuple[List[str], str]:
    tasks = re.findall(r"\*\s*([^\n\r]+)", text)
    cleaned = re.sub(r"\*\s*[^\n\r]+", "", text)
    cleaned = "\n".join([ln.rstrip() for ln in cleaned.splitlines() if ln.strip() != ""]).strip()
    tasks = [t.strip() for t in tasks if t.strip()]
    return tasks, cleaned

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

# ------------ Input (single-line editor) ------------
def get_singleline_input(stdscr, y: int, x: int, max_width: int) -> Optional[str]:
    """
    Single-line editor with:
      - Left/Right arrow navigation
      - Backspace/delete
      - Horizontal scrolling
      - Enter -> return the string
      - ESC -> return None (cancel)
      - Tab or F2 -> return SWITCH_FOCUS_TOKEN to indicate user wants to switch focus (to Catalogue)
    """
    buffer: List[str] = []
    cursor_pos = 0
    scroll = 0
    visible = max(1, max_width)

    while True:
        if cursor_pos < scroll:
            scroll = cursor_pos
        elif cursor_pos > scroll + visible - 1:
            scroll = cursor_pos - (visible - 1)

        view = "".join(buffer)[scroll : scroll + visible]

        try:
            stdscr.move(y, x)
            stdscr.clrtoeol()
            stdscr.addstr(y, x, view)
        except curses.error:
            pass

        cursor_col = x + max(0, cursor_pos - scroll)
        max_y, max_x = stdscr.getmaxyx()
        cursor_col = min(cursor_col, max_x - 1)
        try:
            stdscr.move(y, cursor_col)
        except curses.error:
            try:
                stdscr.move(max(0, min(max_y - 1, y)), max(0, cursor_col))
            except curses.error:
                pass

        ch = stdscr.getch()

        if ch in (10, 13):  # Enter
            return "".join(buffer).strip()
        elif ch == 27:  # ESC
            return None
        elif ch in (8, 127, curses.KEY_BACKSPACE):
            if cursor_pos > 0:
                buffer.pop(cursor_pos - 1)
                cursor_pos -= 1
        elif ch == curses.KEY_LEFT and cursor_pos > 0:
            cursor_pos -= 1
        elif ch == curses.KEY_RIGHT and cursor_pos < len(buffer):
            cursor_pos += 1
        elif ch in (9, curses.KEY_F2):  # Tab or F2 => switch focus to catalogue
            return SWITCH_FOCUS_TOKEN
        elif 32 <= ch <= 126:
            buffer.insert(cursor_pos, chr(ch))
            cursor_pos += 1
        # ignore other keys

# ------------ Task utilities ------------
def tasks_for_date(tasks_map: Dict[str, List[str]], date_str: str) -> List[str]:
    return tasks_map.get(date_str, [])

def add_task_for_date(tasks_map: Dict[str, List[str]], date_str: str, task: str) -> None:
    if not task:
        return
    tasks_map.setdefault(date_str, []).append(task)

# ------------ CLI search helpers ------------
def search_by_date(date_prefix: str) -> None:
    data = load_data()
    entries = data.get("entries", [])
    matches = [e for e in entries if e.get("timestamp", "").startswith(date_prefix)]
    if matches:
        for e in matches:
            tags = f" [tags: {', '.join(e.get('tags', []))}]" if e.get("tags") else ""
            location = f" [location: {e.get('location','')}]"
            print(f"{e['timestamp']}: {e['text']}{tags}{location}")
    else:
        print(f"No entries found for {date_prefix}")

def search_by_tag(tag: str) -> None:
    data = load_data()
    entries = data.get("entries", [])
    tag = tag.lower()
    matches = [e for e in entries if tag in [t.lower() for t in e.get("tags", [])]]
    if matches:
        for e in matches:
            print(f"{e['timestamp']}: {e['text']} [tags: {', '.join(e.get('tags', []))}] [location: {e.get('location','')}]")
    else:
        print(f"No entries found for tag #{tag}")

# ------------ Catalogue UI helpers (NEW) ------------
# Replace sort_entries_newest_first with this function
def group_entries_by_day(entries: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """
    Group entries by their YYYY_MM_DD day prefix.

    Returns a list of tuples (day_str, entries_list) sorted newest day first.
    Each entries_list is sorted newest-first (by timestamp).
    day_str is the YYYY_MM_DD string used in the timestamp prefix.
    """
    # bucket by day prefix
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        ts = e.get("timestamp", "")
        day = ts[:10] if len(ts) >= 10 else "unknown"
        buckets.setdefault(day, []).append(e)

    # sort entries within each day newest-first
    for day, elist in buckets.items():
        elist.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # produce list of (day, entries) sorted by day (newest first)
    days = sorted(buckets.items(), key=lambda kv: kv[0], reverse=True)
    return days

# Replace render_catalogue with this day-group aware version
def render_catalogue(stdscr,
                     days_list: List[Tuple[str, List[Dict[str, Any]]]],
                     sel_idx: int,
                     top_idx: int,
                     sidebar_w: int,
                     height: int,
                     attr_selected,
                     attr_normal):
    """
    Draw the left sidebar showing days. days_list is a list of (day_str, [entries]).
    sel_idx is the selected day index. top_idx is the index at the top of view.
    """
    try:
        # clear sidebar area (simple background)
        for row in range(0, height):
            try:
                stdscr.addstr(row, 0, " " * max(1, sidebar_w))
            except curses.error:
                pass

        title = " Catalogue (by day) "
        try:
            stdscr.addstr(0, 1, title[: max(0, sidebar_w - 2)], curses.A_BOLD)
        except curses.error:
            pass

        visible_h = height - 2  # allow for title + bottom hint
        for idx in range(top_idx, min(top_idx + visible_h, len(days_list))):
            row = 1 + (idx - top_idx)
            day_str, day_entries = days_list[idx]
            count = len(day_entries)
            # preview: first entry's first line (short)
            preview = ""
            if day_entries:
                first = day_entries[0].get("text", "")
                preview = first.splitlines()[0][: (sidebar_w - 20)]
            # format day display: YYYY_MM_DD  (N)  preview...
            display_day = f"{day_str:11} ({count:2}) {preview}"
            try:
                if idx == sel_idx:
                    stdscr.addstr(row, 1, display_day[: max(0, sidebar_w - 2)], attr_selected)
                else:
                    stdscr.addstr(row, 1, display_day[: max(0, sidebar_w - 2)], attr_normal)
            except curses.error:
                pass

        hint = "[Tab/F2 toggle | Enter view day]"
        try:
            stdscr.addstr(height - 1, 1, hint[: max(0, sidebar_w - 2)], curses.A_DIM)
        except curses.error:
            pass
    except Exception:
        pass


# Replace catalogue_navigation_loop with this day-aware version
def catalogue_navigation_loop(stdscr,
                              days_list: List[Tuple[str, List[Dict[str, Any]]]],
                              sidebar_w: int,
                              height: int,
                              start_sel: int):
    """
    Navigate the list of days. Returns (new_selected_day_idx, viewed_day_idx, exit_flag).
    - new_selected_day_idx: final selection when leaving catalogue
    - viewed_day_idx: index of day that was 'viewed' (Enter pressed), or None
    - exit_flag: True if user pressed ESC to quit entire program
    """
    sel = max(0, min(start_sel, len(days_list) - 1)) if days_list else 0
    top = max(0, sel - (height // 2))
    viewed = None

    # attributes
    if curses.has_colors():
        sel_attr = curses.color_pair(4) | curses.A_REVERSE
        normal_attr = curses.color_pair(4)
    else:
        sel_attr = curses.A_REVERSE
        normal_attr = curses.A_NORMAL

    while True:
        render_catalogue(stdscr, days_list, sel, top, sidebar_w, height, sel_attr, normal_attr)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (9, curses.KEY_F2):  # toggle focus back to input
            return sel, viewed, False
        elif ch in (27,):  # ESC -> quit entire app
            return sel, viewed, True
        elif ch in (curses.KEY_UP, ord('k')):
            if sel > 0:
                sel -= 1
            if sel < top:
                top = sel
        elif ch in (curses.KEY_DOWN, ord('j')):
            if sel < max(0, len(days_list) - 1):
                sel += 1
            if sel >= top + (height - 2):
                top = sel - (height - 3)
        elif ch == curses.KEY_NPAGE:  # Page Down
            jump = max(1, height - 4)
            sel = min(max(0, len(days_list) - 1), sel + jump)
            top = min(max(0, len(days_list) - (height - 2)), top + jump)
        elif ch == curses.KEY_PPAGE:  # Page Up
            jump = max(1, height - 4)
            sel = max(0, sel - jump)
            top = max(0, top - jump)
        elif ch in (10, 13):  # Enter -> view this day in main area
            viewed = sel
            # keep selection; allow repeated Enter to re-toggle view
        # ignore other keys


# ------------ Main UI ------------
def interactive_mode(stdscr) -> None:
    try:
        sys.stdout.write("\x1b]2;logue\x07")
        sys.stdout.flush()
    except Exception:
        pass

    curses.cbreak()
    curses.noecho()
    stdscr.keypad(True)

    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # tasks today
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # tasks tomorrow
        curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)   # entries
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)   # header/label/input

        tasks_today_attr = curses.color_pair(1)
        tasks_today_title_attr = curses.color_pair(1) | curses.A_BOLD

        tasks_tomorrow_attr = curses.color_pair(2)
        tasks_tomorrow_title_attr = curses.color_pair(2) | curses.A_BOLD

        entries_attr = curses.color_pair(3)
        entries_title_attr = curses.color_pair(3) | curses.A_BOLD

        header_attr = curses.color_pair(4) | curses.A_BOLD
        label_attr = curses.color_pair(4)
        input_attr = curses.color_pair(4)
    else:
        tasks_today_attr = tasks_today_title_attr = curses.A_BOLD
        tasks_tomorrow_attr = tasks_tomorrow_title_attr = curses.A_BOLD
        entries_attr = entries_title_attr = curses.A_BOLD
        header_attr = label_attr = input_attr = curses.A_NORMAL

    data = load_data()
    entries: List[Dict[str, Any]] = data.get("entries", [])

    stdscr.clear()
    height, width = stdscr.getmaxyx()

    logo_lines = [
        "╻  ┏━┓┏━╸╻ ╻┏━╸",
        "┃  ┃ ┃┃╺┓┃ ┃┣╸ ",
        "┗━╸┗━┛┗━┛┗━┛┗━╸",
    ]
    for i, line in enumerate(logo_lines):
        try:
            stdscr.addstr(i + 1, max(0, (width - len(line)) // 2), line, header_attr)
        except curses.error:
            pass

    prompt_loc = "enter location: "
    prompt_row = len(logo_lines) + 3
    prompt_col = max(2, (width - len(prompt_loc)) // 2)
    try:
        stdscr.addstr(prompt_row, prompt_col, prompt_loc, label_attr)
    except curses.error:
        pass
    stdscr.refresh()

    loc_in = get_singleline_input(stdscr, prompt_row, prompt_col + len(prompt_loc), max(8, width - (prompt_col + len(prompt_loc)) - 2))
    if loc_in is None:
        location = ""
    else:
        location = loc_in.strip()

    location_tags: List[str] = []
    if location:
        raw = location.lower()
        underscore = raw.replace(" ", "_")
        location_tags = [raw] if raw == underscore else [raw, underscore]

    today_date = datetime.date.today()
    today_str = today_date.strftime("%Y_%m_%d")
    tomorrow_date = today_date + datetime.timedelta(days=1)
    tomorrow_str = tomorrow_date.strftime("%Y_%m_%d")
    date_str_pretty = f"{ordinal(today_date.day)} {today_date.strftime('%B')} {today_date.year}"

    # New state for Catalogue & viewing
    catalogue_focus = False
    selected_catalogue_index = 0
    viewed_day_index = None  # index into days_list or None


    # Main loop
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Sidebar width about 1/3
        sidebar_w = max(20, width // 3)
        main_left = sidebar_w + 2  # main content starts after sidebar + separator
        left = main_left
        right = 2

        # Header block (draw in main area)
        header_height = len(logo_lines)
        for i, line in enumerate(logo_lines):
            try:
                stdscr.addstr(i, left, line, header_attr)
            except curses.error:
                pass

        date_line = date_str_pretty
        if location:
            date_line += f"  {location}"
        try:
            stdscr.addstr(0, max(left, width - len(date_line) - 2), date_line, header_attr)
        except curses.error:
            pass

        # Draw vertical separator line between sidebar and main
        try:
            for r in range(0, height):
                stdscr.addch(r, sidebar_w, curses.ACS_VLINE)
        except curses.error:
            pass

        # Entry box (main area)
        box_top = header_height + 1
        box_left = left
        box_width = max(30, width - left - right)
        box_height = 3
        try:
            stdscr.addch(box_top, box_left, curses.ACS_ULCORNER)
            stdscr.hline(box_top, box_left + 1, curses.ACS_HLINE, max(0, box_width - 2))
            stdscr.addch(box_top, box_left + box_width - 1, curses.ACS_URCORNER)
            stdscr.vline(box_top + 1, box_left, curses.ACS_VLINE, max(0, box_height - 2))
            stdscr.vline(box_top + 1, box_left + box_width - 1, curses.ACS_VLINE, max(0, box_height - 2))
            stdscr.addch(box_top + box_height - 1, box_left, curses.ACS_LLCORNER)
            stdscr.hline(box_top + box_height - 1, box_left + 1, curses.ACS_HLINE, max(0, box_width - 2))
            stdscr.addch(box_top + box_height - 1, box_left + box_width - 1, curses.ACS_LRCORNER)
        except curses.error:
            pass

        prompt_text = "Entry: "
        entry_y = box_top + 1
        prompt_x = box_left + 2
        entry_x = prompt_x + len(prompt_text)
        try:
            stdscr.addstr(box_top + 1, prompt_x, prompt_text, label_attr)
        except curses.error:
            pass
        entry_visible_width = max(10, box_left + box_width - entry_x - 2)

        # reload data for latest
        data = load_data()
        entries = data.get("entries", [])
        tasks_map = data.get("tasks", {})

        # Draw Catalogue (left pane) - grouped by day
        days_list = group_entries_by_day(entries)  # List[ (day_str, [entries]) ]
        catalogue_title = "Catalogue"

        # attributes for catalogue and selection — ensure these names are defined
        # whether terminal supports colors or not
        if curses.has_colors():
            cat_title_attr = curses.color_pair(4) | curses.A_BOLD
            cat_sel_attr = curses.color_pair(4) | curses.A_REVERSE
            cat_normal_attr = curses.color_pair(4)
        else:
            cat_title_attr = curses.A_BOLD
            cat_sel_attr = curses.A_REVERSE
            cat_normal_attr = curses.A_NORMAL

        # ensure selected_catalogue_index is valid for days
        selected_catalogue_index = max(0, min(selected_catalogue_index, max(0, len(days_list) - 1)))
        top_idx_guess = max(0, selected_catalogue_index - (height // 2))

        # finally render the catalogue (now with defined attributes)
        render_catalogue(
            stdscr,
            days_list,
            selected_catalogue_index,
            top_idx_guess,
            sidebar_w,
            height,
            cat_sel_attr,
            cat_normal_attr,
        )

        # Tasks for today (main)
        tasks_top = box_top + box_height + 1
        current_line = tasks_top

        if current_line < height - 1:
            try:
                stdscr.addstr(current_line, left, "  Tasks for today:", tasks_today_title_attr)
            except curses.error:
                pass
        current_line += 1
        todays_tasks = tasks_for_date(tasks_map, today_str)
        for t in todays_tasks:
            if current_line < height - 1:
                try:
                    stdscr.addstr(current_line, left + 4, f"- {t}", tasks_today_attr)
                except curses.error:
                    pass
                current_line += 1
            else:
                break

        for _ in range(TASKS_GAP):
            if current_line < height - 1:
                current_line += 1

        if current_line < height - 1:
            try:
                stdscr.addstr(current_line, left, "  Entries:", entries_title_attr)
            except curses.error:
                pass
        line = current_line + 1
        box_height_logs = max(0, height - line - 1)

        # If a viewed day (from catalogue) is set, display all entries for that day; otherwise show today's entries
        if 'viewed_day_index' in locals() and viewed_day_index is not None and 0 <= viewed_day_index < len(days_list):
            day_str, day_entries = days_list[viewed_day_index]
            # header
            try:
                stdscr.addstr(line, left + 4, f"Entries for {day_str} ({len(day_entries)})", entries_attr | curses.A_BOLD)
            except curses.error:
                pass
            line += 1
            # show each entry (newest first)
            for entry in day_entries[: max(0, box_height_logs - 1)]:
                if line >= height - 1:
                    break
                try:
                    ts = datetime.datetime.strptime(entry["timestamp"], "%Y_%m_%d_%H_%M_%S")
                    time_str = ts.strftime("%H:%M:%S")
                except Exception:
                    time_str = entry.get("timestamp", "")[-8:-3]
                try:
                    stdscr.addstr(line, left + 4, f"{time_str}", entries_attr | curses.A_BOLD)
                except curses.error:
                    pass
                display = f" - {entry.get('text','')}"
                wrap_width = max(10, width - (left + 14))
                for wl in textwrap.wrap(display, wrap_width):
                    if line < height - 1:
                        try:
                            stdscr.addstr(line, left + 12, wl, entries_attr)
                        except curses.error:
                            pass
                        line += 1
                    else:
                        break
                if line < height - 1:
                    line += 1
        else:
            # Today's entries (original behavior)
            session_entries = [
                e
                for e in entries
                if e.get("timestamp", "").startswith(today_str) and str(e.get("text", "")).strip() != ""
            ]
            for entry in reversed(session_entries[-(box_height_logs - 1) :]):
                if line >= height - 1:
                    break
                try:
                    ts = datetime.datetime.strptime(entry["timestamp"], "%Y_%m_%d_%H_%M_%S")
                    time_str = ts.strftime("%H:%M")
                except Exception:
                    time_str = entry.get("timestamp", "")[-8:-3]
                try:
                    stdscr.addstr(line, left + 4, f"{time_str}", entries_attr | curses.A_BOLD)
                except curses.error:
                    pass
                display = f" - {entry.get('text','')}"
                wrap_width = max(10, width - (left + 14))
                for wl in textwrap.wrap(display, wrap_width):
                    if line < height - 1:
                        try:
                            stdscr.addstr(line, left + 12, wl, entries_attr)
                        except curses.error:
                            pass
                        line += 1
                    else:
                        break
                if line < height - 1:
                    line += 1


        help_line = "Enter = submit entry | ESC = quit | Tab/F2 = Catalogue"
        try:
            stdscr.addstr(max(0, height - 1), max(left, 2), help_line[: max(0, width - left - 4)], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

        # Input or switch to Catalogue based on focus
        if catalogue_focus:
            sel, viewed_day, exit_flag = catalogue_navigation_loop(stdscr, days_list, sidebar_w, height, selected_catalogue_index)
            selected_catalogue_index = sel
            if viewed_day is not None:
                # set the viewed day index (so main pane will show ALL entries for that day)
                viewed_day_index = viewed_day
            if exit_flag:
                break
            catalogue_focus = False
            continue


        # Entry input mode
        stdscr.attron(input_attr)
        note = get_singleline_input(stdscr, entry_y, entry_x, entry_visible_width)
        stdscr.attroff(input_attr)

        if note is None:
            break

        if note == SWITCH_FOCUS_TOKEN:
            # switch to catalogue focus
            catalogue_focus = True
            continue

        if note == "":
            # ignore empty entries
            continue

        tasks, cleaned_note = extract_tasks_and_clean_text(note)

        now_exact = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        tags = extract_tags(note)
        for lt in location_tags:
            if lt not in tags:
                tags.append(lt)

        new_entry = {"timestamp": now_exact, "text": cleaned_note, "tags": tags, "location": location}
        entries.append(new_entry)
        data["entries"] = entries

        if tasks:
            tasks_map = data.get("tasks", {})
            for t in tasks:
                add_task_for_date(tasks_map, tomorrow_str, t)
            data["tasks"] = tasks_map

        save_data(data)
        # preserve original behavior (attempt push)
        git_commit_and_push()

# ------------ Main ------------
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
