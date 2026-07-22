import os
import shutil
import json
import http.server
import socketserver
import urllib.parse
import subprocess
import threading
import time
import mimetypes
import zipfile
import tarfile

PORT = 8080

def safe_copy2(src, dst, *, follow_symlinks=True):
    """cross-filesystem 복사 시 메타데이터 에러를 방지하는 안전한 복사 함수"""
    try:
        shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
    except PermissionError:
        shutil.copyfile(src, dst, follow_symlinks=follow_symlinks)
        try:
            os.chmod(dst, 0o644)
        except Exception:
            pass

def sanitize_path(path):
    """경로 정규화 및 NUL 바이트 등 보안 검증을 수행하는 안전한 경로 반환 함수"""
    if not path or not isinstance(path, str):
        return None
    if '\x00' in path:
        return None
    try:
        norm = os.path.normpath(os.path.expanduser(path))
        return os.path.abspath(norm)
    except Exception:
        return None

class CommanderHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # 터미널 로그 간소화

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path_query = urllib.parse.parse_qs(parsed_url.query)

        # API: 초기 설정 정보 (사용자 홈 디렉토리 및 Windows C드라이브)
        if parsed_url.path == "/api/init":
            home_dir = os.path.expanduser("~")
            win_c = "/mnt/c" if os.path.exists("/mnt/c") else home_dir
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "home_dir": home_dir,
                "win_c": win_c
            }).encode('utf-8'))
            return

        # API: 디렉토리 목록 조회
        elif parsed_url.path == "/api/list":
            raw_path = path_query.get('path', [None])[0]
            dir_path = sanitize_path(raw_path)
            default_home = os.path.expanduser("~")
            if not dir_path or not os.path.exists(dir_path) or not os.path.isdir(dir_path):
                dir_path = default_home
            
            try:
                items = []
                # 상위 폴더 바로가기 추가
                parent = os.path.dirname(dir_path)
                if parent != dir_path:
                    items.append({"name": "..", "is_dir": True, "size": "-", "mtime": "-"})
                
                for entry in os.scandir(dir_path):
                    try:
                        stat = entry.stat()
                        items.append({
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            "size": stat.st_size if not entry.is_dir() else "-",
                            "mtime": int(stat.st_mtime)
                        })
                    except Exception:
                        continue # 접근 권한이 없는 파일 스킵
                
                # 폴더 우선 정렬 후 이름순 정렬
                items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"current_path": dir_path, "items": items}).encode('utf-8'))
            except Exception as e:
                self.send_error(500, str(e))
            return
            
        # API: 텍스트 파일 읽기 (16GB RAM 사양에 맞춘 고성능 32MB 프리뷰)
        elif parsed_url.path == "/api/read":
            raw_path = path_query.get('path', [None])[0]
            file_path = sanitize_path(raw_path)
            if file_path and os.path.isfile(file_path):
                try:
                    file_size = os.path.getsize(file_path)
                    max_read = 32 * 1024 * 1024 # 32MB 상향
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(max_read)
                    if file_size > max_read:
                        content += f"\n\n--- [안내: 대용량 파일입니다 ({file_size / (1024*1024):.1f} MB). 메모리 보호를 위해 상위 32MB만 표시합니다.] ---"
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(content.encode('utf-8'))
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(400, "Invalid file path")
            return

        # API: PDF 파일 스트리밍 (2MB 대용량 청크 버퍼 전송)
        elif parsed_url.path == "/api/view_pdf":
            raw_path = path_query.get('path', [None])[0]
            file_path = sanitize_path(raw_path)
            if file_path and os.path.isfile(file_path):
                try:
                    file_size = os.path.getsize(file_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/pdf')
                    self.send_header('Content-Disposition', 'inline')
                    self.send_header('Content-Length', str(file_size))
                    self.end_headers()
                    with open(file_path, 'rb') as f:
                        shutil.copyfileobj(f, self.wfile, length=2097152) # 2MB 청크 버퍼
                except (BrokenPipeError, ConnectionResetError):
                    pass # 브라우저(클라이언트)의 소켓 연결 조기 종료 정상 처리
                except Exception as e:
                    try:
                        self.send_error(500, str(e))
                    except Exception:
                        pass
            else:
                self.send_error(400, "Invalid file path")
            return

        # API: 미디어 (이미지/동영상/오디오) 초고속 스트리밍 (2MB 버퍼 & Range 지원)
        elif parsed_url.path == "/api/view_media":
            raw_path = path_query.get('path', [None])[0]
            file_path = sanitize_path(raw_path)
            if file_path and os.path.isfile(file_path):
                try:
                    file_size = os.path.getsize(file_path)
                    mime_type, _ = mimetypes.guess_type(file_path)
                    if not mime_type:
                        mime_type = 'application/octet-stream'
                    
                    range_header = self.headers.get('Range')
                    if range_header and range_header.startswith('bytes='):
                        parts = range_header.replace('bytes=', '').split('-')
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if parts[1] else file_size - 1
                        if end >= file_size:
                            end = file_size - 1
                        length = end - start + 1

                        self.send_response(206)
                        self.send_header('Content-Type', mime_type)
                        self.send_header('Accept-Ranges', 'bytes')
                        self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                        self.send_header('Content-Length', str(length))
                        self.end_headers()

                        with open(file_path, 'rb') as f:
                            f.seek(start)
                            chunk_size = 2097152 # 2MB 고속 버퍼
                            bytes_to_send = length
                            while bytes_to_send > 0:
                                read_len = min(chunk_size, bytes_to_send)
                                chunk = f.read(read_len)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                bytes_to_send -= len(chunk)
                    else:
                        self.send_response(200)
                        self.send_header('Content-Type', mime_type)
                        self.send_header('Accept-Ranges', 'bytes')
                        self.send_header('Content-Length', str(file_size))
                        self.end_headers()
                        with open(file_path, 'rb') as f:
                            shutil.copyfileobj(f, self.wfile, length=2097152) # 2MB 고속 버퍼
                except (BrokenPipeError, ConnectionResetError):
                    pass # 브라우저 연결 종료 처리
                except Exception as e:
                    try:
                        self.send_error(500, str(e))
                    except Exception:
                        pass
            else:
                self.send_error(400, "Invalid file path")
            return

        # API: 압축 파일 내부 목록 조회
        elif parsed_url.path == "/api/archive/list":
            raw_path = path_query.get('path', [None])[0]
            file_path = sanitize_path(raw_path)
            if file_path and os.path.isfile(file_path):
                try:
                    items = []
                    if zipfile.is_zipfile(file_path):
                        with zipfile.ZipFile(file_path, 'r') as zf:
                            for info in zf.infolist():
                                items.append({
                                    "name": info.filename,
                                    "is_dir": info.is_dir(),
                                    "size": info.file_size,
                                    "compressed_size": info.compress_size
                                })
                    elif tarfile.is_tarfile(file_path):
                        with tarfile.open(file_path, 'r:*') as tf:
                            for member in tf.getmembers():
                                items.append({
                                    "name": member.name,
                                    "is_dir": member.isdir(),
                                    "size": member.size,
                                    "compressed_size": member.size
                                })
                    else:
                        self.send_error(400, "Unsupported archive format")
                        return

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"file_path": file_path, "items": items}).encode('utf-8'))
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(400, "Invalid file path")
            return

        # 기본 페이지 (HTML)
        if parsed_url.path == "/" or parsed_url.path == "/index.html":
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
            return

        super().do_GET()

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        content_length = int(self.headers['Content-Length'])
        post_data = json.loads(self.rfile.read(content_length).decode('utf-8'))

        # API: 복사 (Copy)
        if parsed_url.path == "/api/copy":
            src_list = post_data.get('src')
            dst_dir = sanitize_path(post_data.get('dst_dir'))
            if not src_list or not dst_dir or not os.path.isdir(dst_dir):
                self.send_error(400, "Missing or invalid src or dst_dir")
                return

            if isinstance(src_list, str):
                src_list = [src_list]

            try:
                for src_raw in src_list:
                    src = sanitize_path(src_raw)
                    if not src or not os.path.exists(src):
                        continue
                    dst = os.path.join(dst_dir, os.path.basename(src))
                    if os.path.isdir(src):
                        if os.path.exists(dst):
                            continue
                        shutil.copytree(src, dst, copy_function=safe_copy2)
                    else:
                        safe_copy2(src, dst)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            except Exception as e:
                self.send_error(500, str(e))
            return

        # API: 압축 해제 (Extract)
        elif parsed_url.path == "/api/archive/extract":
            archive_path = sanitize_path(post_data.get('archive_path'))
            dst_dir = sanitize_path(post_data.get('dst_dir'))
            if not archive_path or not dst_dir or not os.path.exists(archive_path) or not os.path.isdir(dst_dir):
                self.send_error(400, "Invalid archive_path or dst_dir")
                return

            try:
                if zipfile.is_zipfile(archive_path):
                    with zipfile.ZipFile(archive_path, 'r') as zf:
                        abs_dst = os.path.abspath(dst_dir)
                        for member in zf.infolist():
                            target_path = os.path.abspath(os.path.join(dst_dir, member.filename))
                            if not target_path.startswith(abs_dst + os.sep) and target_path != abs_dst:
                                raise Exception(f"Security error: Zip Slip detected ({member.filename})")
                        zf.extractall(path=dst_dir)
                elif tarfile.is_tarfile(archive_path):
                    with tarfile.open(archive_path, 'r:*') as tf:
                        abs_dst = os.path.abspath(dst_dir)
                        for member in tf.getmembers():
                            target_path = os.path.abspath(os.path.join(dst_dir, member.name))
                            if not target_path.startswith(abs_dst + os.sep) and target_path != abs_dst:
                                raise Exception(f"Security error: Tar Slip detected ({member.name})")
                        tf.extractall(path=dst_dir)
                else:
                    self.send_error(400, "Unsupported archive format")
                    return

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            except Exception as e:
                self.send_error(500, str(e))
            return

        # API: 압축 생성 (Compress)
        elif parsed_url.path == "/api/archive/create":
            src_list = post_data.get('src')
            dst_path = sanitize_path(post_data.get('dst_path'))
            archive_format = post_data.get('format', 'zip').lower()

            if not src_list or not dst_path:
                self.send_error(400, "Missing src or dst_path")
                return

            if isinstance(src_list, str):
                src_list = [src_list]

            try:
                if archive_format == 'zip':
                    with zipfile.ZipFile(dst_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for src_raw in src_list:
                            src = sanitize_path(src_raw)
                            if not src or not os.path.exists(src):
                                continue
                            if os.path.isdir(src):
                                parent_dir = os.path.dirname(src)
                                for root, dirs, files in os.walk(src):
                                    for file in files:
                                        full_file = os.path.join(root, file)
                                        arcname = os.path.relpath(full_file, parent_dir)
                                        zf.write(full_file, arcname)
                            else:
                                zf.write(src, os.path.basename(src))
                elif archive_format in ('tar.gz', 'tgz', 'tar'):
                    mode = 'w:gz' if archive_format in ('tar.gz', 'tgz') else 'w'
                    with tarfile.open(dst_path, mode) as tf:
                        for src_raw in src_list:
                            src = sanitize_path(src_raw)
                            if not src or not os.path.exists(src):
                                continue
                            tf.add(src, arcname=os.path.basename(src))
                else:
                    self.send_error(400, "Unsupported target format")
                    return

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            except Exception as e:
                self.send_error(500, str(e))
            return

        # API: 텍스트 파일 저장
        elif parsed_url.path == "/api/save":
            file_path = sanitize_path(post_data.get('path'))
            content = post_data.get('content')
            if file_path and content is not None:
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    self.send_response(200)
                    self.end_headers()
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(400, "Invalid parameters")
            return

        # API: 폴더 생성 (Mkdir)
        elif parsed_url.path == "/api/mkdir":
            parent = sanitize_path(post_data.get('parent'))
            raw_name = post_data.get('name', '')
            # 디렉토리 이름에서 경로 조작 문자 제거 및 보정
            name = os.path.basename(os.path.normpath(raw_name.strip('/\\'))) if raw_name else None
            if not parent or not name or not os.path.isdir(parent):
                self.send_error(400, "Missing or invalid parent or name")
                return
            
            target = os.path.join(parent, name)
            try:
                os.makedirs(target, exist_ok=False)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            except FileExistsError:
                self.send_error(400, "Folder already exists")
            except Exception as e:
                self.send_error(500, str(e))
            return

        # API: 삭제 (Delete)
        elif parsed_url.path == "/api/delete":
            target_list = post_data.get('path')
            if not target_list:
                self.send_error(400, "Missing path")
                return
            
            if isinstance(target_list, str):
                target_list = [target_list]

            try:
                for target_raw in target_list:
                    target = sanitize_path(target_raw)
                    if not target or target == "/" or not os.path.exists(target):
                        continue
                    if os.path.isdir(target):
                        shutil.rmtree(target)
                    else:
                        os.remove(target)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            except Exception as e:
                self.send_error(500, str(e))
            return

# 프리미엄 듀얼 패널 TUI 스타일 UI를 갖춘 HTML 템플릿
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>WSL-Windows Commander</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --panel-bg: #1e293b;
            --text-color: #f8fafc;
            --accent-color: #3b82f6;
            --accent-hover: #2563eb;
            --border-color: #334155;
            --folder-color: #fbbf24;
            --file-color: #94a3b8;
            --archive-color: #a855f7;
            --media-color: #38bdf8;
        }
        body {
            margin: 0;
            padding: 0;
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        header {
            background-color: #020617;
            padding: 10px 20px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        header h1 {
            margin: 0;
            font-size: 1.2rem;
            color: var(--accent-color);
        }
        .main-container {
            display: flex;
            flex: 1;
            padding: 15px;
            gap: 15px;
            overflow: hidden;
        }
        .panel {
            flex: 1;
            background-color: var(--panel-bg);
            border: 2px solid var(--border-color);
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        .panel.active-panel {
            border-color: var(--accent-color) !important;
            box-shadow: 0 0 12px rgba(59, 130, 246, 0.35);
        }
        .panel-header {
            background-color: #0f172a;
            padding: 8px 12px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .panel-header-title {
            cursor: pointer;
            font-weight: bold;
            padding: 3px 8px;
            border-radius: 4px;
            user-select: none;
            color: var(--accent-color);
            transition: background-color 0.2s, color 0.2s;
        }
        .panel-header-title:hover {
            background-color: var(--accent-color);
            color: #ffffff;
        }
        .nav-btn {
            background-color: #334155;
            color: #f8fafc;
            border: 1px solid #475569;
            padding: 3px 8px;
            font-size: 0.85rem;
            border-radius: 4px;
            cursor: pointer;
            user-select: none;
            transition: all 0.2s;
        }
        .nav-btn:hover:not(:disabled) {
            background-color: var(--accent-color);
            color: #ffffff;
            border-color: var(--accent-color);
        }
        .nav-btn:disabled {
            opacity: 0.35;
            cursor: not-allowed;
        }
        .sync-path-btn {
            background-color: #334155;
            color: #f8fafc;
            border: 1px solid #475569;
            padding: 4px 10px;
            font-size: 0.82rem;
            border-radius: 4px;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
        }
        .sync-path-btn:hover {
            background-color: var(--accent-color);
            color: #ffffff;
            border-color: var(--accent-color);
        }
        .path-input {
            flex: 1;
            background: #1e293b;
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 6px 10px;
            border-radius: 4px;
            font-family: monospace;
        }
        .file-list-container {
            flex: 1;
            overflow-y: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-family: monospace;
        }
        th, td {
            text-align: left;
            padding: 8px 12px;
            border-bottom: 1px solid #334155;
            cursor: pointer;
            white-space: nowrap;
        }
        th {
            background-color: #0f172a;
            position: sticky;
            top: 0;
            color: #94a3b8;
        }
        tr:hover {
            background-color: #334155;
        }
        tr.cursor-row {
            outline: 2px solid #38bdf8 !important;
            outline-offset: -2px;
            background-color: #334155;
        }
        tr.selected {
            background-color: #1d4ed8 !important;
            color: white;
        }
        tr.selected.cursor-row {
            outline: 2px solid #facc15 !important;
            outline-offset: -2px;
            background-color: #1d4ed8 !important;
        }
        .icon {
            margin-right: 8px;
            display: inline-block;
            width: 16px;
        }
        .dir-item { color: var(--folder-color); font-weight: bold; }
        .file-item { color: var(--file-color); }
        .archive-item { color: var(--archive-color); font-weight: bold; }
        .media-item { color: var(--media-color); }
        
        /* 작업 버튼 툴바 */
        .toolbar {
            background-color: #020617;
            padding: 10px 20px;
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        button {
            background-color: var(--accent-color);
            color: white;
            border: none;
            padding: 8px 14px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.2s;
        }
        button:hover { background-color: var(--accent-hover); }
        button.btn-gray { background-color: #475569; }
        button.btn-gray:hover { background-color: #334155; }
        button.btn-purple { background-color: #8b5cf6; }
        button.btn-purple:hover { background-color: #7c3aed; }
        button.btn-red { background-color: #ef4444; }
        button.btn-red:hover { background-color: #dc2626; }

        /* 모달 레이아웃 */
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background-color: rgba(0, 0, 0, 0.75);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .modal-content {
            background-color: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            width: 80%;
            height: 80%;
            display: flex;
            flex-direction: column;
            padding: 15px;
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .modal-title { font-weight: bold; font-size: 1.1rem; }
        .editor-textarea {
            flex: 1;
            background-color: #0f172a;
            color: #38bdf8;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 10px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.95rem;
            resize: none;
        }
        .media-container {
            flex: 1;
            background-color: #000;
            border-radius: 4px;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }
        .media-container img, .media-container video {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }
        .modal-footer {
            margin-top: 10px;
            display: flex;
            justify-content: flex-end;
            gap: 10px;
        }
    </style>
</head>
<body>
    <header>
        <div>
            <h1 style="margin:0; display:inline-block; vertical-align:middle;">WSL ↔ Windows Dual-Panel Commander</h1>
            <span style="font-size: 0.85rem; color: #94a3b8; margin-left: 15px; vertical-align:middle;">* [Tab] 패널 전환 | [↑/↓] 이동 | [Enter] 진입/열기 | [Insert/Space] 다중 선택 | [F3/F5/F7/F8] 기능키</span>
        </div>
        <div>WSL 기준 포트: 8080</div>
    </header>

    <div class="main-container">
        <!-- 좌측 패널 (WSL) -->
        <div class="panel active-panel" id="left-panel" onclick="setActivePanel('left')">
            <div class="panel-header">
                <button class="nav-btn" id="left-back-btn" onclick="historyBack('left')" title="뒤로 가기 (Alt+Left)" disabled>◀</button>
                <button class="nav-btn" id="left-forward-btn" onclick="historyForward('left')" title="앞으로 가기 (Alt+Right)" disabled>▶</button>
                <span class="panel-header-title" onclick="goToPath('left', userHomeDir)" title="클릭 시 사용자 홈 디렉토리로 바로 이동합니다">[좌측 - WSL 🏠]</span>
                <input type="text" class="path-input" id="left-path" value="/">
                <button class="sync-path-btn" onclick="syncPath('left')" title="우측 패널의 경로와 동일하게 설정합니다">우측과같이</button>
            </div>
            <div class="file-list-container">
                <table id="left-table">
                    <thead>
                        <tr>
                            <th style="width: 65%">이름</th>
                            <th style="width: 35%">크기</th>
                        </tr>
                    </thead>
                    <tbody id="left-tbody"></tbody>
                </table>
            </div>
        </div>

        <!-- 우측 패널 (Windows) -->
        <div class="panel" id="right-panel" onclick="setActivePanel('right')">
            <div class="panel-header">
                <button class="nav-btn" id="right-back-btn" onclick="historyBack('right')" title="뒤로 가기 (Alt+Left)" disabled>◀</button>
                <button class="nav-btn" id="right-forward-btn" onclick="historyForward('right')" title="앞으로 가기 (Alt+Right)" disabled>▶</button>
                <span class="panel-header-title" onclick="goToPath('right', winCDir)" title="클릭 시 Windows C드라이브로 바로 이동합니다">[우측 - Windows 💻]</span>
                <input type="text" class="path-input" id="right-path" value="/mnt/c">
                <button class="sync-path-btn" onclick="syncPath('right')" title="좌측 패널의 경로와 동일하게 설정합니다">좌측과같이</button>
            </div>
            <div class="file-list-container">
                <table id="right-table">
                    <thead>
                        <tr>
                            <th style="width: 65%">이름</th>
                            <th style="width: 35%">크기</th>
                        </tr>
                    </thead>
                    <tbody id="right-tbody"></tbody>
                </table>
            </div>
        </div>
    </div>

    <div class="toolbar">
        <button onclick="copyFile('left')">F5 복사 (좌 ➔ 우) ➔</button>
        <button class="btn-gray" onclick="viewFile()">F3 보기 / 편집</button>
        <button class="btn-purple" onclick="createArchive()">📦 압축하기 (Zip)</button>
        <button class="btn-purple" onclick="extractArchive()">📂 압축 풀기</button>
        <button class="btn-gray" onclick="createFolder()">F7 새 폴더</button>
        <button class="btn-red" onclick="deleteItem()">F8 삭제</button>
        <button onclick="copyFile('right')">⬅ F5 복사 (우 ➔ 좌)</button>
    </div>

    <!-- 텍스트 뷰어/편집기 모달 -->
    <div class="modal" id="editor-modal">
        <div class="modal-content">
            <div class="modal-header">
                <span class="modal-title" id="editor-filename">파일 편집기</span>
                <span style="font-size:0.8rem; color:#94a3b8;" id="editor-filepath"></span>
            </div>
            <textarea class="editor-textarea" id="editor-text"></textarea>
            <div class="modal-footer">
                <button onclick="saveAndCloseEditor()">저장 및 닫기</button>
                <button class="btn-gray" onclick="closeEditor()">취소</button>
            </div>
        </div>
    </div>

    <!-- 이미지 및 동영상 뷰어 모달 -->
    <div class="modal" id="media-modal">
        <div class="modal-content">
            <div class="modal-header">
                <span class="modal-title" id="media-title">미디어 플레이어</span>
                <button class="btn-gray" onclick="closeMediaModal()">✕ 닫기</button>
            </div>
            <div class="media-container" id="media-body"></div>
        </div>
    </div>

    <!-- 압축 파일 목록 모달 -->
    <div class="modal" id="archive-modal">
        <div class="modal-content">
            <div class="modal-header">
                <span class="modal-title" id="archive-title">압축 파일 내부 목록</span>
                <span style="font-size:0.8rem; color:#94a3b8;" id="archive-filepath"></span>
            </div>
            <div class="file-list-container" style="flex:1;">
                <table>
                    <thead>
                        <tr>
                            <th style="width: 70%">파일명</th>
                            <th style="width: 30%">크기</th>
                        </tr>
                    </thead>
                    <tbody id="archive-tbody"></tbody>
                </table>
            </div>
            <div class="modal-footer">
                <button class="btn-purple" onclick="extractArchiveFromModal()">현재 패널로 압축 풀기</button>
                <button class="btn-gray" onclick="closeArchiveModal()">닫기</button>
            </div>
        </div>
    </div>

    <script>
        let currentLeftPath = "/";
        let currentRightPath = "/mnt/c";
        let userHomeDir = "~";
        let winCDir = "/mnt/c";
        let selectedItems = { panel: null, items: [] };
        let currentArchiveFile = "";

        let activePanel = 'left'; // 'left' | 'right'
        let cursorIndex = { left: 0, right: 0 };
        let panelItems = { left: [], right: [] };

        const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'];
        const VIDEO_EXTS = ['.mp4', '.webm', '.ogg', '.mov', '.mkv'];
        const AUDIO_EXTS = ['.mp3', '.wav', '.flac', '.aac', '.m4a', '.wma'];
        const ARCHIVE_EXTS = ['.zip', '.tar', '.gz', '.tgz', '.bz2'];

        const panelHistory = {
            left: { stack: [], index: -1 },
            right: { stack: [], index: -1 }
        };

        function setActivePanel(panelId) {
            activePanel = panelId;
            document.getElementById('left-panel').classList.toggle('active-panel', panelId === 'left');
            document.getElementById('right-panel').classList.toggle('active-panel', panelId === 'right');
            updateCursorVisual(panelId);
        }

        function updateCursorVisual(panelId) {
            const tbody = document.getElementById(panelId + '-tbody');
            if (!tbody) return;
            const rows = tbody.querySelectorAll('tr');
            rows.forEach((r, idx) => {
                r.classList.toggle('cursor-row', idx === cursorIndex[panelId]);
            });
            if (rows[cursorIndex[panelId]]) {
                rows[cursorIndex[panelId]].scrollIntoView({ block: 'nearest' });
            }
        }

        function updateRowSelectionVisual(panelId) {
            const tbody = document.getElementById(panelId + '-tbody');
            if (!tbody) return;
            const rows = tbody.querySelectorAll('tr');
            const items = panelItems[panelId];

            rows.forEach((tr, idx) => {
                const item = items[idx];
                if (!item) return;
                const isSel = (selectedItems.panel === panelId) && selectedItems.items.some(i => i.name === item.name);
                tr.classList.toggle('selected', isSel);
            });
        }

        function moveCursor(dir) {
            const items = panelItems[activePanel];
            if (!items || items.length === 0) return;
            let newIdx = cursorIndex[activePanel] + dir;
            if (newIdx < 0) newIdx = 0;
            if (newIdx >= items.length) newIdx = items.length - 1;
            
            cursorIndex[activePanel] = newIdx;
            updateCursorVisual(activePanel);

            // 단일 선택 항목 자동 업데이트 (부모 이동 .. 제외)
            const item = items[newIdx];
            if (item && item.name !== "..") {
                selectedItems.panel = activePanel;
                selectedItems.items = [{ name: item.name, isDir: item.is_dir }];
                updateRowSelectionVisual(activePanel);
            }
        }

        function toggleSelectInsert() {
            const items = panelItems[activePanel];
            const idx = cursorIndex[activePanel];
            if (!items || idx >= items.length) return;
            const item = items[idx];
            if (item.name === "..") return;

            if (selectedItems.panel !== activePanel) {
                clearSelection();
                selectedItems.panel = activePanel;
            }

            const existingIdx = selectedItems.items.findIndex(i => i.name === item.name);
            if (existingIdx > -1) {
                selectedItems.items.splice(existingIdx, 1);
            } else {
                selectedItems.items.push({ name: item.name, isDir: item.is_dir });
            }

            updateRowSelectionVisual(activePanel);
            moveCursor(1); // 한 칸 아래로 커서 자동 이동
        }

        function handleEnterKey() {
            const items = panelItems[activePanel];
            const idx = cursorIndex[activePanel];
            if (!items || idx >= items.length) return;
            const item = items[idx];
            const currentPath = activePanel === 'left' ? currentLeftPath : currentRightPath;
            const filePath = (currentPath === "/" ? "" : currentPath) + "/" + item.name;

            if (item.is_dir) {
                let nextPath = item.name === ".." ? (osDirName(currentPath) || "/") : filePath;
                loadDir(activePanel, nextPath);
            } else {
                const fType = getFileType(item.name);
                if (fType === 'image' || fType === 'video' || fType === 'audio') {
                    openMediaViewer(filePath, fType);
                } else if (fType === 'archive') {
                    openArchiveViewer(filePath);
                } else if (fType === 'pdf') {
                    window.open('/api/view_pdf?path=' + encodeURIComponent(filePath), '_blank');
                } else {
                    openEditor(filePath);
                }
            }
        }

        function updateNavButtons(panelId) {
            const h = panelHistory[panelId];
            const backBtn = document.getElementById(panelId + '-back-btn');
            const fwdBtn = document.getElementById(panelId + '-forward-btn');
            if (backBtn) backBtn.disabled = (h.index <= 0);
            if (fwdBtn) fwdBtn.disabled = (h.index >= h.stack.length - 1);
        }

        function historyBack(panelId) {
            const pid = panelId || activePanel || 'left';
            const h = panelHistory[pid];
            if (h.index > 0) {
                h.index--;
                loadDir(pid, h.stack[h.index], true);
            }
        }

        function historyForward(panelId) {
            const pid = panelId || activePanel || 'left';
            const h = panelHistory[pid];
            if (h.index < h.stack.length - 1) {
                h.index++;
                loadDir(pid, h.stack[h.index], true);
            }
        }

        function goToPath(panelId, targetPath) {
            if (targetPath) {
                loadDir(panelId, targetPath);
            }
        }

        function syncPath(targetPanel) {
            if (targetPanel === 'left') {
                loadDir('left', currentRightPath);
            } else if (targetPanel === 'right') {
                loadDir('right', currentLeftPath);
            }
        }

        function getFileType(filename) {
            const lower = filename.toLowerCase();
            if (IMAGE_EXTS.some(ext => lower.endsWith(ext))) return 'image';
            if (VIDEO_EXTS.some(ext => lower.endsWith(ext))) return 'video';
            if (AUDIO_EXTS.some(ext => lower.endsWith(ext))) return 'audio';
            if (ARCHIVE_EXTS.some(ext => lower.endsWith(ext))) return 'archive';
            if (lower.endsWith('.pdf')) return 'pdf';
            return 'file';
        }

        async function loadDir(panelId, dirPath, isHistoryNav = false) {
            const tbody = document.getElementById(panelId + '-tbody');
            const pathInput = document.getElementById(panelId + '-path');
            
            try {
                const response = await fetch(`/api/list?path=${encodeURIComponent(dirPath)}`);
                if (!response.ok) throw new Error("로드 실패");
                
                const data = await response.json();
                const actualPath = data.current_path;
                
                if (panelId === 'left') currentLeftPath = actualPath;
                else currentRightPath = actualPath;
                
                pathInput.value = actualPath;

                // 히스토리 업데이트
                if (!isHistoryNav) {
                    const h = panelHistory[panelId];
                    if (h.index === -1 || h.stack[h.index] !== actualPath) {
                        h.stack = h.stack.slice(0, h.index + 1);
                        h.stack.push(actualPath);
                        h.index = h.stack.length - 1;
                    }
                }
                updateNavButtons(panelId);
                tbody.innerHTML = "";

                // 상위 이동 (..) 아이템 추가
                let finalItems = [];
                if (actualPath !== "/") {
                    finalItems.push({ name: "..", is_dir: true, size: "-", mtime: 0 });
                }
                finalItems = finalItems.concat(data.items);
                panelItems[panelId] = finalItems;
                cursorIndex[panelId] = 0; // 목록 로드 시 커서 맨 위로 초기화
                
                finalItems.forEach((item, idx) => {
                    const tr = document.createElement('tr');
                    const fType = item.is_dir ? 'dir' : getFileType(item.name);
                    
                    let icon = "📄";
                    let itemClass = "file-item";
                    if (item.is_dir) {
                        icon = "📁";
                        itemClass = "dir-item";
                    } else if (fType === 'image') {
                        icon = "🖼️";
                        itemClass = "media-item";
                    } else if (fType === 'video') {
                        icon = "🎬";
                        itemClass = "media-item";
                    } else if (fType === 'audio') {
                        icon = "🎵";
                        itemClass = "media-item";
                    } else if (fType === 'archive') {
                        icon = "📦";
                        itemClass = "archive-item";
                    } else if (fType === 'pdf') {
                        icon = "📕";
                    }

                    const nameTd = document.createElement('td');
                    nameTd.innerHTML = `<span class="icon">${icon}</span>${item.name}`;
                    nameTd.className = itemClass;
                    
                    const sizeTd = document.createElement('td');
                    sizeTd.textContent = item.is_dir ? "-" : formatBytes(item.size);
                    
                    tr.appendChild(nameTd);
                    tr.appendChild(sizeTd);

                    tr.onmouseenter = () => {
                        setActivePanel(panelId);
                        cursorIndex[panelId] = idx;
                        updateCursorVisual(panelId);
                    };

                    tr.onclick = (e) => {
                        setActivePanel(panelId);
                        cursorIndex[panelId] = idx;
                        
                        if (item.name !== "..") {
                            if (e.ctrlKey || e.metaKey) {
                                if (selectedItems.panel !== panelId) {
                                    clearSelection();
                                    selectedItems.panel = panelId;
                                }
                                const sIdx = selectedItems.items.findIndex(i => i.name === item.name);
                                if (sIdx > -1) {
                                    selectedItems.items.splice(sIdx, 1);
                                } else {
                                    selectedItems.items.push({ name: item.name, isDir: item.is_dir });
                                }
                            } else {
                                clearSelection();
                                selectedItems.panel = panelId;
                                selectedItems.items = [{ name: item.name, isDir: item.is_dir }];
                            }
                        }
                        updateRowSelectionVisual(panelId);
                        updateCursorVisual(panelId);
                    };
                    
                    tr.ondblclick = () => {
                        cursorIndex[panelId] = idx;
                        updateCursorVisual(panelId);
                        const filePath = (data.current_path === "/" ? "" : data.current_path) + "/" + item.name;
                        if (item.is_dir) {
                            let nextPath = item.name === ".." ? (osDirName(data.current_path) || "/") : filePath;
                            loadDir(panelId, nextPath);
                        } else if (fType === 'image' || fType === 'video' || fType === 'audio') {
                            openMediaViewer(filePath, fType);
                        } else if (fType === 'archive') {
                            openArchiveViewer(filePath);
                        } else if (fType === 'pdf') {
                            window.open('/api/view_pdf?path=' + encodeURIComponent(filePath), '_blank');
                        } else {
                            openEditor(filePath);
                        }
                    };

                    tbody.appendChild(tr);
                });

                updateCursorVisual(panelId);
                updateRowSelectionVisual(panelId);
            } catch (err) {
                tbody.innerHTML = `<tr><td colspan="2" style="color:#ef4444;">에러: ${err.message}</td></tr>`;
            }
        }

        function osDirName(path) {
            if (!path || path === "/") return "/";
            const parts = path.split('/').filter(Boolean);
            parts.pop();
            return "/" + parts.join('/');
        }

        function formatBytes(bytes) {
            if (bytes === 0 || bytes === "-") return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        function clearSelection() {
            document.querySelectorAll('tr').forEach(tr => tr.classList.remove('selected'));
            selectedItems = { panel: null, items: [] };
        }

        async function copyFile(fromPanel) {
            if (selectedItems.panel !== fromPanel || selectedItems.items.length === 0) {
                alert("복사할 파일이나 폴더를 선택하세요.");
                return;
            }
            
            const currentPath = fromPanel === 'left' ? currentLeftPath : currentRightPath;
            const dstDir = fromPanel === 'left' ? currentRightPath : currentLeftPath;
            const srcPaths = selectedItems.items.map(item => currentPath + "/" + item.name);
            const count = selectedItems.items.length;
            
            if (confirm(`선택한 ${count}개의 항목을 반대편 패널로 복사하시겠습니까?`)) {
                try {
                    const response = await fetch('/api/copy', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ src: srcPaths, dst_dir: dstDir })
                    });
                    if (!response.ok) {
                        const errorMsg = await response.text();
                        throw new Error(errorMsg || "복사 중 오류 발생");
                    }
                    
                    loadDir('left', currentLeftPath);
                    loadDir('right', currentRightPath);
                    alert("복사 완료!");
                } catch (err) {
                    alert("에러: " + err.message);
                }
            }
        }

        function viewFile() {
            if (selectedItems.items.length !== 1) {
                alert("하나의 파일만 선택해 주세요.");
                return;
            }
            
            const item = selectedItems.items[0];
            if (item.isDir) {
                alert("폴더는 볼 수 없습니다.");
                return;
            }

            const currentPath = selectedItems.panel === 'left' ? currentLeftPath : currentRightPath;
            const fullPath = currentPath + "/" + item.name;
            const fType = getFileType(item.name);

            if (fType === 'image' || fType === 'video' || fType === 'audio') {
                openMediaViewer(fullPath, fType);
            } else if (fType === 'archive') {
                openArchiveViewer(fullPath);
            } else if (fType === 'pdf') {
                window.open('/api/view_pdf?path=' + encodeURIComponent(fullPath), '_blank');
            } else {
                openEditor(fullPath);
            }
        }

        // 미디어 뷰어 (이미지, 동영상, 오디오)
        function openMediaViewer(fullPath, fType) {
            const body = document.getElementById('media-body');
            document.getElementById('media-title').textContent = "미디어 뷰어: " + fullPath.split('/').pop();
            body.innerHTML = "";

            const mediaUrl = `/api/view_media?path=${encodeURIComponent(fullPath)}`;
            if (fType === 'image') {
                const img = document.createElement('img');
                img.src = mediaUrl;
                body.appendChild(img);
            } else if (fType === 'video') {
                const video = document.createElement('video');
                video.src = mediaUrl;
                video.controls = true;
                video.autoplay = true;
                body.appendChild(video);
            } else if (fType === 'audio') {
                const audio = document.createElement('audio');
                audio.src = mediaUrl;
                audio.controls = true;
                audio.autoplay = true;
                audio.style.width = "80%";
                body.appendChild(audio);
            }
            document.getElementById('media-modal').style.display = 'flex';
        }

        function closeMediaModal() {
            const body = document.getElementById('media-body');
            body.innerHTML = ""; // 동영상 재생 정지
            document.getElementById('media-modal').style.display = 'none';
        }

        // 압축 파일 뷰어 및 해제
        async function openArchiveViewer(fullPath) {
            currentArchiveFile = fullPath;
            document.getElementById('archive-filepath').textContent = fullPath;
            document.getElementById('archive-title').textContent = "압축 파일 보기: " + fullPath.split('/').pop();
            const tbody = document.getElementById('archive-tbody');
            tbody.innerHTML = "";

            try {
                const res = await fetch(`/api/archive/list?path=${encodeURIComponent(fullPath)}`);
                if (!res.ok) throw new Error("압축 파일 목록 읽기 실패");
                const data = await res.json();
                
                data.items.forEach(item => {
                    const tr = document.createElement('tr');
                    const nameTd = document.createElement('td');
                    nameTd.textContent = (item.is_dir ? "📁 " : "📄 ") + item.name;
                    const sizeTd = document.createElement('td');
                    sizeTd.textContent = item.is_dir ? "-" : formatBytes(item.size);
                    tr.appendChild(nameTd);
                    tr.appendChild(sizeTd);
                    tbody.appendChild(tr);
                });

                document.getElementById('archive-modal').style.display = 'flex';
            } catch (err) {
                alert("에러: " + err.message);
            }
        }

        function closeArchiveModal() {
            document.getElementById('archive-modal').style.display = 'none';
        }

        async function extractArchiveFromModal() {
            if (!currentArchiveFile) return;
            const activePanel = selectedItems.panel || 'left';
            const dstDir = activePanel === 'left' ? currentLeftPath : currentRightPath;
            await doExtract(currentArchiveFile, dstDir);
            closeArchiveModal();
        }

        async function extractArchive() {
            if (!selectedItems.panel || selectedItems.items.length !== 1) {
                alert("해제할 압축 파일을 하나 선택해 주세요.");
                return;
            }
            const activePanel = selectedItems.panel;
            const item = selectedItems.items[0];
            const currentPath = activePanel === 'left' ? currentLeftPath : currentRightPath;
            const fullPath = currentPath + "/" + item.name;

            if (getFileType(item.name) !== 'archive') {
                alert("선택된 파일은 지원되는 압축 파일(.zip, .tar.gz 등)이 아닙니다.");
                return;
            }

            const dstDir = activePanel === 'left' ? currentRightPath : currentLeftPath;
            if (confirm(`압축 파일 '${item.name}'을(를) 반대편 폴더(${dstDir})로 해제하시겠습니까?`)) {
                await doExtract(fullPath, dstDir);
            }
        }

        async function doExtract(archivePath, dstDir) {
            try {
                const res = await fetch('/api/archive/extract', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ archive_path: archivePath, dst_dir: dstDir })
                });
                if (!res.ok) {
                    const msg = await res.text();
                    throw new Error(msg || "압축 해제 실패");
                }
                alert("압축 해제 완료!");
                loadDir('left', currentLeftPath);
                loadDir('right', currentRightPath);
            } catch (err) {
                alert("에러: " + err.message);
            }
        }

        // 압축하기 (Zip 생성)
        async function createArchive() {
            if (!selectedItems.panel || selectedItems.items.length === 0) {
                alert("압축할 파일이나 폴더를 선택하세요.");
                return;
            }

            const activePanel = selectedItems.panel;
            const currentPath = activePanel === 'left' ? currentLeftPath : currentRightPath;
            const srcPaths = selectedItems.items.map(item => currentPath + "/" + item.name);
            
            const zipName = prompt("생성할 압축 파일명을 입력하세요 (예: archive.zip):", "archive.zip");
            if (!zipName) return;

            const format = zipName.toLowerCase().endsWith('.tar.gz') ? 'tar.gz' : 'zip';
            const dstPath = currentPath + "/" + (zipName.endsWith('.zip') || zipName.endsWith('.tar.gz') ? zipName : zipName + ".zip");

            try {
                const res = await fetch('/api/archive/create', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ src: srcPaths, dst_path: dstPath, format: format })
                });
                if (!res.ok) {
                    const msg = await res.text();
                    throw new Error(msg || "압축 생성 실패");
                }
                alert("압축 생성 완료!");
                loadDir(activePanel, currentPath);
            } catch (err) {
                alert("에러: " + err.message);
            }
        }

        let editingFilePath = "";

        async function openEditor(filePath) {
            editingFilePath = filePath;
            document.getElementById('editor-filepath').textContent = filePath;
            document.getElementById('editor-filename').textContent = filePath.split('/').pop();
            
            try {
                const res = await fetch(`/api/read?path=${encodeURIComponent(filePath)}`);
                if (!res.ok) throw new Error("파일 읽기 실패");
                const content = await res.text();
                document.getElementById('editor-text').value = content;
                document.getElementById('editor-modal').style.display = 'flex';
            } catch (err) {
                alert("파일 열기 실패: " + err.message);
            }
        }

        async function saveAndCloseEditor() {
            const content = document.getElementById('editor-text').value;
            try {
                const res = await fetch('/api/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ path: editingFilePath, content: content })
                });
                if (!res.ok) throw new Error("저장 실패");
                alert("저장 성공!");
                closeEditor();
                loadDir('left', currentLeftPath);
                loadDir('right', currentRightPath);
            } catch (err) {
                alert("저장 실패: " + err.message);
            }
        }

        function closeEditor() {
            document.getElementById('editor-modal').style.display = 'none';
        }

        function refreshAll() {
            loadDir('left', currentLeftPath);
            loadDir('right', currentRightPath);
        }

        async function createFolder() {
            const activePanel = selectedItems.panel || 'left';
            const currentPath = activePanel === 'left' ? currentLeftPath : currentRightPath;
            
            const folderName = prompt("새로 생성할 폴더명을 입력하세요:");
            if (!folderName) return;
            
            try {
                const response = await fetch('/api/mkdir', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ parent: currentPath, name: folderName })
                });
                if (!response.ok) {
                    const errorMsg = await response.text();
                    throw new Error(errorMsg || "폴더 생성 중 오류 발생");
                }
                loadDir(activePanel, currentPath);
            } catch (err) {
                alert("에러: " + err.message);
            }
        }

        async function deleteItem() {
            if (!selectedItems.panel || selectedItems.items.length === 0) {
                alert("삭제할 폴더나 파일을 선택해 주세요.");
                return;
            }
            
            const activePanel = selectedItems.panel;
            const currentPath = activePanel === 'left' ? currentLeftPath : currentRightPath;
            const targetPaths = selectedItems.items.map(item => currentPath + "/" + item.name);
            const count = selectedItems.items.length;
            
            const confirmMsg = `선택한 ${count}개의 항목을 정말 삭제하시겠습니까?\n(주의: 폴더인 경우 내부 모든 파일이 삭제됩니다!)`;
            if (confirm(confirmMsg)) {
                try {
                    const response = await fetch('/api/delete', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ path: targetPaths })
                    });
                    if (!response.ok) {
                        const errorMsg = await response.text();
                        throw new Error(errorMsg || "삭제 중 오류 발생");
                    }
                    clearSelection();
                    loadDir(activePanel, currentPath);
                    alert("삭제 완료!");
                } catch (err) {
                    alert("에러: " + err.message);
                }
            }
        }

        window.addEventListener('keydown', (e) => {
            if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') {
                return;
            }

            const modalOpen = Array.from(document.querySelectorAll('.modal')).find(m => getComputedStyle(m).display === 'flex');
            if (modalOpen) {
                if (e.key === 'Escape') {
                    closeEditor();
                    closeMediaModal();
                    closeArchiveModal();
                }
                return;
            }

            // 1. Tab: 좌/우 패널 포커스 전환
            if (e.key === 'Tab') {
                e.preventDefault();
                setActivePanel(activePanel === 'left' ? 'right' : 'left');
            }
            // 2. Alt + Left / Right: 히스토리 탐색 (뒤로/앞으로)
            else if (e.altKey && e.key === 'ArrowLeft') {
                e.preventDefault();
                historyBack(activePanel);
            }
            else if (e.altKey && e.key === 'ArrowRight') {
                e.preventDefault();
                historyForward(activePanel);
            }
            // 3. ArrowUp / ArrowDown: 목록 커서 위/아래 이동
            else if (e.key === 'ArrowUp') {
                e.preventDefault();
                moveCursor(-1);
            }
            else if (e.key === 'ArrowDown') {
                e.preventDefault();
                moveCursor(1);
            }
            // 4. PageUp / PageDown: 10개 단위 빠르게 이동
            else if (e.key === 'PageUp') {
                e.preventDefault();
                moveCursor(-10);
            }
            else if (e.key === 'PageDown') {
                e.preventDefault();
                moveCursor(10);
            }
            // 5. Home / End: 맨 위 / 맨 아래로 커서 이동
            else if (e.key === 'Home') {
                e.preventDefault();
                cursorIndex[activePanel] = 0;
                updateCursorVisual(activePanel);
            }
            else if (e.key === 'End') {
                e.preventDefault();
                const items = panelItems[activePanel];
                cursorIndex[activePanel] = Math.max(0, items.length - 1);
                updateCursorVisual(activePanel);
            }
            // 6. Insert 또는 Space: 다중 선택 토글 후 한 칸 아래로 이동
            else if (e.key === 'Insert' || e.code === 'Space') {
                e.preventDefault();
                toggleSelectInsert();
            }
            // 7. Enter: 폴더 진입 또는 파일 열기
            else if (e.key === 'Enter') {
                e.preventDefault();
                handleEnterKey();
            }
            // 8. Backspace: 상위(부모) 디렉토리로 이동
            else if (e.key === 'Backspace') {
                e.preventDefault();
                const currentPath = activePanel === 'left' ? currentLeftPath : currentRightPath;
                if (currentPath !== "/") {
                    loadDir(activePanel, osDirName(currentPath) || "/");
                }
            }
            // 9. F3 / F5 / F7 / F8 기능키
            else if (e.key === 'F3') {
                e.preventDefault();
                viewFile();
            } else if (e.key === 'F5') {
                e.preventDefault();
                copyFile(activePanel);
            } else if (e.key === 'F7') {
                e.preventDefault();
                createFolder();
            } else if (e.key === 'F8') {
                e.preventDefault();
                deleteItem();
            }
        });

        document.getElementById('left-path').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadDir('left', e.target.value);
        });
        document.getElementById('right-path').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadDir('right', e.target.value);
        });

        window.onload = async () => {
            try {
                const res = await fetch('/api/init');
                if (res.ok) {
                    const data = await res.json();
                    if (data.home_dir) {
                        userHomeDir = data.home_dir;
                        currentLeftPath = data.home_dir;
                    }
                    if (data.win_c) {
                        winCDir = data.win_c;
                        currentRightPath = data.win_c;
                    }
                }
            } catch (e) {}
            if (!currentLeftPath) currentLeftPath = userHomeDir;
            loadDir('left', currentLeftPath);
            loadDir('right', currentRightPath);
        };
    </script>
</body>
</html>
"""

def open_browser():
    # 서버 소켓이 준비될 때까지 1초 대기
    time.sleep(1)
    try:
        # WSL 환경에서 Windows의 기본 웹 브라우저를 호출하여 자동 접속
        subprocess.run(["cmd.exe", "/c", "start", f"http://localhost:{PORT}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == '__main__':
    handler = CommanderHandler
    # 백그라운드에서 브라우저 자동 실행 스레드 시작
    threading.Thread(target=open_browser, daemon=True).start()
    
    with ReusableTCPServer(("", PORT), handler) as httpd:
        print(f"WSL Commander Server가 포트 {PORT}에서 가동 중입니다...")
        print(f"서버가 구동되면 Windows 기본 웹 브라우저가 자동으로 열립니다.")
        httpd.serve_forever()
