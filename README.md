# LetsChat 🚀

A modern, full-featured real-time chat and WebRTC audio/video calling application built with Django Channels, Daphne, and WebRTC.

## ✨ Features
- 💬 **Real-time Messaging**: Instant bidirectional communication powered by Django Channels & WebSockets.
- 📞 **Voice & Video Calling**: Peer-to-peer WebRTC calling with audio/video stream exchange and camera flip.
- 🆔 **6-Digit Unique IDs**: Fast and simple user discovery via personal unique numeric codes.
- 🟢 **Live Online & Last Seen Status**: Real-time presence indicators and last seen timestamps.
- 🔒 **User Blocking & Moderation**: Instant two-way conversation blocking and safety controls.
- 🖼️ **Profile Management**: Profile pictures (DP), avatars, and username management.
- 🎨 **Sleek Modern UI**: Premium dark theme interface inspired by modern messaging apps.

## 🛠️ Quick Start

```bash
# Clone the repository
git clone https://github.com/Alpha-Air-Conditioning/LetsChat.git
cd LetsChat

# Create virtual environment & install dependencies
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Start development server
python manage.py runserver 0.0.0.0:8000
```
