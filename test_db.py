import os
import socket
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("DATABASE_URL")
print(f"1. DATABASE_URL loaded: '{url}'")

if url:
    try:
        host = url.split("@")[1].split(":")[0]
        print(f"2. Hostname parsed: '{host}'")
        try:
            ip = socket.gethostbyname(host)
            print(f"3. DNS resolved OK: {host} -> {ip}")
        except socket.gaierror as e:
            print(f"3. DNS FAILED: {e}")
    except Exception as e:
        print(f"2. Could not parse hostname: {e}")
else:
    print("2. DATABASE_URL is None — .env not found!")

print("\nDone.")
