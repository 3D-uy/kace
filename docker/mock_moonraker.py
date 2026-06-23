#!/usr/bin/env python3
"""
mock_moonraker.py

A lightweight mock Moonraker REST API server for testing KACE deployment features.
Runs on port 7125 and implements server info, file upload, and restart endpoints.
Uses only the Python standard library.
"""

import os
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 7125
CONFIG_DIR = os.path.expanduser("~/printer_data/config")

class MockMoonrakerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to format logging nicely
        print(f"\033[90m[Mock Moonraker] {format % args}\033[0m")

    def do_GET(self):
        # Handle /server/info
        if self.path == "/server/info":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "result": {
                    "moonraker_version": "v0.8.0-mock",
                    "api_version": [1, 3, 0],
                    "api_version_string": "1.3.0",
                    "cpu_info": {
                        "model": "Simulated Raspberry Pi (Docker)"
                    }
                }
            }
            self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        # Parse query params out of path
        path_parts = self.path.split("?")
        base_path = path_parts[0]
        query_string = path_parts[1] if len(path_parts) > 1 else ""

        # Handle /printer/firmware_restart
        if base_path == "/printer/firmware_restart":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"result": "ok", "message": "FIRMWARE_RESTART issued successfully"}
            print("\033[92m[Mock Moonraker] Received FIRMWARE_RESTART command!\033[0m")
            self.wfile.write(json.dumps(response).encode("utf-8"))

        # Handle /machine/services/restart
        elif base_path == "/machine/services/restart":
            # Match service=klipper
            if "service=klipper" in query_string:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"result": "ok", "message": "Klipper service restart issued successfully"}
                print("\033[92m[Mock Moonraker] Received Klipper service restart command!\033[0m")
                self.wfile.write(json.dumps(response).encode("utf-8"))
            else:
                self.send_error(400, "Bad Request: missing or invalid service name")

        # Handle /server/files/upload
        elif base_path == "/server/files/upload":
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                self.send_error(400, "Bad Request: Content-Type must be multipart/form-data")
                return

            try:
                # Extract boundary
                boundary_match = re.search(r"boundary=([^;]+)", content_type)
                if not boundary_match:
                    self.send_error(400, "Bad Request: boundary not found")
                    return
                boundary = boundary_match.group(1).encode()

                # Read body
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)

                # Parse the file from the multipart body
                # Locate file bytes by splitting on boundary
                parts = body.split(b"--" + boundary)
                file_data = None
                filename = "printer.cfg"

                for part in parts:
                    if b"filename=" in part:
                        # Extract the content from headers and data section
                        # A part looks like:
                        # \r\nContent-Disposition: ...; name="file"; filename="printer.cfg"\r\nContent-Type: ...\r\n\r\n<data>\r\n
                        header_data_split = part.split(b"\r\n\r\n", 1)
                        if len(header_data_split) == 2:
                            data = header_data_split[1]
                            # Strip trailing CRLF from file data
                            if data.endswith(b"\r\n"):
                                data = data[:-2]
                            file_data = data
                            break

                if file_data is None:
                    self.send_error(400, "Bad Request: file part not found in form data")
                    return

                # Write to simulated config folder
                os.makedirs(CONFIG_DIR, exist_ok=True)
                dest_file = os.path.join(CONFIG_DIR, filename)
                with open(dest_file, "wb") as f:
                    f.write(file_data)

                print(f"\033[92m[Mock Moonraker] Uploaded printer.cfg successfully to {dest_file} ({len(file_data)} bytes)!\033[0m")

                # Send success response
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
                    "result": {
                        "item": {
                            "path": "printer.cfg",
                            "size": len(file_data)
                        }
                    }
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))

            except Exception as e:
                print(f"\033[91m[Mock Moonraker] Error during file upload: {e}\033[0m")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": str(e)}}).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, MockMoonrakerHandler)
    print(f"\033[94m[Mock Moonraker] Server started on port {PORT}\033[0m")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print("\033[94m[Mock Moonraker] Server stopped.\033[0m")

if __name__ == "__main__":
    run_server()
