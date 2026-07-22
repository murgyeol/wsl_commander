import os
import shutil
import json
import http.server
import socketserver
import urllib.parse
import subprocess
import threading
import time

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

class CommanderHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # 터미널 로그 간소화

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path_query = urllib.parse.parse_qs(parsed_url.query)
        
        # API: 디렉토리 목록 조회
        if parsed_url.path == "/api/list":
            dir_path = path_query.get('path', [None])[0]
            if not dir_path or not os.path.exists(dir_path):
                dir_path = "/"
            
            try:
                items = []
                # 상위 폴더 바로가기 추가
                parent = os.path.dirname(os.path.normpath(dir_path))
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
                self.wfile.write(json.dumps({"current_path": os.path.abspath(dir_path), "items": items}).encode('utf-8'))
            except Exception as e:
                self.send_error(500, str(e))
            return
            
        # API: 텍스트 파일 읽기
        elif parsed_url.path == "/api/read":
            file_path = path_query.get('path', [None])[0]
            if file_path and os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(content.encode('utf-8'))
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(400, "Invalid file path")
            return

        # API: PDF 파일 스트리밍
        elif parsed_url.path == "/api/view_pdf":
            file_path = path_query.get('path', [None])[0]
            if file_path and os.path.isfile(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    
                    # PDF 내장 자동 인쇄 스크립트 무력화 (xref 테이블 정렬 유지를 위해 동일한 글자 수로 대체)
                    content = content.replace(b'/OpenAction', b'/OpenActioX')
                    content = content.replace(b'/JavaScript', b'/JavaScripX')
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/pdf')
                    self.send_header('Content-Disposition', 'inline')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
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
            dst_dir = post_data.get('dst_dir')
            if not src_list or not dst_dir:
                self.send_error(400, "Missing src or dst_dir")
                return

            if isinstance(src_list, str):
                src_list = [src_list]

            try:
                for src in src_list:
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

        # API: 텍스트 파일 저장
        elif parsed_url.path == "/api/save":
            file_path = post_data.get('path')
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
            parent = post_data.get('parent')
            name = post_data.get('name')
            if not parent or not name:
                self.send_error(400, "Missing parent or name")
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
                for target in target_list:
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
            border: 1px solid var(--border-color);
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .panel-header {
            background-color: #0f172a;
            padding: 8px 12px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 10px;
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
        tr.selected {
            background-color: #1d4ed8 !important;
            color: white;
        }
        .icon {
            margin-right: 8px;
            display: inline-block;
            width: 16px;
        }
        .dir-item { color: var(--folder-color); font-weight: bold; }
        .file-item { color: var(--file-color); }
        
        /* 작업 버튼 툴바 */
        .toolbar {
            background-color: #020617;
            padding: 10px 20px;
            border-top: 1px solid var(--border-color);
            display: flex;
            gap: 10px;
        }
        button {
            background-color: var(--accent-color);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.2s;
        }
        button:hover { background-color: var(--accent-hover); }
        button.btn-gray { background-color: #475569; }
        button.btn-gray:hover { background-color: #334155; }
        button.btn-red { background-color: #ef4444; }
        button.btn-red:hover { background-color: #dc2626; }

        /* 텍스트 뷰어 모달 */
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background-color: rgba(0, 0, 0, 0.7);
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
            <span style="font-size: 0.85rem; color: #94a3b8; margin-left: 15px; vertical-align:middle;">* Ctrl+클릭으로 여러 항목을 다중 선택할 수 있습니다.</span>
        </div>
        <div>WSL 기준 포트: 8080</div>
    </header>

    <div class="main-container">
        <!-- 좌측 패널 (WSL) -->
        <div class="panel" id="left-panel">
            <div class="panel-header">
                <span>[좌측 - WSL]</span>
                <input type="text" class="path-input" id="left-path" value="/">
            </div>
            <div class="file-list-container">
                <table id="left-table">
                    <thead>
                        <tr>
                            <th style="width: 60%">이름</th>
                            <th style="width: 20%">크기</th>
                        </tr>
                    </thead>
                    <tbody id="left-tbody"></tbody>
                </table>
            </div>
        </div>

        <!-- 우측 패널 (Windows) -->
        <div class="panel" id="right-panel">
            <div class="panel-header">
                <span>[우측 - Windows]</span>
                <input type="text" class="path-input" id="right-path" value="/mnt/c">
            </div>
            <div class="file-list-container">
                <table id="right-table">
                    <thead>
                        <tr>
                            <th style="width: 60%">이름</th>
                            <th style="width: 20%">크기</th>
                        </tr>
                    </thead>
                    <tbody id="right-tbody"></tbody>
                </table>
            </div>
        </div>
    </div>

    <div class="toolbar">
        <button onclick="copyFile('left')">F5 복사 (좌 → 우) ➔</button>
        <button onclick="copyFile('right')">F5 복사 (우 → 좌) ⮨</button>
        <button class="btn-gray" onclick="viewFile()">F3 보기 / 편집</button>
        <button class="btn-gray" onclick="createFolder()">F7 새 폴더</button>
        <button class="btn-red" onclick="deleteItem()">F8 삭제</button>
        <button class="btn-gray" onclick="refreshAll()">새로고침</button>
    </div>

    <!-- 텍스트 뷰어 모달 -->
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

    <script>
        let currentLeftPath = "/";
        let currentRightPath = "/mnt/c";
        let selectedItems = { panel: null, items: [] };

        async function loadDir(panelId, dirPath) {
            const tbody = document.getElementById(panelId + '-tbody');
            const pathInput = document.getElementById(panelId + '-path');
            
            try {
                const response = await fetch(`/api/list?path=${encodeURIComponent(dirPath)}`);
                if (!response.ok) throw new Error("로드 실패");
                
                const data = await response.json();
                
                // 전역 경로 업데이트
                if (panelId === 'left') currentLeftPath = data.current_path;
                else currentRightPath = data.current_path;
                
                pathInput.value = data.current_path;
                tbody.innerHTML = "";
                
                data.items.forEach(item => {
                    const tr = document.createElement('tr');
                    
                    const nameTd = document.createElement('td');
                    const icon = item.is_dir ? "📁" : "📄";
                    nameTd.innerHTML = `<span class="icon">${icon}</span>${item.name}`;
                    nameTd.className = item.is_dir ? 'dir-item' : 'file-item';
                    
                    const sizeTd = document.createElement('td');
                    sizeTd.textContent = item.is_dir ? "-" : formatBytes(item.size);
                    
                    tr.appendChild(nameTd);
                    tr.appendChild(sizeTd);
                    
                    // 더블 클릭 시 폴더 이동 또는 파일 열기
                    tr.ondblclick = () => {
                        const filePath = (data.current_path === "/" ? "" : data.current_path) + "/" + item.name;
                        if (item.is_dir) {
                            let nextPath;
                            if (item.name === "..") {
                                const parts = data.current_path.split('/');
                                parts.pop();
                                nextPath = parts.join('/') || "/";
                            } else {
                                nextPath = filePath;
                            }
                            loadDir(panelId, nextPath);
                        } else if (item.name.toLowerCase().endsWith('.pdf')) {
                            // PDF 파일은 새 탭에서 브라우저 네이티브 뷰어로 열기
                            window.open('/api/view_pdf?path=' + encodeURIComponent(filePath), '_blank');
                        } else {
                            openEditor(filePath);
                        }
                    };
                    
                    // 단일/다중 클릭 시 행 선택
                    tr.onclick = (e) => {
                        if (item.name === "..") return; // 부모 바로가기는 다중 선택 불가
                        
                        if (selectedItems.panel !== panelId) {
                            clearSelection();
                            selectedItems.panel = panelId;
                        }

                        const idx = selectedItems.items.findIndex(i => i.name === item.name);
                        const isSelected = idx > -1;

                        if (e.ctrlKey || e.metaKey) {
                            // Ctrl+Click: 토글 선택
                            if (isSelected) {
                                selectedItems.items.splice(idx, 1);
                                tr.classList.remove('selected');
                            } else {
                                selectedItems.items.push({ name: item.name, isDir: item.is_dir });
                                tr.classList.add('selected');
                            }
                        } else {
                            // 일반 Click: 단일 독점 선택
                            document.querySelectorAll(`#${panelId}-tbody tr`).forEach(row => row.classList.remove('selected'));
                            selectedItems.items = [{ name: item.name, isDir: item.is_dir }];
                            tr.classList.add('selected');
                        }
                    };
                    
                    tbody.appendChild(tr);
                });
            } catch (err) {
                alert("폴더 이동 실패: " + err.message);
            }
        }

        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
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
                    
                    // 양쪽 다시 로딩
                    loadDir('left', currentLeftPath);
                    loadDir('right', currentRightPath);
                    alert("복사 완료!");
                } catch (err) {
                    alert("에러: " + err.message);
                }
            }
        }

        // F3 보기/편집
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

            if (item.name.toLowerCase().endsWith('.pdf')) {
                // PDF 파일은 새 탭에서 열기
                window.open('/api/view_pdf?path=' + encodeURIComponent(fullPath), '_blank');
            } else {
                openEditor(fullPath);
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
                // 패널 리로드
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

        // 새 폴더 생성
        async function createFolder() {
            // 선택된 항목이 있는 패널을 활성 패널로 간주, 없으면 왼쪽 패널을 기본값으로 사용
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

        // 파일/폴더 삭제
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

        // 키보드 바인딩 (F3: 보기, F5: 복사, F7: 새 폴더, F8: 삭제)
        window.addEventListener('keydown', (e) => {
            if (e.key === 'F3') {
                e.preventDefault();
                viewFile();
            } else if (e.key === 'F5') {
                e.preventDefault();
                if (selectedItems.panel) copyFile(selectedItems.panel);
            } else if (e.key === 'F7') {
                e.preventDefault();
                createFolder();
            } else if (e.key === 'F8') {
                e.preventDefault();
                deleteItem();
            }
        });

        // 엔터키 경로 이동 이벤트 등록
        document.getElementById('left-path').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadDir('left', e.target.value);
        });
        document.getElementById('right-path').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadDir('right', e.target.value);
        });

        // 초기화
        window.onload = () => {
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
