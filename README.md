# SideJob (סייד-ג'וב) — Freelance Services Platform

פלטפורמה לחיבור בין לקוחות לנותני שירות עצמאיים בישראל.

## 🚀 Live
**https://sidejob.bluedune-2855dd8a.germanywestcentral.azurecontainerapps.io**

## 🛠 Tech Stack
- **Backend:** Flask 2.3 + SQLAlchemy 2.0 + SocketIO
- **Database:** PostgreSQL (production) / SQLite (local dev)
- **Hosting:** Azure Container Apps
- **Container:** Docker + Gunicorn + Eventlet

## 🔒 Security
- CSRF protection on all forms
- Rate limiting (10/min login, 5/min signup)
- HTTPS enforced (Talisman)
- CSP, HSTS, X-Frame-Options security headers
- Session cookies: Secure + HttpOnly + SameSite=Lax
- SocketIO auth required

## 🏃 Local Development

```bash
pip install -r requirements.txt
python app.py
```

## 🐳 Docker

```bash
docker build -t sidejob .
docker run -p 5000:5000 -e DATABASE_URL=sqlite:///site.db sidejob
```

## 📂 Project Structure

```
sideJobhebrew/
├── app.py              # Main application
├── requirements.txt    # Python dependencies
├── Dockerfile          # Production container
├── templates/          # Jinja2 templates (Hebrew)
├── static/             # CSS, JS, images
│   └── uploads/        # User uploads
└── instance/           # SQLite DB (local only)
```
