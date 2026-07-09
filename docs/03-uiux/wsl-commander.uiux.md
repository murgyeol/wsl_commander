# Wsl Commander Interface/Usage Design

- Date: 2026-07-09
- Stage: Interface/Usage Design
- Iteration: Round 1/5
- Feature: wsl-commander
- Project Type: CLI/TUI

## Source Documents

- Plan: docs/01-plan/wsl-commander.plan.md
- Architecture: docs/02-architecture/wsl-commander.architecture.md

## Context Anchor

| Field | Content |
|---|---|
| WHY | Need a dual-pane file manager for WSL (Linux terminal) inspired by Total Commander / Double Commander |
| WHO | WSL users, Linux terminal users who prefer keyboard-driven file management |
| RISK | TUI complexity, cross-platform terminal compatibility, performance with large directories |
| SUCCESS | Working dual-pane TUI file manager with common file operations, keyboard shortcuts, and visual file listing |
| SCOPE | TUI-based dual-pane file manager for Linux/WSL terminal |

## Usage Goal

Provide a lightweight, keyboard-driven dual-pane file manager for Linux/WSL terminals. The user should be able to launch `lcom`, browse two directories side by side, switch the active pane, navigate directories, inspect file metadata, and perform common file operations without leaving the terminal.

The primary usage goal is fast file management through predictable Total Commander-style controls:

- Compare source and destination directories side by side.
- Copy or move files from the active pane to the inactive pane.
- Rename, delete, create directories, and view files through keyboard shortcuts.
- Search/filter the current pane quickly.
- Sort file listings by name, extension/type, size, or date.
- Keep status and error feedback visible without writing log files.

## User or Developer Flow

1. User launches the executable:

   ```sh
   python3 lcom
   ```

   or, after quick install:

   ```sh
   lcom
   ```

2. The TUI opens in the current working directory with two side-by-side panels.
3. The left panel is active by default unless implementation chooses to persist no state and initialize both panes equally from `os.getcwd()`.
4. User navigates the active panel with arrow keys, PageUp/PageDown, Home/End, Enter, and Backspace.
5. User switches panes with Tab.
6. File operations use the active pane as the source context:

   - F3 views the highlighted file.
   - F5 copies selected/highlighted item(s) to the inactive pane directory.
   - F6 moves selected/highlighted item(s) to the inactive pane directory, or renames when the destination is the same logical directory/name prompt.
   - F7 creates a directory in the active pane.
   - F8 deletes selected/highlighted item(s) after confirmation.
   - F10 exits the application.

7. After each directory change or file operation, the affected panel refreshes its file list.
8. Status bar messages report success, failure, current filter/sort state, and selected file metadata.
9. Developer implementation follows the selected architecture: one executable `lcom` file using Python `curses`, organized internally around `WslCommander`, `FilePanel`, file operation helpers, constants, and utility functions.

## Commands or Interface Contract

Describe:

- Keyboard navigation (arrow keys, Tab, Enter, Backspace)
- F-key shortcuts (F3=view, F5=copy, F6=move/rename, F7=mkdir, F8=delete, F10=quit)
- Quick search (Ctrl+S)
- Sorting toggles
- How the dual-pane interaction works
- Dialog windows (confirm delete, input for mkdir/rename)

Keyboard navigation:

- Up Arrow: move selection up one row in the active pane.
- Down Arrow: move selection down one row in the active pane.
- PageUp: scroll/move up one visible page in the active pane.
- PageDown: scroll/move down one visible page in the active pane.
- Home: move selection to the first visible/listed item.
- End: move selection to the last listed item.
- Tab: switch active pane between left and right.
- Enter: enter highlighted directory, or view/open behavior for files only if explicitly mapped in implementation; v1 reserves F3 for view.
- Backspace: go to parent directory in the active pane.
- Esc: go to parent directory in normal mode; cancel dialogs in modal mode.
- q: quit in normal mode.

F-key shortcuts:

- F3: view highlighted file in a read-only pager.
- F5: copy highlighted/selected item(s) from active pane to inactive pane current directory.
- F6: move highlighted/selected item(s) from active pane to inactive pane current directory; when used for rename flow, prompt for a new filename.
- F7: prompt for directory name and create it in active pane current directory.
- F8: show delete confirmation dialog, then delete highlighted/selected item(s) on `y`/`Y`.
- F10: quit application.

Quick search:

- Ctrl+S: open a text input prompt for a quick filter/search pattern.
- Pattern syntax uses shell-style wildcards through `fnmatch` behavior, for example `*.py`, `README*`, or `*test*`.
- Empty input clears the filter.
- Filter applies only to the active pane.
- Current filter is shown in the status bar or panel header.

Sorting toggles:

- F2: cycle active pane sort key: name -> extension/type -> size -> date -> name.
- Repeated F2 presses move to the next sort mode.
- Directories remain grouped before files regardless of sort key.
- Secondary sort is by filename for stable, predictable ordering.
- If reverse sorting is implemented in v1, Shift+F2 or a repeated modifier action may toggle ascending/descending order; otherwise sorting is ascending except where date sorting may display newest first if chosen by implementation.

Dual-pane interaction:

- Exactly one pane is active at a time.
- The active pane uses a stronger highlight for its border/header and selected row.
- The inactive pane remains visible and is the default destination for copy/move operations.
- Each pane owns independent state: current directory, cursor index, scroll offset, sort key, reverse flag, filter pattern, and file list cache.
- Copy and move source is always the active pane selection.
- Copy and move destination is the inactive pane current directory unless a rename dialog explicitly prompts for a different name.
- Directory navigation in one pane does not change the other pane.

Dialog windows:

- Confirm delete dialog: centered modal box with the target name/count and `Delete? (y/N)`.
- Delete confirmation accepts `y`/`Y` to proceed and `n`/`N`, Esc, or Enter on default No to cancel.
- Mkdir dialog: centered or bottom prompt with a single-line text input for the directory name.
- Rename dialog: centered or bottom prompt prefilled with the current filename when feasible.
- Text input supports printable UTF-8 characters, Backspace, Enter to submit, and Esc to cancel.
- Dialogs are modal: background panels remain visible but do not receive navigation keys until the dialog closes.

## Inputs

- Keyboard input mapping (all keys and their actions)
- Mouse: not supported in v1

Keyboard input mapping:

| Key | Action |
|---|---|
| Up Arrow | Move selection up in active pane |
| Down Arrow | Move selection down in active pane |
| Left Arrow | No required action in v1; may mirror Backspace only if implementation keeps behavior documented |
| Right Arrow | No required action in v1; may mirror Enter only if implementation keeps behavior documented |
| PageUp | Move up by one visible page |
| PageDown | Move down by one visible page |
| Home | Move to first listed item |
| End | Move to last listed item |
| Tab | Switch active pane |
| Enter | Enter highlighted directory; submit active dialog input |
| Backspace | Go to parent directory; delete previous character in text input dialogs |
| Esc | Go to parent directory in normal mode; cancel active dialog/viewer in modal mode |
| F2 | Cycle sort key |
| F3 | View highlighted file |
| F5 | Copy to inactive pane directory |
| F6 | Move to inactive pane directory or start rename flow |
| F7 | Create directory dialog |
| F8 | Delete confirmation dialog |
| F10 | Quit |
| Ctrl+S | Quick search/filter dialog |
| Ctrl+R | Refresh active panel file list |
| Ctrl+D | Prompt for directory path if implemented from architecture |
| Ctrl+\ | Go to filesystem root if implemented from architecture |
| q | Quit in normal mode |
| y/Y | Confirm destructive action in confirm dialog |
| n/N | Cancel destructive action in confirm dialog |
| Printable text | Append character in text input dialogs |

Mouse: not supported in v1. Mouse clicks, wheel scrolling, drag selection, and context menus are intentionally out of scope.

## Outputs

- TUI screen layout description (top to bottom):
  - Header bar (program name, current path, drive info)
  - Dual panels (left and right, each showing file list)
  - Separator column between panels
  - Status bar (key hints, file count, selected file info)
- Each panel shows: filename, size, date, permissions
- Colors: directories highlighted, different colors for file types
- Info panel at bottom with file count and total size

TUI screen layout description, top to bottom:

1. Header bar:

   - Full-width top row.
   - Shows program name `Wsl Commander`.
   - Shows current path for left and right panes, truncated safely to fit.
   - Shows active pane indicator such as `[L]` or `[R]`.
   - Shows drive/root information relevant to WSL/Linux paths, for example `/`, `/mnt/c`, or current mount root when detectable.

2. Dual panels:

   - Left panel occupies the left half of the terminal.
   - Right panel occupies the right half of the terminal.
   - Each panel has a panel header row with column labels: `Name`, `Size`, `Date`, `Perm`.
   - Each panel shows a scrollable list of directory entries.
   - The selected row in the active pane is highlighted.
   - The selected row in the inactive pane may remain subtly marked but must not look active.
   - Long filenames are truncated with enough room preserved for size, date, and permission columns.

3. Separator column between panels:

   - A single vertical separator column divides left and right panels.
   - Separator should remain visible after terminal resize.
   - The separator is visual only; it is not interactive.

4. Status bar:

   - Near-bottom or bottom row.
   - Shows key hints: `F3 View  F5 Copy  F6 Move  F7 MkDir  F8 Delete  F10 Quit`.
   - Shows transient status messages such as permission errors, copy completion, delete cancellation, current filter, or current sort.
   - Shows selected file info when no higher-priority message is active.

5. Info panel at bottom:

   - Shows active pane file count and total size.
   - May show both pane summaries if terminal width allows.
   - For empty directories, shows `0 files` and an empty-state row in the active panel.

Each panel shows:

- Filename, with directory names visually indicated using trailing `/` or bracket style such as `[dirname]/`.
- Size, formatted with compact units for files and a placeholder such as `<DIR>` for directories.
- Date, based on modification time.
- Permissions, formatted from file mode, for example `drwxr-xr-x` or `-rw-r--r--`.

Colors:

- Active pane header/border uses the active color pair.
- Inactive pane uses a dimmer color pair.
- Selected row uses reverse video or a dedicated selection color pair.
- Directories are highlighted differently from regular files.
- Executable files, symlinks, hidden files, and common file types may use separate color pairs when terminal color support is available.
- Color setup must use `curses.init_pair()`.
- If color is unavailable, the interface must remain usable with attributes such as bold, dim, and reverse.

## Error Handling

- Permission denied errors shown in status bar
- Disk full errors during copy/move
- Invalid directory paths
- Unicode decode errors for filenames
- Terminal resize handling
- Empty directory display

Permission denied errors:

- Show `Permission denied: <path>` in the status bar.
- Do not crash or leave the TUI in a broken state.
- Keep the user in the current directory or restore the previous valid state.

Disk full errors during copy/move:

- Catch `OSError` conditions such as no space left on device.
- Show a clear status message: `Copy failed: disk full` or `Move failed: disk full`.
- Refresh source and destination panels after a failed partial operation when filesystem state may have changed.

Invalid directory paths:

- Reject nonexistent paths, file paths used as directories, and inaccessible directories.
- Show `Invalid directory: <path>` or a shorter truncated equivalent in the status bar.
- Preserve the previous current directory.

Unicode decode errors for filenames:

- Prefer Python filesystem APIs using native `str` paths under UTF-8 locale.
- Use safe replacement rendering for undecodable display text rather than failing the whole panel refresh.
- Korean filenames must display correctly when the terminal locale supports UTF-8.

Terminal resize handling:

- Handle `curses.KEY_RESIZE` and/or `SIGWINCH`.
- Recalculate rows, columns, panel widths, visible row counts, separator position, and truncation widths.
- Clamp cursor and scroll offsets after resize.
- If the terminal is too small, show a minimal status message such as `Terminal too small` instead of drawing overlapping panels.

Empty directory display:

- Show an empty list area with a simple row such as `(empty)`.
- File count displays `0 files`.
- Operations requiring a selected file should show `No file selected`.

## Logging

- No file logging in v1 (terminal-only status messages)

All operational feedback is displayed inside the TUI status bar or modal dialogs. The application must not create log files in v1. Unexpected recoverable errors should be converted to concise status messages. Fatal startup errors, such as missing `curses`, may print to stderr before the TUI starts.

## Configuration

- No config file in v1 — all settings hardcoded
- Hardcoded key bindings
- Hardcoded color scheme

Configuration is intentionally omitted from v1. Key bindings, color pairs, panel layout constants, default sort behavior, and file type color rules are module-level constants inside the single `lcom` executable.

Future versions may extract these constants into a config file, but v1 must not require any external files to run.

## Operational Notes

- Single executable: lcom
- Launch: python3 lcom from project directory
- Quick install: cp lcom ~/.local/bin/lcom
- Requires: Python 3.8+ with curses module

Operational expectations:

- The executable should include a shebang: `#!/usr/bin/env python3`.
- The executable should be runnable directly after `chmod +x lcom`.
- The project has no external pip dependencies in v1.
- The terminal should use a UTF-8 locale for correct Korean filename rendering.
- The application targets Linux/WSL terminals such as Windows Terminal, standard Linux terminal emulators, and tmux where curses keys are available.

## Implementation Notes for Do

- Single file lcom, Python with curses
- UTF-8 handling for Korean filenames
- All keyboard input must be handled via getch() with timeout
- Dialog windows for: confirm (y/n), text input (rename, mkdir)
- Color pairs must use curses.init_pair()
- Handle SIGWINCH for terminal resize

Implementation notes:

- Use the selected architecture option: single-file `lcom` with internal class boundaries.
- `WslCommander` owns curses setup, main loop, drawing, input dispatch, active pane coordination, modal state, and terminal resize behavior.
- `FilePanel` owns per-pane state: current directory, file list, cursor, scroll offset, sort key, sort direction, filter pattern, and selected files if multi-select is included.
- File operation helpers should wrap `shutil`, `os`, and `pathlib` operations with predictable error handling.
- Use `stdscr.getch()` with a timeout, such as `stdscr.timeout(...)`, so resize/status updates can be processed without blocking forever.
- Handle modal dialogs before normal key dispatch.
- Use `curses.init_pair()` during startup for all color pairs.
- Avoid writing temp files.
- Avoid requiring root privileges.
- After copy, move, delete, mkdir, or rename, refresh affected panels.
- Ensure drawing code catches layout constraints and prevents text overlap on narrow terminals.
