import subprocess
import time
import sys

print("[Tunnel Daemon] Starting persistent localtunnel...")

while True:
    try:
        cmd = "npx -y localtunnel --port 8000 --subdomain xeon-letschat"
        print(f"[Tunnel Daemon] Executing: {cmd}")
        process = subprocess.Popen(cmd, shell=True, stdout=sys.stdout, stderr=sys.stderr)
        process.wait()
        print(f"[Tunnel Daemon] localtunnel exited with code {process.returncode}. Restarting in 2 seconds...")
        time.sleep(2)
    except KeyboardInterrupt:
        print("[Tunnel Daemon] Stopped.")
        break
    except Exception as e:
        print(f"[Tunnel Daemon] Error: {e}. Retrying in 3 seconds...")
        time.sleep(3)
