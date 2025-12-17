#!/usr/bin/env python3
"""
logue.py – Terminal logbook with Git integration.

This version:
 - Left-hand Catalogue grouped by day (select a day to view all entries for that day)
 - Catalogue draws only inside its left columns (won't erase main area)
 - Tab/F2 toggles focus between entry input and Catalogue
 - Terminal theme respected via use_default_colors()
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
SWITCH_FOCUS_TOKEN = "__SWITCH_FOCUS__"
SIDEBAR_MIN_WIDTH = 10

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
    """
    Robust, non-crashing commit & push for the cold-storage repo.

    Behavior:
      - Operates in COLD_STORAGE_DIR (not the program's cwd).
      - Ensures 'origin' remote exists (adds it if missing).
      - Stages LOGFILE.name, checks `git status --porcelain`.
      - If there are changes, commits with a timestamped message and pushes.
      - All git stdout/stderr and any exceptions are appended to git_push_error.log
        so you can inspect why a push might have failed.
    """
    import subprocess
    import datetime
    from pathlib import Path

    repo_dir = str(COLD_STORAGE_DIR)
    logfile_name = str(LOGFILE.name)
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    log_path = Path(repo_dir) / "git_push_error.log"

    def _append_log(msg: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
        except Exception:
            # best-effort only; don't raise
            pass

    try:
        # Ensure repo exists & is initialized
        init_proc = subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, text=True)
        _append_log(f"git init: rc={init_proc.returncode} out={init_proc.stdout.strip()} err={init_proc.stderr.strip()}")

        # Ensure remote origin exists
        remotes_proc = subprocess.run(["git", "remote", "-v"], cwd=repo_dir, capture_output=True, text=True)
        _append_log(f"git remote -v: rc={remotes_proc.returncode} out={remotes_proc.stdout.strip()} err={remotes_proc.stderr.strip()}")
        if "origin" not in remotes_proc.stdout:
            add_remote_proc = subprocess.run(["git", "remote", "add", "origin", COLD_REPO_URL], cwd=repo_dir, capture_output=True, text=True)
            _append_log(f"git remote add origin: rc={add_remote_proc.returncode} out={add_remote_proc.stdout.strip()} err={add_remote_proc.stderr.strip()}")

        # Stage the log file explicitly
        add_proc = subprocess.run(["git", "add", logfile_name], cwd=repo_dir, capture_output=True, text=True)
        _append_log(f"git add {logfile_name}: rc={add_proc.returncode} out={add_proc.stdout.strip()} err={add_proc.stderr.strip()}")

        # Check if there are any changes to commit (staged or unstaged)
        status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True)
        _append_log(f"git status --porcelain: rc={status_proc.returncode} out={status_proc.stdout.strip()}")

        if status_proc.returncode != 0:
            _append_log("git status returned non-zero; skipping commit/push.")
            return

        if status_proc.stdout.strip() == "":
            # No changes detected
            _append_log("No changes to commit (porcelain empty).")
            return

        # Determine current branch (fallback to main)
        branch_proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, capture_output=True, text=True)
        branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 and branch_proc.stdout.strip() else "main"
        _append_log(f"current branch: {branch}")

        # Commit changes (use explicit message)
        commit_msg = f"Auto log update {timestamp}"
        commit_proc = subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_dir, capture_output=True, text=True)
        _append_log(f"git commit: rc={commit_proc.returncode} out={commit_proc.stdout.strip()} err={commit_proc.stderr.strip()}")

        # If commit failed (non-zero rc) log and continue (do not crash)
        if commit_proc.returncode != 0:
            # If commit failed because nothing to commit, that's ok; otherwise log the error
            _append_log("Commit returned non-zero (no commit performed or error).")

        # Push to origin on the detected branch (set upstream if needed)
        push_proc = subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo_dir, capture_output=True, text=True)
        _append_log(f"git push: rc={push_proc.returncode} out={push_proc.stdout.strip()} err={push_proc.stderr.strip()}")

        if push_proc.returncode != 0:
            _append_log("Push failed (see stderr above).")
    except Exception as ex:
        _append_log(f"Exception in git_commit_and_push: {ex}")

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
    Single-line editor:
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
            # clear only the input region (from x to x+visible)
            # avoid clearing entire line to not touch sidebar
            stdscr.addstr(y, x, " " * visible)
            stdscr.move(y, x)
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

# ------------ Catalogue helpers ------------
def _parse_timestamp_to_date(ts: str) -> Optional[datetime.date]:
    """
    Try to parse several common timestamp formats into a date object.
    Falls back to None if parsing fails.
    """
    if not ts or not isinstance(ts, str):
        return None
    fmts = [
        "%Y_%m_%d_%H_%M_%S",  # default format used by this program
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y_%m_%d",  # sometimes only a date was stored
        "%Y-%m-%d",
    ]
    for f in fmts:
        try:
            return datetime.datetime.strptime(ts, f).date()
        except Exception:
            continue
    # as final fallback, try to extract first 10 characters and replace '-' with '_'
    try:
        raw = ts[:10].replace("-", "_")
        return datetime.datetime.strptime(raw, "%Y_%m_%d").date()
    except Exception:
        return None

def group_entries_by_day(entries: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """
    Group entries by day (normalized to YYYY_MM_DD). This function is robust to different
    timestamp formats that might be present in older entries. The returned list is sorted
    by date descending (newest first).
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        ts = e.get("timestamp", "")
        date_obj = _parse_timestamp_to_date(ts)
        if date_obj is None:
            day = "unknown"
        else:
            day = date_obj.strftime("%Y_%m_%d")
        buckets.setdefault(day, []).append(e)

    # sort entries within each day newest first
    for day, elist in buckets.items():
        elist.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # sort days by parsed date descending, but ensure 'unknown' goes last
    def day_sort_key(item):
        day_key = item[0]
        if day_key == "unknown":
            return datetime.date.min
        try:
            return datetime.datetime.strptime(day_key, "%Y_%m_%d").date()
        except Exception:
            return datetime.date.min

    days = sorted(buckets.items(), key=day_sort_key, reverse=True)
    return days

def render_catalogue(stdscr,
                     days_list: List[Tuple[str, List[Dict[str, Any]]]],
                     sel_idx: int,
                     top_idx: int,
                     sidebar_w: int,
                     height: int,
                     attr_selected,
                     attr_normal):
    """
    Draw the left sidebar but ONLY within columns [0..sidebar_w-1].
    Never clears beyond the sidebar_w column.
    Shows only the date and the number of entries (no preview).
    """
    try:
        # For each row, overwrite only the sidebar columns with spaces (safe)
        for row in range(0, height):
            try:
                stdscr.addstr(row, 0, " " * sidebar_w)
            except curses.error:
                pass

        title = " Catalogue "
        max_write = max(0, sidebar_w - 2)
        try:
            if max_write > 0:
                stdscr.addnstr(0, 1, title, max_write, curses.A_BOLD)
        except curses.error:
            pass

        visible_h = max(0, height - 2)

        # clamp top_idx to valid range so we never try to render an invalid slice
        max_top = max(0, len(days_list) - visible_h)
        top_idx = max(0, min(top_idx, max_top))

        for idx in range(top_idx, min(top_idx + visible_h, len(days_list))):
            row = 1 + (idx - top_idx)
            day_str, day_entries = days_list[idx]
            count = len(day_entries)
            # display only date and count (no preview)
            display_day = f"{day_str} ({count})"
            try:
                if max_write > 0:
                    if idx == sel_idx:
                        stdscr.addnstr(row, 1, display_day, max_write, attr_selected)
                    else:
                        stdscr.addnstr(row, 1, display_day, max_write, attr_normal)
            except curses.error:
                pass

        hint = "[Tab/F2 toggle | Enter view day]"
        try:
            if max_write > 0:
                stdscr.addnstr(max(0, height - 1), 1, hint, max_write, curses.A_DIM)
        except curses.error:
            pass

    except Exception:
        pass


# ------------ Main UI ------------
def interactive_mode(stdscr) -> None:
    # terminal title
    try:
        sys.stdout.write("\x1b]2;logue\x07")
        sys.stdout.flush()
    except Exception:
        pass

    curses.cbreak()
    curses.noecho()
    stdscr.keypad(True)

    # Colors and attributes
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
        except Exception:
            pass

        curses.init_pair(1, curses.COLOR_CYAN, -1)   # tasks today
        curses.init_pair(2, curses.COLOR_YELLOW, -1) # tasks tomorrow
        curses.init_pair(3, curses.COLOR_GREEN, -1)  # entries
        curses.init_pair(4, curses.COLOR_WHITE, -1)  # header/label/input

        tasks_today_attr = curses.color_pair(1)
        tasks_today_title_attr = curses.color_pair(1) | curses.A_BOLD

        tasks_tomorrow_attr = curses.color_pair(2)
        tasks_tomorrow_title_attr = curses.color_pair(2) | curses.A_BOLD

        entries_attr = curses.color_pair(3)
        entries_title_attr = curses.color_pair(3) | curses.A_BOLD

        logo_attr = curses.color_pair(4) | curses.A_BOLD
        date_attr = curses.color_pair(4) | curses.A_BOLD | curses.A_UNDERLINE
        label_attr = curses.color_pair(4)
        input_attr = curses.color_pair(4)

    else:
        tasks_today_attr = tasks_today_title_attr = curses.A_BOLD
        tasks_tomorrow_attr = tasks_tomorrow_title_attr = curses.A_BOLD
        entries_attr = entries_title_attr = curses.A_BOLD
        logo_attr = curses.A_BOLD
        date_attr = curses.A_BOLD | curses.A_UNDERLINE
        label_attr = input_attr = curses.A_NORMAL


    logo_lines = [
        "╻  ┏━┓┏━╸╻ ╻┏━╸",
        "┃  ┃ ┃┃╺┓┃ ┃┣╸ ",
        "┗━╸┗━┛┗━┛┗━┛┗━╸",
    ]
    prompt_loc = "enter location: "

    today_date = datetime.date.today()
    today_str = today_date.strftime("%Y_%m_%d")
    tomorrow_date = today_date + datetime.timedelta(days=1)
    tomorrow_str = tomorrow_date.strftime("%Y_%m_%d")
    date_str_pretty = f"{ordinal(today_date.day)} {today_date.strftime('%B')} {today_date.year} at"

    # State
    catalogue_focus = False
    selected_catalogue_index = 0
    viewed_day_index = None

    # initial data load
    data = load_data()
    entries = data.get("entries", [])
    tasks_map = data.get("tasks", {})

    # prompt for location once before entering main loop — draw logo centered, prompt centered
    stdscr.clear()
    maxy, maxx = stdscr.getmaxyx()
    # draw logo centered using logo_attr
    for i, line in enumerate(logo_lines):
        try:
            stdscr.addstr(i + 1, max(0, (maxx - len(line)) // 2), line, logo_attr)
        except curses.error:
            pass

    # center the prompt underneath the logo
    prompt_row = len(logo_lines) + 3
    prompt_col = max(2, (maxx - len(prompt_loc)) // 2)
    try:
        stdscr.addstr(prompt_row, prompt_col, prompt_loc, label_attr)
    except curses.error:
        pass
    stdscr.refresh()
    loc_in = get_singleline_input(
        stdscr,
        prompt_row,
        prompt_col + len(prompt_loc),
        max(8, maxx - (prompt_col + len(prompt_loc)) - 2),
    )

    if loc_in is None:
        location = ""
    else:
        location = loc_in.strip()

    if location:
        raw = location.lower()
        underscore = raw.replace(" ", "_")
        location_tags = [raw] if raw == underscore else [raw, underscore]
    else:
        location_tags = []

    # -----------------------
    # Clock-In / Clock-Out setup
    # -----------------------
    # Determine day, start_time and end_time immediately after the user answered the location
    dt_now = datetime.datetime.now()
    day_of_week = dt_now.strftime("%A")               # e.g. "Monday"
    start_time = dt_now.strftime("%H:%M:%S")          # exact time user submitted location
    now_exact = dt_now.strftime("%Y_%m_%d_%H_%M_%S")  # timestamp format used by program

    # Business logic: Monday/Tuesday => +9 hours, other days => +8 hours
    if day_of_week.lower() in ("monday", "tuesday"):
        delta = datetime.timedelta(hours=9)
    else:
        delta = datetime.timedelta(hours=8)
    end_dt = dt_now + delta
    end_time = end_dt.strftime("%H:%M:%S")

    # Create a "first entry of the day" if there is no non-empty text entry for today
    # Use the same today_str created above in interactive_mode (today_str is in scope)
    # We consider an entry "present" if there's any existing entry with today's prefix and non-empty text.
    # (This mirrors the session entries logic later in the program.)
    try:
        # load initial entries that were loaded earlier
        # `entries` exists (it was loaded before the prompt). If not, reload.
        if "entries" not in locals():
            data = load_data()
            entries = data.get("entries", [])
        # Find if any non-empty entry already exists for today
        today_entries = [
            e for e in entries
            if isinstance(e.get("timestamp", ""), str)
            and e.get("timestamp", "").startswith(today_str)
            and str(e.get("text", "")).strip() != ""
        ]
        if not today_entries:
            # compose the clock-in entry text
            clock_text = f"Clock-In at {start_time}. Clock out at {end_time}"
            tags = location_tags.copy()
            new_entry = {
                "timestamp": now_exact,
                "text": clock_text,
                "tags": tags,
                "location": location,
            }
            entries.append(new_entry)
            # persist using existing data dict (or create one) so save_data() will commit & push
            try:
                data  # if data exists, update
            except NameError:
                data = load_data()
            data["entries"] = entries
            save_data(data)  # will write file and trigger git commit/push
    except Exception as ex:
        # Best-effort only — do not crash the UI if something unexpectedly fails here.
        # You can log it to stderr or ignore silently depending on desired behaviour.
        print(f"[WARN] Failed to create clock-in entry: {ex}", file=sys.stderr)


    # Main loop
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        # Sidebar geometry
        sidebar_w = max(SIDEBAR_MIN_WIDTH, width // 3)
        main_left = sidebar_w + 2  # main content starts after sidebar + separator
        left = main_left
        right = 2

        # reload data
        data = load_data()
        entries = data.get("entries", [])
        tasks_map = data.get("tasks", {})

        # grouped days
        days_list = group_entries_by_day(entries)
        selected_catalogue_index = max(0, min(selected_catalogue_index, max(0, len(days_list) - 1)))

        # compute visible rows in the sidebar (title + footer excluded)
        visible_h = max(0, height - 2)
        # center selected index in the visible window when possible
        top_idx_guess = max(0, selected_catalogue_index - (visible_h // 2))
        # clamp top index so that top_idx_guess never goes beyond the available range
        top_idx_clamped = max(0, min(top_idx_guess, max(0, len(days_list) - visible_h)))

        # catalogue attributes
        if curses.has_colors():
            cat_sel_attr = curses.color_pair(4) | curses.A_REVERSE
            cat_normal_attr = curses.color_pair(4)
        else:
            cat_sel_attr = curses.A_REVERSE
            cat_normal_attr = curses.A_NORMAL

        # Draw catalogue (left) — this writes only in columns 0..sidebar_w-1
        render_catalogue(stdscr, days_list, selected_catalogue_index, top_idx_clamped, sidebar_w, height, cat_sel_attr, cat_normal_attr)

        # vertical separator
        try:
            for r in range(0, height):
                stdscr.addch(r, sidebar_w, curses.ACS_VLINE)
        except curses.error:
            pass

        # Draw header/logo and date in main area
        header_height = len(logo_lines)
        # Draw logo at left of main area using logo_attr (no underline)
        for i, line in enumerate(logo_lines):
            try:
                stdscr.addstr(i + 1, left, line, logo_attr)
            except curses.error:
                pass

        # Draw date on the top line using date_attr (can include underline)
        date_line = date_str_pretty
        if location:
            date_line += f" {location}"
        # Include the computed clock-out time in the header (if available)
        try:
            # end_time was computed earlier after the location prompt; guard just in case
            if "end_time" in locals() and end_time:
                date_line += f"  —  Clock out at {end_time}"
        except Exception:
            pass
        try:
            stdscr.addstr(0, max(left, width - len(date_line) - 2), date_line, date_attr)
        except curses.error:
            pass



        # Entry box
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

        # Tasks and entries area
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

        # gap
        for _ in range(TASKS_GAP):
            if current_line < height - 1:
                current_line += 1

        # Tasks for tomorrow
        if current_line < height - 1:
            try:
                stdscr.addstr(current_line, left, "  Tasks for tomorrow:", tasks_tomorrow_title_attr)
            except curses.error:
                pass
        current_line += 1
        tom_tasks = tasks_for_date(tasks_map, tomorrow_str)
        for t in tom_tasks:
            if current_line < height - 1:
                try:
                    stdscr.addstr(current_line, left + 4, f"- {t}", tasks_tomorrow_attr)
                except curses.error:
                    pass
                current_line += 1
            else:
                break

        # spacer before entries
        if current_line < height - 1:
            current_line += 1

        if current_line < height - 1:
            try:
                stdscr.addstr(current_line, left, "  Entries:", entries_title_attr)
            except curses.error:
                pass

        line = current_line + 1
        box_height_logs = max(0, height - line - 1)

        # If a viewed day is set, show its entries; otherwise show today's entries
        if viewed_day_index is not None and 0 <= viewed_day_index < len(days_list):
            day_str, day_entries = days_list[viewed_day_index]
            try:
                stdscr.addstr(line, left + 4, f"Entries for {day_str} ({len(day_entries)})", entries_attr | curses.A_BOLD)
            except curses.error:
                pass
            line += 1
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

        # If catalogue is focused, handle catalogue navigation here (non-destructive)
        if catalogue_focus:
            # single-threaded navigation loop that DOES NOT clear the main area.
            while True:
                ch = stdscr.getch()
                if ch in (9, curses.KEY_F2):  # toggle focus back to input
                    catalogue_focus = False
                    break
                elif ch in (27,):  # ESC -> quit
                    return
                elif ch in (curses.KEY_UP, ord('k')):
                    if selected_catalogue_index > 0:
                        selected_catalogue_index -= 1
                elif ch in (curses.KEY_DOWN, ord('j')):
                    if selected_catalogue_index < max(0, len(days_list) - 1):
                        selected_catalogue_index += 1
                elif ch == curses.KEY_NPAGE:
                    jump = max(1, height - 4)
                    selected_catalogue_index = min(max(0, len(days_list) - 1), selected_catalogue_index + jump)
                elif ch == curses.KEY_PPAGE:
                    jump = max(1, height - 4)
                    selected_catalogue_index = max(0, selected_catalogue_index - jump)
                elif ch in (10, 13):  # Enter -> view selected day
                    viewed_day_index = selected_catalogue_index
                # Re-render only the catalogue portion to reflect new selection
                top_idx_local = max(0, selected_catalogue_index - (visible_h // 2))
                top_idx_local = max(0, min(top_idx_local, max(0, len(days_list) - visible_h)))
                render_catalogue(stdscr, days_list, selected_catalogue_index, top_idx_local, sidebar_w, height, cat_sel_attr, cat_normal_attr)
                try:
                    stdscr.addch(0, sidebar_w, curses.ACS_VLINE)
                except curses.error:
                    pass
                stdscr.noutrefresh()
                curses.doupdate()
            # when we come back here, main loop will redraw everything (clean)
            continue

        # Entry input mode (blocking on input); Tab returns SWITCH_FOCUS_TOKEN
        stdscr.attron(input_attr)
        note = get_singleline_input(stdscr, entry_y, entry_x, entry_visible_width)
        stdscr.attroff(input_attr)

        if note is None:
            break

        if note == SWITCH_FOCUS_TOKEN:
            catalogue_focus = True
            continue

        if note == "":
            continue

        tasks, cleaned_note = extract_tasks_and_clean_text(note)
        now_exact = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        tags = extract_tags(note)
        for lt in location_tags:
            if lt not in tags:
                tags.append(lt)

        # **Important fix**: Do NOT append empty-text entries (these are typically task-only inputs).
        # If the user entered only tasks (cleaned_note is empty) we only add to the tasks_map.
        if cleaned_note and cleaned_note.strip():
            new_entry = {"timestamp": now_exact, "text": cleaned_note, "tags": tags, "location": location}
            entries.append(new_entry)
            data["entries"] = entries
        else:
            # no entry text to record; ensure entries list remains unchanged
            data["entries"] = entries

        if tasks:
            tasks_map = data.get("tasks", {})
            for t in tasks:
                add_task_for_date(tasks_map, tomorrow_str, t)
            data["tasks"] = tasks_map

        # save once (save_data already runs git_commit_and_push())
        save_data(data)

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
