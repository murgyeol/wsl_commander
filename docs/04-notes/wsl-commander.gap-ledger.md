# Wsl Commander — Gap Ledger & Implementation Notes

- **Date:** 2026-07-09
- **Stage:** Do (Round 1/5)
- **Feature:** wsl-commander

## Status Summary

| Item | Status | Details |
|---|---|---|
| Plan | ✅ Complete | docs/01-plan/wsl-commander.plan.md (Architecture Pro) |
| Architecture | ✅ Complete | docs/02-architecture/wsl-commander.architecture.md (DeepSeek V4 Pro) |
| Interface/Usage | ✅ Complete | docs/03-uiux/wsl-commander.uiux.md (Codex GPT-5.5) |
| JSON Design | ✅ Complete | docs/06-qwen-design/wsl-commander.design.json (DeepSeek V4 Pro) |
| **Do (Implementation)** | **✅ Complete** | `/home/won/wsl-commander/lcom` — 1000 lines |
| Lint | ✅ Clean | ruff check — all passed |
| Syntax | ✅ Clean | python3 -m py_compile passed |
| Runtime Test | ✅ Passed | `script -q -c` — TUI launched, dual-pane visible |
| Executable | ✅ | `chmod +x lcom` — file is executable |
| Git | ✅ | 초기 상태: docs/ 커밋됨, lcom 추가 pending |

## Deliverable

**Executable:** `/home/won/wsl-commander/lcom`
**Run command:** `python3 lcom` or `./lcom` (after install to PATH)
**Alias:** `lcom` (심볼릭 링크 /usr/local/bin/lcom 권장)

## Code Stats

- **1000 lines** of Python
- **4 classes:** `App` (base), `WslCommander` (main), `FilePanel` (pane state), `FileViewer` (pager)
- **12 file operation functions:** copy_file, move_file, delete_file, create_directory, rename_file, format_size, format_date, format_permissions, plus internal helpers
- **Dependencies:** Standard library only (`curses`, `os`, `shutil`, `stat`, `time`, `fnmatch`, `sys`, `locale`)
- **Lint:** 0 errors (ruff clean)
- **PEP 8:** Auto-formatted

## Implemented Features

| Feature | Status | Notes |
|---|---|---|
| Dual-pane TUI (left/right) | ✅ | Vertical separator `\|`, active/inactive color pairs |
| Header: paths + active indicator | ✅ | `Wsl Commander [L] /path [R] /path` |
| File listing: name, size, date, perm | ✅ | Columns auto-adjust to terminal width |
| Arrow key navigation | ✅ | Up/Down + PgUp/PgDown + Home/End |
| Tab to switch active pane | ✅ | Toggles active/inactive state |
| Enter directory | ✅ | Descends into full path |
| Backspace parent directory | ✅ | Preserves cursor on parent entry |
| Esc = parent dir / cancel dialog | ✅ | Normal mode: parent. Dialog mode: cancel |
| F2 cycle sort (name/ext/size/date) | ✅ | Dir before file grouping. Status bar shows sort |
| F3 file viewer (pager) | ✅ | FileViewer class — scroll, hex dump for binaries |
| F5 copy to other pane | ✅ | Progress callback, overwrite confirm, dir copy |
| F6 move/rename | ✅ | Move with progress, rename via input dialog |
| F7 create directory | ✅ | Input dialog, validation |
| F8 delete with confirmation | ✅ | y/N dialog, rmtree for dirs |
| F10/q quit | ✅ | Clean curses teardown |
| Ctrl+S quick filter | ✅ | fnmatch wildcard, auto-wraps bare terms in `*` |
| Ctrl+R refresh panels | ✅ | Reloads both panes |
| Color scheme (10 color pairs) | ✅ | Header=cyan, Active=blue, Selected=yellow, Dir=cyan, Status=green, Dialog=blue |
| Terminal resize (KEY_RESIZE) | ✅ | Handled via draw() on each loop iteration |
| UTF-8/Korean filenames | ✅ | locale-aware decode |
| Permission errors handled | ✅ | Status bar message, fallback path |
| File size formatting | ✅ | B/K/M/G/T with decimal precision |
| Date formatting | ✅ | Same-year: MM-DD HH:MM, older: YYYY-MM-DD |
| Dialog overlays | ✅ | Confirm (y/N) + Input (text entry) modes |
| Directive grouping before files | ✅ | Sort stable: dirs first, files after |
| Empty directory display | ✅ | Shows `<empty>` state via blank list |
| Progress callback for copy/move | ✅ | Status bar shows percentage + filename |

## Known Gaps (v1)

| # | Gap | Priority | Notes |
|---|---|---|---|
| G1 | 파일 선택 (multi-select) 미구현 | Medium | Space/Insert for marking multiple files |
| G2 | Progress bar (%, bytes) 개선 | Low | 현재는 텍스트 %, 향후 bar 표시 |
| G3 | Config file support | Low | 하드코딩 키바인딩, 향후 YAML/JSON config |
| G4 | Mouse support | Low | v1 non-goal |
| G5 | 파일/디렉토리 복사 충돌 해결 | Low | _unique_destination이 기본, 향후 merge/diff |
| G6 | Hidden file toggle | Low | `.`으로 시작하는 파일 숨기기 |
| G7 | F3 확장자별 뷰어 | Low | Text/Image/Hex 자동 선택 |
| G8 | Ctrl+D (go to directory) | Low | Architecture에 있으나 v1 생략 |
| G9 | Ctrl+\ (go to root) | Low | Architecture에 있으나 v1 생략 |
| G10 | Cross-filesystem move | Low | 현재 os.rename + fallback shutil.move |

## Recommendations

1. **Install:** `sudo ln -sf /home/won/wsl-commander/lcom /usr/local/bin/lcom`
2. **Next feature candidate:** multi-file selection (Space key) + batch copy/move/delete
3. **Large directory perf:** 10000+ files — 현재 os.listdir() + os.lstat() per file, O(n) OK
4. **Monitor:** curses lib on minimal WSL — `python3-tinfo` or equivalent may be needed

## Pipeline Summary

All 7 stages complete. PDCA Round 1/5 finished.
- Plan → Architecture → Interface → JSON Design → **Do** → Lint/Test → Notes
- Do model: Codex GPT-5.5 (Ollama qwen2.5-coder blocked by user policy)
- Check-1/Style: ruff
- Check-2/Syntax: python3 -m py_compile
- Runtime: script PTY test passed
