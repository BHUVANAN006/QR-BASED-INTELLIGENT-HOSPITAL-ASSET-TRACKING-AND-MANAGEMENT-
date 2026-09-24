
# MedAsset Track — Python Flask Hospital Asset Tracking

## Run on Windows

1. Extract the ZIP.
2. Double-click `START_MEDTRACK.bat`.
3. Wait for package installation.
4. Open `http://127.0.0.1:5000`.
5. On first launch, create your own Office and Management user IDs and passwords.
6. Sign in through the Office portal and create individual Nurse/Staff accounts.

No demo usernames or passwords are included.

## Open it on another mobile or laptop on the same Wi-Fi

1. Start the project on the main computer.
2. Open Command Prompt and run `ipconfig`.
3. Find the computer's IPv4 address, for example `192.168.1.10`.
4. On another device connected to the same Wi-Fi, open:
   `http://192.168.1.10:5000`
5. Allow Python through Windows Firewall when asked.

## Create a public link

Deploy the project to a Python hosting service such as Render using the included `render.yaml`.
The SQLite database is suitable for prototype testing. For long-term production use, connect a persistent PostgreSQL database or attach persistent storage.

## Main functions

- Separate Staff, Office and Management portals
- Mobile camera QR scanning with manual fallback
- 303 seeded hospital assets and 21 hospital locations
- Asset take, transfer, return and maintenance reporting
- Automatic low-availability return requests
- NEED and RETURN IN 10 MINUTES responses
- Messages between devices
- Emergency alert broadcast to all logged-in users
- Office employee and asset registration
- QR-code printing page
- Management graphs and 48-hour CSV report
- Responsive mobile, tablet and laptop layout

## Data files

The application creates `meditrack.db` automatically on first run.
Delete that file only when you intentionally want a completely new database and setup.


## Live mobile camera

A mobile browser blocks the camera on a normal local HTTP address such as `http://192.168.x.x:5000`.

Double-click `START_SECURE_MOBILE_LINK.bat`. It creates a temporary HTTPS link. Open the displayed `https://...trycloudflare.com` link on the phone and allow camera permission.
