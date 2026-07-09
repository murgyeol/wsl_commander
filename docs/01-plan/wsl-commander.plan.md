# Wsl Commander Plan

- Date: 2026-07-09
- Stage: Plan
- Iteration: Round 1/5
- Feature: wsl-commander

## Context Anchor

| Field | Content |
|---|---|
| WHY | Need a dual-pane file manager for WSL (Linux terminal) inspired by Total Commander / Double Commander |
| WHO | WSL users, Linux terminal users who prefer keyboard-driven file management |
| RISK | TUI complexity, cross-platform terminal compatibility, performance with large directories |
| SUCCESS | Working dual-pane TUI file manager with common file operations, keyboard shortcuts, and visual file listing |
| SCOPE | TUI-based dual-pane file manager for Linux/WSL terminal |

## Problem Statement

WSL (Linux) users lack a native dual-pane file manager similar to Total Commander on Windows. Existing options like Double Commander have complex setups or heavy dependencies. A lightweight, keyboard-driven TUI file manager built specifically for the terminal would improve file management productivity on WSL.

## Goals

1. Dual-pane file browser showing directory contents in two side-by-side panels
2. Keyboard-driven navigation (arrow keys, Tab, F-key shortcuts)
3. Common file operations: copy, move, rename, delete, mkdir, view
4. File filtering and sorting (by name, size, date, type)
5. Directory tree navigation (up/down, enter directory, go back)
6. Command-line quick start: `lcom` launches the program
7. Built using Python with cross-platform terminal support

## Non-Goals

1. No GUI — pure terminal interface (TUI)
2. No remote file system support (FTP, SFTP, cloud) in v1
3. No file editing — view only in v1
4. No plugin system in v1
5. No archive/compression handling in v1

## Scope

- Single Python script `lcom` that runs as a TUI application
- Dual-pane file listing with current directory at top
- Navigation: Up/Down/PageUp/PageDown/Home/End
- Tab to switch active pane
- File operations via F-keys (F3=view, F5=copy, F6=move/rename, F7=mkdir, F8=delete)
- Directory tree: Enter to descend, Backspace/Esc to go up
- Drive/root selection
- File sorting by name, extension, size, date
- File filtering by wildcard pattern
- Status bar with key hints
- Minimal dependencies (only `curses`/standard library)

## Requirements

1. Dual-pane TUI with resizable columns
2. File listing with: filename, size, date, attributes
3. Directory navigation with visual indicators ([/] for directories)
4. File copying with progress indicator
5. File moving with progress indicator
6. File deletion with confirmation
7. Directory creation
8. File renaming
9. Quick file view with paging
10. Active pane switching (Tab)
11. Drive/directory selection
12. File sorting toggle (F2?)
13. Quick filter/search (Ctrl+S)
14. Exit with Esc or F10 or q

## Constraints

1. Must work in stock WSL terminal (Windows Terminal, tmux, etc.)
2. Python 3.8+ compatible (standard library only, no external pip packages)
3. Must handle UTF-8 filenames (Korean filenames)
4. Must not create temporary files or require root
5. Single executable script (`lcom` in PATH or run via `python3 lcom`)
6. Use Python's built-in `curses` library for TUI
7. Executable name: `lcom`

## Success Criteria

1. `python3 lcom` launches the TUI with two file panels
2. Arrow keys navigate files in both panels
3. Tab switches active pane
4. Enter descends into directories, Backspace goes up
5. F5 copies file, F6 moves/renames, F8 deletes with confirmation
6. F7 creates directory
7. File sizes, dates, permissions displayed correctly
8. UTF-8 filenames display correctly
9. F10 or q quits the program
10. Sorting by name/size/date works

## Risks

1. `curses` library may not be available on minimal WSL installs (usually in `python3-tinfo` or similar)
2. Terminal resize handling may have edge cases
3. Large directories (10000+ files) may cause performance issues
4. Color scheme may not render in all terminals

## Assumptions

1. Python 3.8+ is available
2. `curses` module is available or installable via system packages
3. Terminal supports UTF-8 and standard ANSI escape codes
4. WSL terminal emulator supports standard Linux terminal features

## Open Questions

1. Should scroll offset be per-pane or shared?
2. Should we support mouse clicks? (v1: no)
3. Should config file be used for key bindings? (v1: hardcoded)
4. Copy/move destination: always other pane's current directory?
