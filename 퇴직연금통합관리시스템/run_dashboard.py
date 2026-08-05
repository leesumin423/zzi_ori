import os
import sys


def main():
    # Change working directory to the script's directory to serve files correctly
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    sys.path.insert(0, script_dir)

    import pension_server

    PORT = 8000

    print(f"\n========================================================")
    print(f"  퇴직연금 통합 대시보드 서버 구동 중...")
    print(f"  접속 주소: http://localhost:{PORT}")
    print(f"  데이터 관리(기준일 등록/삭제): http://localhost:{PORT}/admin")
    print(f"  종료하려면 Ctrl+C 를 누르세요.")
    print(f"========================================================\n")

    try:
        pension_server.app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n대시보드 서버를 종료합니다...")


if __name__ == "__main__":
    main()
