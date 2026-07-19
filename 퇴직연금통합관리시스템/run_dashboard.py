import subprocess
import os
import sys
import webbrowser
import http.server
import socketserver
import threading
import time

def main():
    # Change working directory to the script's directory to serve files correctly
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # 1. Update data by running parse_data.py
    print("Updating dashboard data from Excel files...")
    result = subprocess.run([sys.executable, "parse_data.py"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("Error updating data:")
        print(result.stderr)
        sys.exit(1)

    # 2. Start a local HTTP server
    PORT = 8000
    Handler = http.server.SimpleHTTPRequestHandler
    
    # Enable address reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        pass

    try:
        server = ThreadedTCPServer(("", PORT), Handler)
    except Exception as e:
        print(f"Error starting server on port {PORT}: {e}")
        print("The port might be in use. Trying to open browser anyway...")
        webbrowser.open(f"http://localhost:{PORT}")
        sys.exit(1)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    print(f"\n========================================================")
    # Highlight to the user
    print(f"  퇴직연금 통합 대시보드 서버 구동 중...")
    print(f"  접속 주소: http://localhost:{PORT}")
    print(f"  종료하려면 Ctrl+C 를 누르세요.")
    print(f"========================================================\n")

    # 3. Open browser automatically
    webbrowser.open(f"http://localhost:{PORT}")

    # Keep the main thread alive to serve requests
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n대시보드 서버를 종료합니다...")
        server.shutdown()
        server.server_close()
        print("서버가 안전하게 중지되었습니다.")

if __name__ == "__main__":
    main()
