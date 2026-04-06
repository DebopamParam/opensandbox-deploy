import asyncio
import base64
import os
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import WriteEntry

IMAGE = os.environ.get("SANDBOX_IMAGE", "opensandbox-base:latest")
PORT = os.environ.get("SANDBOX_PORT", "8080")
API_KEY = os.environ.get("SANDBOX_API_KEY", "change-me-to-something-secret")

CONFIG = ConnectionConfig(
    domain=f"localhost:{PORT}",
    api_key=API_KEY,
    use_server_proxy=True,
)

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: sans-serif; padding: 2em; background: #f9f9f9; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        .box { border: 1px solid #bdc3c7; padding: 1.5em; border-radius: 8px; background: #ffffff; }
        .footer { margin-top: 30px; font-size: 0.8em; color: #7f8c8d; }
    </style>
</head>
<body>
    <h1>OpenSandbox + WeasyPrint</h1>
    <div class="box">
        <p>This PDF was rendered securely inside an isolated container.</p>
        <ul>
            <li><b>System:</b> Debian (Python 3.13-slim)</li>
            <li><b>Renderer:</b> WeasyPrint</li>
            <li><b>Fonts:</b> Noto Core</li>
        </ul>
    </div>
    <div class="footer">Generated via Python SDK</div>
</body>
</html>
"""

async def main():
    print(f"Launching sandbox with image: {IMAGE}...")
    sandbox = await Sandbox.create(
        IMAGE,
        connection_config=CONFIG,
        entrypoint=["sleep", "infinity"],
    )

    try:
        # 1. Write the HTML file to the sandbox
        print("1. Writing input.html to sandbox workspace...")
        await sandbox.files.write_files([
            WriteEntry(path="/workspace/input.html", data=HTML_CONTENT)
        ])

        # 2. Run Weasyprint
        print("2. Executing WeasyPrint engine...")
        res = await sandbox.commands.run(
            "weasyprint /workspace/input.html /workspace/output.pdf",
        )
        
        if res.exit_code != 0:
            err = res.logs.stderr[0].text if res.logs.stderr else 'Unknown error'
            print(f"❌ Error running WeasyPrint: {err}")
            return

        # 3. Read the binary file out via Base64
        # (This avoids any text-encoding issues with standard file-read APIs)
        print("3. Extracting PDF binary as base64...")
        b64_res = await sandbox.commands.run("base64 -w 0 /workspace/output.pdf")
        
        if not b64_res.logs.stdout:
            print("❌ Failed to read base64 output.")
            return
            
        b64_data = b64_res.logs.stdout[0].text
        pdf_bytes = base64.b64decode(b64_data)

        # 4. Save locally
        out_path = "rendered_output.pdf"
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)

        print(f"✅ Success! PDF saved locally to: {os.path.abspath(out_path)}")

    finally:
        print("Cleaning up sandbox...")
        await sandbox.kill()

if __name__ == "__main__":
    asyncio.run(main())