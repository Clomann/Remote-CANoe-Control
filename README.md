# Remote CANoe Control

A small FastAPI service that exposes basic CANoe controls through a REST API.

The service runs on the Windows computer where CANoe is installed and controls CANoe through its local COM interface. Other computers or CI runners on the same network can send JSON requests to it.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\activate
pip install fastapi uvicorn pywin32
```

Set the required environment variables:

```powershell
$env:CANOE_API_KEY = "your-secret-key"
$env:CANOE_CONFIG_ROOT = "C:\CANoeConfigs"
```

Start the API:

```powershell
python -m uvicorn app:api --host 0.0.0.0 --port 8000 --workers 1
```

## Usage

Replace `192.168.1.50` with the IP address of the CANoe computer.

Check the CANoe status:

```bash
curl -H "X-API-Key: your-secret-key" \
  http://192.168.1.50:8000/canoe/status
```

Start a measurement:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{"wait_seconds":30}' \
  http://192.168.1.50:8000/canoe/measurement/start
```

Stop a measurement:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{"wait_seconds":30}' \
  http://192.168.1.50:8000/canoe/measurement/stop
```

Interactive API documentation is available at:

```text
http://192.168.1.50:8000/docs
```

## Notes

* CANoe and the API should run under the same logged-in Windows user.
* Run only one API worker.
* Allow TCP port `8000` through Windows Firewall for the local network.
* Do not expose the API directly to the internet.

