# Wsl Commander Architecture Design

- Date: 2026-07-09
- Stage: Architecture Design
- Iteration: Round 1/5
- Feature: wsl-commander

## Source Documents

- Plan: docs/01-plan/wsl-commander.plan.md

## Context Anchor

| Field | Content |
|---|---|
| WHY | Need a dual-pane file manager for WSL (Linux terminal) inspired by Total Commander / Double Commander |
| WHO | WSL users, Linux terminal users who prefer keyboard-driven file management |
| RISK | TUI complexity, cross-platform terminal compatibility, performance with large directories |
| SUCCESS | Working dual-pane TUI file manager with common file operations, keyboard shortcuts, and visual file listing |
| SCOPE | TUI-based dual-pane file manager for Linux/WSL terminal |

## Option A — Minimal Changes

**Description:** A flat, procedural single-file script using `curses` directly. All logic — UI drawing, file I/O, input handling, state — is interleaved in a single `main()` function or a handful of top-level functions with global mutable state.

**Approach:**

- One file: `lcom`
- Global variables for: current directory (left), current directory (right), active pane index, cursor positions, file list caches
- Inline `curses` calls throughout: `stdscr.addstr(...)`, `stdscr.refresh()`, manual coordinate math
- `while True:` loop reading `stdscr.getch()` with a giant `if/elif` chain for key dispatch
- File operations: inline `shutil.copy2(...)`, `os.remove(...)`, etc., called directly from the input handler

**Pros:**

- Fastest to prototype — zero architectural overhead
- No class design decisions needed upfront
- Easy for a single developer to hold the entire program in their head (under ~300 lines)
- Minimal indirection; grep-friendly

**Cons:**

- Hard to extend beyond ~500 lines — complexity grows nonlinearly
- Testing individual components (e.g., sorting logic) requires extracting them first
- Global mutable state makes bugs hard to reproduce and trace
- Resize handling, dual-pane coordinate math, and key dispatch all tangled together
- Adding features like configurable key bindings or themes requires significant refactoring
- Code review is painful — every change touches the monolithic block

## Option B — Clean Architecture

**Description:** A multi-module Python package with strict separation of concerns: UI rendering, file system operations, state management, input handling, and configuration are in separate files.

**Approach:**

- Package structure: `lcom/__init__.py`, `lcom/ui.py`, `lcom/panels.py`, `lcom/fsops.py`, `lcom/state.py`, `lcom/keys.py`, `lcom/config.py`
- `lcom` script is a thin entry point that initializes `curses` and delegates to `App`
- `App` class orchestrates the game loop, delegates rendering to `Renderer`, input to `KeyDispatcher`
- `Renderer` owns all `curses` window objects and coordinate math
- `FilePanel` is a pure data model + logic class with no `curses` dependency (testable without a terminal)
- `FileOperations` is a stateless module of pure functions (trivially unit-testable)
- `Config` reads a YAML/JSON config file for key bindings, colors, defaults

**Pros:**

- Each module is independently testable and reviewable
- Clear separation of concerns — a new developer knows exactly where to add a feature
- Supports configuration files, plugins, and themes naturally
- Scales to thousands of lines without degradation
- UI can be swapped out (e.g., `curses` → `urwid` later) without touching file ops or state

**Cons:**

- Heavy upfront cost — 8+ files, package structure, `__init__.py` wiring
- Over-engineered for a v1 with a single developer and ~500 lines of logic
- Python module import overhead at the `lcom` script boundary (minor but real)
- Packaging/distribution complexity — no longer a single droppable script
- Increases cognitive load: tracing a keypress through 4 files to understand behavior
- Adds friction for quick experiments and rapid iteration during early development

## Option C — Pragmatic Balance

**Description:** A single-file application with well-defined internal class boundaries. All code lives in one `lcom` file, but logic is partitioned into distinct classes: `WslCommander` (app controller), `FilePanel` (per-pane state + navigation), file operation functions, and utility functions. The single-file constraint keeps distribution trivial while classes provide internal modularity.

**Approach:**

- One file: `lcom` (executable via `#!/usr/bin/env python3` shebang)
- `class WslCommander` — app lifecycle, main loop, input dispatch, panel coordination
- `class FilePanel` — one instance per pane; owns current directory, cursor, file list, sort/filter state
- Top-level functions: `copy_file()`, `move_file()`, `delete_file()`, etc. (file operations module)
- Top-level utility functions: `format_size()`, `format_date()`, `format_permissions()`
- Constants defined as module-level dicts: `KEYBINDINGS`, `COLORS`, `HEADER_HEIGHT`
- All `curses` interaction is contained in `WslCommander.draw()` and `FilePanel` rendering helpers
- State is owned by class instances, not globals — clean initialization and reset

**Pros:**

- Single droppable file — distribution is `cp lcom /usr/local/bin/`
- Internal class boundaries make the code navigable and reviewable
- File operations are pure functions — testable without a terminal
- `FilePanel` can evolve independently; adding a third pane or a tree view is a new class, not a rewrite
- Fast enough to prototype (no package scaffolding) but structured enough to grow
- Natural migration path: if `lcom` grows large, classes can be extracted into separate files later with minimal refactoring
- Fits the v1 scope perfectly — ~500–800 lines, one developer

**Cons:**

- Single file still has a practical cap (~2000 lines before scrolling becomes painful)
- Class boundaries are conventions, not enforced by the module system — discipline required
- All functions share the same namespace; naming collisions are possible (though unlikely with the proposed structure)
- No automated enforcement of layering (e.g., `FilePanel` could technically call `curses` directly)
- Harder to parallelize development across multiple contributors than a multi-file package

## Trade-off Table

| Criteria | A (Minimal) | B (Clean) | C (Pragmatic) |
|---|---|---|---|
| Prototyping speed | ★★★★★ | ★★ | ★★★★ |
| Readability (<800 lines) | ★★★ | ★★★★ | ★★★★★ |
| Extensibility (v2+) | ★★ | ★★★★★ | ★★★★ |
| Testability | ★ | ★★★★★ | ★★★★ |
| Distribution simplicity | ★★★★★ | ★★ | ★★★★★ |
| Onboarding ease | ★★★ | ★★ | ★★★★ |
| Separation of concerns | ★ | ★★★★★ | ★★★★ |
| Refactoring cost (v1→v2) | ★★ | ★★★★★ | ★★★★ |
| Risk of spaghetti | High | Low | Medium-Low |
| Best fit for v1 scope | Overkill in reverse | Overkill | **Optimal** |

## Selected Option

**Selected Option:** Option C — Pragmatic Balance

**Selection Reason:** Option C provides the best trade-off for a v1 TUI file manager targeting ~500–800 lines of Python. It preserves the single-file distribution simplicity critical for a WSL utility (copy one file into PATH), while internal class boundaries keep the code organized, testable, and extensible. Option A would become unmaintainable as features accumulate. Option B is architecturally correct but adds unnecessary scaffolding for a single-developer v1 with bounded scope. Option C defers the multi-file split to a future iteration when the codebase warrants it — the class structure makes that extraction straightforward.

## Component / Module Structure

### 1. Main Application Class (`WslCommander`)

**Role:** Application lifecycle, main event loop, coordination between panels, input dispatch, and top-level UI layout.

**Responsibilities:**
- Initialize `curses` (color pairs, terminal setup, hide cursor)
- Create and manage two `FilePanel` instances (left and right panes)
- Track which panel is active (`active_panel: int = 0` for left, `1` for right)
- Run the main loop: `while running: handle_input(key); draw()`
- Dispatch keystrokes to the appropriate handler (navigation, file ops, app control)
- Coordinate copy/move between panes (source = active panel, destination = inactive panel)
- Handle terminal resize (`curses.KEY_RESIZE`)
- Cleanup on exit (restore terminal state)

### 2. UI Rendering Components

**Header Bar:**
- Displays current directory path for each panel
- Shows "[L]" or "[R]" indicator for active/inactive pane
- Rendered as a single line at the top of the terminal

**Dual Panels:**
- Left panel occupies columns 0 to `(cols // 2) - 1`
- Right panel occupies columns `(cols // 2)` to `cols - 1`
- Vertical separator line at `cols // 2`
- Each panel shows a scrollable file list with:
  - Selection highlight (reverse video or color bar)
  - Directory indicator: `[dirname]/` format
  - File columns: name, size, date/time, permissions (truncated to fit panel width)
- Panel header: column labels ("Name", "Size", "Date", "Attr") — drawn once per refresh

**Status Bar:**
- Bottom line of the terminal
- Shows context-sensitive key hints: `F3 View  F5 Copy  F6 Move  F7 MkDir  F8 Delete  F10 Quit`
- For the active panel, may show selected file count or current filter

**Dialog Overlays (modal):**
- Confirmation dialog for delete: centered box with "Delete <filename>? (y/N)"
- Input prompt for mkdir/rename: single-line input at bottom or centered
- Progress indicator for copy/move: bottom bar showing bytes transferred
- File viewer: full-screen pager using `curses` pad, scrollable with Up/Down/PgUp/PgDn

### 3. File System Operations Module

**Role:** Stateless functions that perform file operations with error handling and progress callbacks.

**Design note:** All functions return `bool` for success/failure and accept an optional `progress_callback` for copy/move operations. Errors are reported via return values (not exceptions) to keep the TUI responsive.

**Operations:**
- `copy_file(src, dst, progress_cb=None)` — copies a single file with progress
- `copy_directory(src, dst, progress_cb=None)` — recursive directory copy
- `move_file(src, dst, progress_cb=None)` — rename/move (within same filesystem = `os.rename`, cross-filesystem = copy + delete)
- `delete_file(path)` — single file deletion
- `delete_directory(path)` — recursive directory deletion (with confirmation called by UI layer)
- `create_directory(path)` — `os.makedirs(path, exist_ok=False)`
- `rename_file(old, new)` — simple rename via `os.rename`
- `read_file_preview(path, max_size=1024*1024)` — read first N bytes for the file viewer

### 4. Input Handling and Key Mapping

**Role:** Translate raw `curses` key codes into semantic actions.

**Architecture:** `WslCommander.handle_input(key)` is the central dispatcher. It uses a `KEYBINDINGS` dictionary mapping key codes to action names, then delegates to the appropriate method.

**Key categories:**
- **Navigation:** `KEY_UP`, `KEY_DOWN`, `KEY_PPAGE`, `KEY_NPAGE`, `KEY_HOME`, `KEY_END` — delegated to `active_panel.navigate()`
- **Panel switching:** `\t` (Tab) — toggles `active_panel`
- **Directory traversal:** `\n` (Enter) — `active_panel.enter_directory()`, `KEY_BACKSPACE` or `27` (Esc) — `active_panel.go_up()`
- **File operations:** F3 (view), F5 (copy), F6 (move/rename), F7 (mkdir), F8 (delete)
- **App control:** F10 or `q` — quit
- **Sort toggle:** Ctrl+F2 or F2 — cycle sort key (name → extension → size → date)
- **Filter:** Ctrl+S — prompt for wildcard filter pattern
- **Drive/root:** Ctrl+\\ — go to root directory; Ctrl+D — prompt for path

### 5. File List State Management (`FilePanel`)

**Role:** Per-pane state container holding the current directory, file listing, cursor position, scroll offset, sort configuration, and filter pattern.

**State fields:**
- `current_dir: str` — absolute path to the directory being displayed
- `files: list[dict]` — cached file listing; each entry is `{"name", "path", "size", "mtime", "mode", "is_dir"}`
- `cursor_index: int` — index into `files` of the highlighted entry (0-based)
- `scroll_offset: int` — first visible row index (for scrolling)
- `sort_key: str` — one of `"name"`, `"extension"`, `"size"`, `"date"`
- `sort_reverse: bool` — ascending/descending toggle
- `filter_pattern: str | None` — wildcard pattern for filtering (e.g., `"*.py"`), `None` means no filter
- `selected_files: set[str]` — set of selected filenames (for multi-select with Space or Insert)

**Lifecycle:**
- `refresh()` — re-reads `os.listdir()` + `os.stat()` for each file in `current_dir`, applies sort and filter, preserves cursor position on surviving entries
- Called on: directory change, file operation completion, manual refresh (Ctrl+R)

### 6. Sorting and Filtering

**Sorting:**
- Applied in `FilePanel.refresh()` after reading the file list
- Sort key selected cyclically: Name → Extension → Size → Date → (back to Name)
- Directories are always listed before files (Total Commander convention)
- Sort is stable; secondary sort is always by name

**Filtering:**
- Applied in `FilePanel.refresh()` after sorting
- Uses `fnmatch.fnmatch(filename, pattern)` for wildcard matching
- Filter pattern is displayed in the panel header or status bar when active
- Empty/None pattern = show all files (except hidden, unless toggled)

## Data Flow

```
┌─────────────────────────────────────────────────────┐
│                    User Keystroke                     │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  WslCommander.handle_input(key)                      │
│  ┌───────────────────────────────────────────────┐  │
│  │ 1. Look up key in KEYBINDINGS → action name   │  │
│  │ 2. Dispatch to handler method                 │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  Navigation keys → active_panel.navigate(direction)   │
│  Tab            → toggle active_panel                │
│  Enter          → active_panel.enter_directory()     │
│  F5 (Copy)      → copy_file(active.get_selected(),   │
│                            inactive.current_dir)     │
│  F8 (Delete)    → confirm → delete_file(path)        │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  State Update                                        │
│  ┌───────────────────────────────────────────────┐  │
│  │ FilePanel.current_dir updated (if navigated)  │  │
│  │ FilePanel.cursor_index updated (if navigated) │  │
│  │ FilePanel.scroll_offset recalculated          │  │
│  │ FilePanel.refresh() called (if dir changed)   │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  WslCommander.draw()                                 │
│  ┌───────────────────────────────────────────────┐  │
│  │ 1. stdscr.erase()                             │  │
│  │ 2. Draw header (current dirs for both panes)  │  │
│  │ 3. Draw vertical separator                    │  │
│  │ 4. Draw left panel  (FilePanel.render_rows()) │  │
│  │ 5. Draw right panel (FilePanel.render_rows()) │  │
│  │ 6. Draw status bar (key hints)                │  │
│  │ 7. stdscr.refresh()                           │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Terminal Display (rendered TUI)                     │
│  ┌──────────────────────┬──────────────────────┐    │
│  │ /home/user/projects  │ /home/user/docs      │    │
│  │ Name  │Size  │Date   │ Name  │Size  │Date   │    │
│  │ [src]/ │ 4 KB │Jul 09 │ [img]/ │ 8 KB │Jul 08 │    │
│  │ >main.p│ 2 KB │Jul 09 │ >notes.│ 1 KB │Jul 07 │    │
│  │ readme.│ 1 KB │Jul 08 │ todo.tx│ 0.5KB│Jul 01 │    │
│  └──────────────────────┴──────────────────────┘    │
│  F3 View  F5 Copy  F6 Move  F7 MkDir  F8 Del  F10 Q │
└─────────────────────────────────────────────────────┘
```

**Key design decisions in the flow:**

1. **Input → State → Render** is a strict unidirectional cycle. Input handlers never call draw methods directly. The main loop always calls `draw()` after `handle_input()`.
2. **File operations are blocking** in v1 (simplifies progress display). The event loop pauses during copy/move — progress is rendered inline before returning to the main loop.
3. **`refresh()` is explicit.** Directory re-reading only happens when the directory actually changes or the user manually refreshes (Ctrl+R). This avoids unnecessary `stat` calls on every keystroke.
4. **Modality** is handled by a `mode` enum on `WslCommander`: `NORMAL`, `INPUT` (for mkdir/rename prompts), `CONFIRM` (for delete confirmation), `VIEW` (for file viewer). The `handle_input()` dispatcher checks mode first.

## File Structure

```
wsl-commander/
├── lcom                          # Main executable script (~500–800 lines)
│                                 #   Shebang: #!/usr/bin/env python3
│                                 #   Contains all classes and functions
├── docs/
│   ├── 01-plan/
│   │   └── wsl-commander.plan.md
│   ├── 02-architecture/
│   │   └── wsl-commander.architecture.md
│   └── ...
└── README.md                     # Usage instructions
```

**No submodules in v1.** The entire application is a single Python file. If the codebase grows beyond ~1500 lines in a future iteration, the classes can be extracted into a package:

```
lcom/                            # Future v2 package structure (NOT for v1)
├── __init__.py
├── __main__.py
├── app.py                       # WslCommander class
├── panel.py                     # FilePanel class
├── fsops.py                     # File operation functions
├── ui.py                        # Rendering helpers
├── keys.py                      # Keybindings
└── utils.py                     # format_size, format_date, etc.
```

## Function Signatures

### Entry Point

```python
def main() -> None:
    """Entry point. Initializes curses and runs WslCommander."""
```

### WslCommander Class

```python
class WslCommander:
    """Main application controller for Wsl Commander."""

    def __init__(self, stdscr: "curses.window") -> None:
        """Initialize curses colors, create FilePanels, set initial state.

        Args:
            stdscr: The curses standard screen object from curses.wrapper().
        """

    def run(self) -> None:
        """The main event loop: read keys, dispatch, render. Runs until quit."""

    def handle_input(self, key: int) -> bool:
        """Dispatch a single keystroke to the appropriate handler.

        Args:
            key: Raw key code from stdscr.getch().

        Returns:
            False if the application should quit, True otherwise.
        """

    def draw(self) -> None:
        """Render the entire TUI: header, panels, separator, status bar."""

    def refresh_panel(self, panel_index: int) -> None:
        """Force a panel to re-read its directory and re-render.

        Args:
            panel_index: 0 for left panel, 1 for right panel.
        """

    # --- Internal handlers (called by handle_input) ---

    def _navigate_active(self, direction: str, count: int = 1) -> None:
        """Navigate cursor in the active panel.

        Args:
            direction: One of 'up', 'down', 'pgup', 'pgdn', 'home', 'end'.
            count: Number of steps (default 1, larger for pgup/pgdn).
        """

    def _switch_panel(self) -> None:
        """Toggle the active panel between left (0) and right (1)."""

    def _enter_directory(self) -> None:
        """Enter the directory under cursor in the active panel."""

    def _go_up(self) -> None:
        """Go to parent directory in the active panel."""

    def _copy_file(self) -> None:
        """Copy selected file(s) from active panel to inactive panel's directory."""

    def _move_file(self) -> None:
        """Move/rename selected file(s) from active panel to inactive panel's directory."""

    def _delete_file(self) -> None:
        """Delete selected file(s) with confirmation dialog."""

    def _create_directory(self) -> None:
        """Prompt for directory name and create it in the active panel's directory."""

    def _rename_file(self) -> None:
        """Prompt for new name and rename the selected file."""

    def _view_file(self) -> None:
        """Open the selected file in a scrollable pager."""

    def _toggle_sort(self) -> None:
        """Cycle the active panel's sort key (name → extension → size → date)."""

    def _set_filter(self) -> None:
        """Prompt for a wildcard filter pattern and apply to active panel."""

    def _handle_modal_input(self, key: int) -> bool:
        """Handle input when in a modal state (INPUT, CONFIRM, VIEW).

        Args:
            key: Raw key code.

        Returns:
            False if the modal should close and return to NORMAL, True otherwise.
        """

    def _show_message(self, text: str, duration: float = 1.5) -> None:
        """Show a temporary message on the status bar (e.g., error feedback).

        Args:
            text: Message to display.
            duration: How long to show in seconds (approximate, keypress-cleared).
        """
```

### FilePanel Class

```python
class FilePanel:
    """Manages the state and file listing for a single pane."""

    def __init__(self, start_dir: str, panel_width: int, panel_height: int) -> None:
        """Initialize a panel with the given starting directory and dimensions.

        Args:
            start_dir: Initial directory path (defaults to os.getcwd()).
            panel_width: Width in columns for this panel.
            panel_height: Height in rows for this panel's file list area.
        """

    def refresh(self) -> None:
        """Re-read the current directory, apply sort and filter, update file list.
        Preserves cursor position on the same file when possible.
        """

    def navigate(self, direction: str, count: int = 1) -> None:
        """Move the cursor within the file list.

        Args:
            direction: 'up', 'down', 'pgup', 'pgdn', 'home', 'end'.
            count: Number of steps. pgup/pgdn use visible_rows as step size.
        """

    def enter_directory(self) -> bool:
        """Change current_dir to the directory under the cursor.

        Returns:
            True if the directory was entered, False if no directory at cursor.
        """

    def go_up(self) -> None:
        """Change current_dir to the parent directory (if not at root)."""

    def get_selected(self) -> str | None:
        """Get the full path of the currently highlighted file.

        Returns:
            Absolute path or None if the file list is empty.
        """

    def get_selected_all(self) -> list[str]:
        """Get full paths of all selected files (or cursor file if none selected).

        Returns:
            List of absolute paths.
        """

    def sort_by(self, key: str) -> None:
        """Set the sort key and re-sort.

        Args:
            key: 'name', 'extension', 'size', or 'date'.
        """

    def toggle_sort_reverse(self) -> None:
        """Toggle ascending/descending sort order."""

    def filter_by(self, pattern: str | None) -> None:
        """Apply a wildcard filter. None or '' clears the filter.

        Args:
            pattern: fnmatch-compatible wildcard pattern (e.g., '*.py').
        """

    def render_rows(self, stdscr: "curses.window", col_offset: int, row_offset: int) -> None:
        """Render the file list into the curses window.

        Args:
            stdscr: The curses window to draw on.
            col_offset: Starting column for this panel.
            row_offset: Starting row for the file list (below header).
        """

    # --- Internal helpers ---

    def _ensure_cursor_visible(self) -> None:
        """Adjust scroll_offset so cursor_index is within the visible area."""

    def _format_file_row(self, file_info: dict, width: int) -> str:
        """Format a single file entry into a display string fitting the given width.

        Args:
            file_info: Dict with keys: name, size, mtime, mode, is_dir.
            width: Available column width.

        Returns:
            Formatted string like " [dir]/  4.2 KB  2026-07-09  rwxr-xr-x".
        """
```

### File Operations Functions

```python
# All file operation functions are top-level (module-level) functions.

def copy_file(src: str, dst: str, progress_callback: Callable[[int, int], None] | None = None) -> bool:
    """Copy a single file from src to dst.

    Args:
        src: Source file path.
        dst: Destination file path.
        progress_callback: Called with (bytes_copied, total_bytes) during copy.

    Returns:
        True on success, False on failure.
    """

def copy_directory(src: str, dst: str, progress_callback: Callable[[int, int], None] | None = None) -> bool:
    """Recursively copy a directory from src to dst.

    Args:
        src: Source directory path.
        dst: Destination directory path.
        progress_callback: Called with (files_copied, total_files) during copy.

    Returns:
        True on success, False on failure.
    """

def move_file(src: str, dst: str, progress_callback: Callable[[int, int], None] | None = None) -> bool:
    """Move a file or directory from src to dst.
    Uses os.rename for same-filesystem moves, copy+delete for cross-filesystem.

    Args:
        src: Source path.
        dst: Destination path.
        progress_callback: Called during cross-filesystem moves only.

    Returns:
        True on success, False on failure.
    """

def delete_file(path: str) -> bool:
    """Delete a single file.

    Args:
        path: Path to the file to delete.

    Returns:
        True on success, False on failure.
    """

def delete_directory(path: str) -> bool:
    """Recursively delete a directory.

    Args:
        path: Path to the directory to delete.

    Returns:
        True on success, False on failure.
    """

def create_directory(path: str) -> bool:
    """Create a directory (including parents if needed).

    Args:
        path: Path to create.

    Returns:
        True on success, False on failure.
    """

def rename_file(old: str, new: str) -> bool:
    """Rename a file or directory.

    Args:
        old: Current path.
        new: New path.

    Returns:
        True on success, False on failure.
    """

def read_file_content(path: str, max_size: int = 1_048_576) -> str | None:
    """Read file content for the file viewer.

    Args:
        path: Path to the file to read.
        max_size: Maximum bytes to read (default 1 MB).

    Returns:
        File content as string, or None if file is binary or too large.
    """
```

### Utility Functions

```python
def format_size(size_bytes: int) -> str:
    """Format a byte count into a human-readable size string.

    Args:
        size_bytes: File size in bytes.

    Returns:
        Formatted string like '4.2 KB', '1.3 MB', '850 B'.
    """

def format_date(mtime: float) -> str:
    """Format a file modification timestamp into a display string.

    Args:
        mtime: Modification time as a Unix timestamp (float from os.stat().st_mtime).

    Returns:
        Formatted string like '2026-07-09' or 'Jul 09 14:30'.
    """

def format_permissions(mode: int) -> str:
    """Convert a file mode integer into a permission string.

    Args:
        mode: File mode from os.stat().st_mode.

    Returns:
        String like 'rwxr-xr-x' or 'rw-r--r--'.
    """

def safe_filename_display(name: str, max_width: int) -> str:
    """Truncate a filename for display, handling UTF-8 width correctly.

    Args:
        name: The filename (may contain multi-byte UTF-8 characters).
        max_width: Maximum display width in terminal columns.

    Returns:
        Truncated string with '…' suffix if too long.
    """
```

## Constants and Configuration

```python
# --- Key Bindings ---
# Maps curses key codes to semantic action names.
# Structured as a dict for clarity; consumed by WslCommander.handle_input().

KEYBINDINGS: dict[int, str] = {
    # Navigation (active panel)
    curses.KEY_UP:       "nav_up",
    curses.KEY_DOWN:     "nav_down",
    curses.KEY_PPAGE:    "nav_pgup",
    curses.KEY_NPAGE:    "nav_pgdn",
    curses.KEY_HOME:     "nav_home",
    curses.KEY_END:      "nav_end",

    # Panel switching
    ord('\t'):           "switch_panel",   # Tab

    # Directory traversal
    ord('\n'):           "enter_dir",       # Enter
    curses.KEY_BACKSPACE: "go_up",          # Backspace
    27:                  "go_up",           # Esc (also go up)

    # File operations (F-keys)
    curses.KEY_F3:       "view",
    curses.KEY_F5:       "copy",
    curses.KEY_F6:       "move",
    curses.KEY_F7:       "mkdir",
    curses.KEY_F8:       "delete",

    # Application control
    curses.KEY_F10:      "quit",
    ord('q'):            "quit",
    ord('Q'):            "quit",

    # Refresh
    18:                  "refresh",         # Ctrl+R
    ord('r'):            "refresh",         # (alternative, in NORMAL mode)

    # Sort
    curses.KEY_F2:       "sort_toggle",
    6:                   "sort_toggle",     # Ctrl+F

    # Filter
    19:                  "filter",          # Ctrl+S

    # Toggle hidden files
    8:                   "toggle_hidden",   # Ctrl+H

    # Drive/root
    28:                  "goto_root",       # Ctrl+\
    4:                   "goto_path",       # Ctrl+D (prompt for path)
}

# --- Color Pairs ---
# curses color pair indices. Initialized in WslCommander.__init__().

COLOR_PAIRS: dict[str, int] = {
    "header":        1,   # Header bar (white on blue)
    "active_panel":  2,   # Active panel border/highlight
    "inactive_panel": 3,  # Inactive panel border
    "selected":      4,   # Selected/highlighted file (reverse: black on white)
    "directory":     5,   # Directory names (cyan)
    "executable":    6,   # Executable files (green)
    "symlink":       7,   # Symbolic links (magenta)
    "status":        8,   # Status bar (white on blue)
    "error":         9,   # Error messages (red)
    "dialog":       10,   # Dialog boxes (white on black with border)
}

# Colors are applied as:
# curses.init_pair(COLOR_PAIRS["header"], curses.COLOR_WHITE, curses.COLOR_BLUE)
# Usage: stdscr.addstr(y, x, text, curses.color_pair(COLOR_PAIRS["header"]))

# --- Layout Constants ---

HEADER_HEIGHT: int = 2          # Rows reserved for header (directory paths + column labels)
STATUS_HEIGHT: int = 1          # Rows reserved for status bar at bottom
MIN_PANEL_WIDTH: int = 20       # Minimum columns per panel before truncation kicks in
PANEL_SEPARATOR: str = "│"      # Vertical separator character (Unicode box drawing)

# --- Defaults ---

DEFAULT_SORT_KEY: str = "name"          # Initial sort order
DEFAULT_SORT_REVERSE: bool = False      # Ascending by default
DEFAULT_SHOW_HIDDEN: bool = False       # Hide dotfiles by default
DEFAULT_FILTER: str | None = None       # No filter by default

# --- File Viewer ---

VIEWER_MAX_SIZE: int = 1_048_576        # 1 MB max for the built-in file viewer
VIEWER_TAB_WIDTH: int = 8               # Tab stop width in viewer

# --- Progress ---

COPY_BUFFER_SIZE: int = 64 * 1024       # 64 KB buffer for file copy operations
```

## Edge Cases & Error Handling Strategy

| Edge Case | Handling |
|---|---|
| Terminal too small (<80x24) | Show warning message: "Terminal too small. Resize to at least 80x24." |
| Terminal resize (SIGWINCH) | `curses.KEY_RESIZE` → recalculate panel dimensions → redraw |
| Permission denied on directory | Show error in status bar, stay in current directory, don't crash |
| File deleted externally while listed | `FileNotFoundError` caught in operations → status bar error message |
| Binary file in viewer | Detect null bytes → show "Binary file — cannot display" |
| Copy/move overwrite | Prompt: "File exists. Overwrite? (y/N/a)" (a = all, for multi-file ops) |
| Symlink loops | `os.stat()` handles symlinks; `is_dir` uses `os.path.isdir()` which follows |
| Very long filenames | Truncate with `safe_filename_display()` using `…` ellipsis |
| Non-UTF-8 filenames | Python 3 handles via `surrogateescape` — display as-is, errors caught |
| Empty directory | Show "(empty)" message in panel body instead of crashing |
| Root directory ("/") | `go_up()` is a no-op; parent of "/" is "/" |

## Link to Plan

[docs/01-plan/wsl-commander.plan.md](../01-plan/wsl-commander.plan.md)
