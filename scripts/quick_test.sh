#!/bin/bash
# テスト実行スクリプト（Cursor AI対応）
#
# 使用方法:
#   ./scripts/quick_test.sh run [target]  # テスト実行
#   ./scripts/quick_test.sh check         # 完了確認
#   ./scripts/quick_test.sh get           # 結果取得
#   ./scripts/quick_test.sh kill          # 強制終了

set -e

ACTION="${1:-run}"
TARGET="${2:-tests/}"
RESULT_FILE="/app/test_result.txt"

case "$ACTION" in
    run)
        echo "=== Cleanup ==="
        podman exec lancet pkill -9 -f "pytest" 2>/dev/null || true
        sleep 1
        
        echo "=== Running: $TARGET ==="
        # podman exec -d でデタッチ実行（コンテナ内で独立プロセス）
        podman exec lancet rm -f "$RESULT_FILE"
        podman exec -d lancet sh -c "PYTHONUNBUFFERED=1 pytest $TARGET -m 'not e2e' --tb=short -q > $RESULT_FILE 2>&1"
        echo "Started. Run: ./scripts/quick_test.sh check"
        ;;
    
    check)
        # ファイル更新時刻で判定（5秒以上更新がなければ完了）
        MTIME=$(podman exec lancet stat -c %Y "$RESULT_FILE" 2>/dev/null || echo 0)
        NOW=$(podman exec lancet date +%s)
        AGE=$((NOW - MTIME))
        LAST=$(podman exec lancet tail -1 "$RESULT_FILE" 2>/dev/null || echo "waiting...")
        
        if [ "$AGE" -gt 5 ]; then
            echo "DONE (${AGE}s ago)"
            podman exec lancet tail -5 "$RESULT_FILE" 2>/dev/null
        else
            echo "RUNNING | $LAST"
        fi
        ;;
    
    get)
        echo "=== Result ==="
        podman exec lancet tail -20 "$RESULT_FILE" 2>/dev/null || echo "No result"
        ;;
    
    kill)
        echo "Killing..."
        podman exec lancet pkill -9 -f "pytest" 2>/dev/null || true
        echo "Done"
        ;;
    
    *)
        echo "Usage: $0 {run|check|get|kill} [target]"
        ;;
esac
