from datetime import datetime, date, time, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit, join_room
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import re
import uuid
import secrets

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ========== SECURITY HEADERS (HTTPS / CSP / HSTS) ==========
talisman = Talisman(
    app,
    content_security_policy={
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' https://ajax.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://maxcdn.bootstrapcdn.com",
        'style-src': "'self' 'unsafe-inline' https://maxcdn.bootstrapcdn.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com",
        'img-src': "'self' data: blob:",
        'font-src': "'self' https://fonts.gstatic.com",
        'connect-src': "'self' ws: wss:",
        'frame-src': "'none'",
    },
    force_https=os.environ.get('FLASK_ENV') == 'production',
    session_cookie_secure=os.environ.get('FLASK_ENV') == 'production',
    session_cookie_http_only=True,
)

# ========== RATE LIMITING ==========
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.environ.get('REDIS_URL', 'memory://'),
)

# Database: PostgreSQL in production, SQLite for local dev
database_url = os.environ.get('DATABASE_URL')
if database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    # Connection pooling for PostgreSQL
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': int(os.environ.get('DB_POOL_SIZE', 5)),
        'pool_recycle': int(os.environ.get('DB_POOL_RECYCLE', 300)),
        'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW', 10)),
    }
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=120)

# Session security — auto-configure from environment
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ========== FILE UPLOAD CONFIG ==========
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['UPLOAD_PROVIDER'] = os.environ.get('UPLOAD_PROVIDER', 'local')

# Ensure upload folder exists (with absolute path)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app)


# ========== CSRF PROTECTION ==========

def generate_csrf_token():
    """Generate a CSRF token and store it in the session."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


@app.before_request
def csrf_protect():
    """Validate CSRF token on all state-changing requests."""
    # Always ensure a CSRF token exists in session
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        # Skip CSRF for login/signup, API, SocketIO, and health endpoints
        if (request.path in ('/login', '/signup')
            or request.path.startswith('/api/')
            or request.path.startswith('/socket.io')
            or request.path.startswith('/health')
            or request.path.startswith('/ready')):
            return
        token = session.get('_csrf_token', '')
        request_token = request.form.get('csrf_token', '')
        if not token or not request_token or not secrets.compare_digest(token, request_token):
            flash('בקשתך נדחתה מטעמי אבטחה. אנא רענן את הדף ונסה שוב.', 'danger')
            return redirect(request.referrer or url_for('index'))


@app.context_processor
def inject_csrf_token():
    """Make CSRF token available to all templates."""
    return {'csrf_token': generate_csrf_token()}


# ========== SOCKETIO AUTH ==========

@socketio.on('connect')
def handle_connect():
    """Allow all connections. Auth is checked per-event."""
    pass  # Don't reject unauthenticated users — it causes 400 spam


@socketio.on('join_room')
def handle_join_room(data):
    if 'user_id' not in session:
        return
    join_room(str(data['room']))


@socketio.on('message')
def handle_message(data):
    if 'user_id' not in session:
        return
    user_id = data.get('user_id')
    crew_member_id = data.get('crew_member_id')
    content = sanitize_input(data.get('content', ''))

# ========== PROFESSION CATEGORIES ==========
PROFESSION_CATEGORIES = [
    'ניקיון',           # Cleaning
    'שמרטפות',          # Babysitting
    'הולכת כלבים',       # Dog walking
    'גינון',             # Gardening
    'שיפוצים',           # Renovations
    'הובלות',            # Moving
    'שיעורים פרטיים',    # Private tutoring
    'תיקוני מחשב',       # Computer repairs
    'צילום',             # Photography
    'עיצוב גרפי',        # Graphic design
    'תרגום',             # Translation
    'בישול',             # Cooking
    'נהיגה/שליחויות',    # Driving/Deliveries
    'אירוח',             # Event hosting
    'ניהול רשתות חברתיות', # Social media management
    'בדיקות תוכנה',      # Software testing
    'עזרה בשיעורי בית',  # Homework help
    'ליווי לקשישים',     # Elderly companionship
    'אימון אישי',        # Personal training
    'חשמלאות',           # Electrical work
    'אינסטלציה',         # Plumbing
    'ניקוי חלונות',      # Window cleaning
    'הרכבת רהיטים',      # Furniture assembly
    'כתיבת תוכן',         # Content writing
    'אחר',               # Other
]

# ========== MODELS ==========

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_crew_member = db.Column(db.Boolean, default=False)
    
    user_profile = db.relationship('Profile', back_populates='user', uselist=False)
    crew_member = db.relationship('CrewMember', back_populates='user', uselist=False)
    bookings_as_customer = db.relationship('Booking', backref='customer', lazy='dynamic',
                                           foreign_keys='Booking.customer_id')
    
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', back_populates='user_profile')
    bio = db.Column(db.String(500), nullable=True)
    profile_picture = db.Column(db.String(300), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)


class Profession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    
    crew_members = db.relationship('CrewMemberProfession', back_populates='profession')


class CrewMemberProfession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    profession_id = db.Column(db.Integer, db.ForeignKey('profession.id'), nullable=False)
    experience_years = db.Column(db.Float, default=0)
    description = db.Column(db.String(300), nullable=True)
    
    crew_member = db.relationship('CrewMember', back_populates='professions')
    profession = db.relationship('Profession', back_populates='crew_members')


class CrewMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', back_populates='crew_member')
    name = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.String(500), nullable=True)
    hourly_fee = db.Column(db.Float, nullable=False, default=0)
    profile_picture = db.Column(db.String(300), nullable=False, default='profile.png')
    phone = db.Column(db.String(20), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    rating_avg = db.Column(db.Float, default=0)
    rating_count = db.Column(db.Integer, default=0)
    
    professions = db.relationship('CrewMemberProfession', back_populates='crew_member', cascade='all, delete-orphan')
    working_hours = db.relationship('WorkingHour', back_populates='crew_member', cascade='all, delete-orphan')
    bookings = db.relationship('Booking', backref='crew_member', lazy='dynamic',
                               foreign_keys='Booking.crew_member_id')
    hires = db.relationship('CrewMemberHire', backref='crew_member_ref', lazy='dynamic', overlaps="old_hires")
    reviews_received = db.relationship('Review', backref='crew_member_ref', lazy='dynamic', overlaps="reviews_list,crew_member")
    cart_items_ref = db.relationship('CartItem', backref='crew_member_ref', lazy='dynamic')


class WorkingHour(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = db.Column(db.String(5), nullable=False)  # "09:00"
    end_time = db.Column(db.String(5), nullable=False)    # "17:00"
    is_available = db.Column(db.Boolean, default=True)
    
    crew_member = db.relationship('CrewMember', back_populates='working_hours')
    
    DAY_NAMES = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    profession_id = db.Column(db.Integer, db.ForeignKey('profession.id'), nullable=True)
    booking_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    duration_hours = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, completed, cancelled
    description = db.Column(db.String(500), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    profession = db.relationship('Profession')


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)
    text = db.Column(db.String(500), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('reviews_written', lazy=True))
    crew_member = db.relationship('CrewMember', overlaps="reviews_received,crew_member_ref")
    booking = db.relationship('Booking', backref=db.backref('review', uselist=False))


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, completed, refunded
    payment_method = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    booking = db.relationship('Booking', backref=db.backref('transaction', uselist=False))


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    link = db.Column(db.String(300), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_from_crew = db.Column(db.Boolean, default=False)

    user = db.relationship('User', foreign_keys=[user_id])
    crew_member = db.relationship('CrewMember', foreign_keys=[crew_member_id])


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    user = db.relationship('User', backref=db.backref('cart_items', lazy='dynamic'))


class Errand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(1000), nullable=False)
    profession_id = db.Column(db.Integer, db.ForeignKey('profession.id'), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    budget_min = db.Column(db.Float, nullable=True)
    budget_max = db.Column(db.Float, nullable=True)
    preferred_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='open')  # open, assigned, completed, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    customer = db.relationship('User', foreign_keys=[customer_id])
    profession = db.relationship('Profession')
    proposals = db.relationship('Proposal', backref='errand', lazy='dynamic')


class Proposal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    errand_id = db.Column(db.Integer, db.ForeignKey('errand.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    crew_member = db.relationship('CrewMember', foreign_keys=[crew_member_id])


# ========== OLD MODEL (Keep for backward compatibility) ==========
class CrewMemberHire(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    crew_member = db.relationship('CrewMember', backref=db.backref('old_hires', lazy=True), overlaps="hires,crew_member_ref,crew_member")
    user = db.relationship('User', backref=db.backref('old_hires', lazy=True))


# ========== INIT DB ==========
def init_professions():
    """Ensure all profession categories exist in the database."""
    existing = Profession.query.count()
    if existing == 0:
        for cat in PROFESSION_CATEGORIES:
            p = Profession(name=cat, category=cat)
            db.session.add(p)
        db.session.commit()

with app.app_context():
    db.create_all()
    init_professions()


# ========== HELPER FUNCTIONS ==========

def login_required(f):
    """Decorator to require login."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('אנא התחבר קודם', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


def create_notification(user_id, title, content, link=None):
    notif = Notification(user_id=user_id, title=title, content=content, link=link)
    db.session.add(notif)
    db.session.commit()


def sanitize_input(text):
    """Basic input sanitization."""
    if not text:
        return text
    text = re.sub(r'<[^>]*>', '', text)
    return text.strip()


def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file):
    """Save an uploaded file and return the stored filename (without path)."""
    if not file or not file.filename:
        return None
    
    if not allowed_file(file.filename):
        return None
    
    try:
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{ext}"
        
        provider = app.config.get('UPLOAD_PROVIDER', 'local')
        
        if provider == 'azure_blob':
            from azure.storage.blob import BlobServiceClient
            conn_str = os.environ['AZURE_STORAGE_CONNECTION_STRING']
            container = os.environ.get('AZURE_STORAGE_CONTAINER', 'sidejob-uploads')
            blob_client = BlobServiceClient.from_connection_string(conn_str).get_blob_client(
                container=container, blob=unique_filename
            )
            blob_client.upload_blob(file.read(), overwrite=True)
            print(f"UPLOADED to blob: {container}/{unique_filename}", flush=True)
            return unique_filename
        else:
            # Local storage
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            file.save(filepath)
            return unique_filename
    except Exception as e:
        print(f"ERROR saving uploaded file: {e}", flush=True)
        return None


# ========== UPLOAD SERVING ==========

@app.route('/uploads/<filename>')
def serve_upload(filename):
    """Serve uploaded files from Azure Blob or local disk."""
    provider = app.config.get('UPLOAD_PROVIDER', 'local')
    
    if provider == 'azure_blob':
        try:
            from azure.storage.blob import BlobServiceClient
            conn_str = os.environ['AZURE_STORAGE_CONNECTION_STRING']
            container = os.environ.get('AZURE_STORAGE_CONTAINER', 'sidejob-uploads')
            blob_client = BlobServiceClient.from_connection_string(conn_str).get_blob_client(
                container=container, blob=filename
            )
            stream = blob_client.download_blob()
            return Response(
                stream.readall(),
                status=200,
                mimetype=stream.properties.content_settings.content_type or 'image/jpeg',
                headers={'Cache-Control': 'public, max-age=31536000'}
            )
        except Exception as e:
            print(f"ERROR serving blob {filename}: {e}", flush=True)
            return '', 404
    else:
        # Local
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.context_processor
def inject_image_helper():
    """Make get_image_url available to all templates."""
    def get_image_url(stored_value):
        if not stored_value:
            return url_for('static', filename='profile.png')
        if stored_value == 'profile.png':
            return url_for('static', filename='profile.png')
        if stored_value.startswith('http'):
            return stored_value
        if stored_value.startswith('/static/'):
            # Legacy format — already a full path
            return stored_value
        # New format — just UUID filename, serve via /uploads/
        return url_for('serve_upload', filename=stored_value)
    return {'get_image_url': get_image_url}


# ========== AUTH ROUTES ==========

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username', ''))
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            if user.is_crew_member:
                cm = CrewMember.query.filter_by(user_id=user.id).first()
                if cm:
                    session['is_crew_member'] = True
                    session['crew_member_id'] = cm.id
                else:
                    session['is_crew_member'] = False
            else:
                session['is_crew_member'] = False
            flash(f'ברוך הבא, {user.first_name}!', 'success')
            
            if user.is_crew_member:
                crew_member = CrewMember.query.filter_by(user_id=user.id).first()
                if crew_member:
                    return redirect(url_for('crew_member_profile', crew_member_id=crew_member.id))
            return redirect(url_for('index'))
        else:
            flash('שם משתמש או סיסמה לא נכונים', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('התנתקת בהצלחה', 'success')
    return redirect(url_for('index'))


@app.route('/signup', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def signup():
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username', ''))
        email = sanitize_input(request.form.get('email', ''))
        password = request.form.get('password', '')
        first_name = sanitize_input(request.form.get('first_name', ''))
        last_name = sanitize_input(request.form.get('last_name', ''))
        phone = sanitize_input(request.form.get('phone', ''))
        is_crew_member = 'is_crew_member' in request.form
        
        errors = []
        if not username or len(username) < 3:
            errors.append('שם המשתמש חייב להכיל לפחות 3 תווים')
        if not email or '@' not in email:
            errors.append('כתובת אימייל לא תקינה')
        if not password or len(password) < 6:
            errors.append('הסיסמה חייבת להכיל לפחות 6 תווים')
        if User.query.filter_by(username=username).first():
            errors.append('שם המשתמש כבר קיים')
        if User.query.filter_by(email=email).first():
            errors.append('כתובת האימייל כבר קיימת')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('signup.html', form_data=request.form, professions=Profession.query.all())
        
        hashed_password = generate_password_hash(password)
        user = User(
            username=username, email=email, password_hash=hashed_password,
            first_name=first_name, last_name=last_name, phone=phone,
            is_crew_member=is_crew_member
        )
        profile = Profile(user=user)
        db.session.add(user)
        db.session.commit()

        if is_crew_member:
            name = sanitize_input(request.form.get('name', ''))
            bio = sanitize_input(request.form.get('bio', ''))
            hourly_fee = float(request.form.get('hourly_fee', 0))
            location = sanitize_input(request.form.get('location', ''))
            cm_phone = sanitize_input(request.form.get('cm_phone', ''))
            
            # Handle profile picture upload
            profile_picture = 'profile.png'
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                uploaded_path = save_uploaded_file(file)
                if uploaded_path:
                    profile_picture = uploaded_path
            
            crew_member = CrewMember(
                user_id=user.id, name=name or username,
                bio=bio, hourly_fee=hourly_fee,
                profile_picture=profile_picture,
                location=location, phone=cm_phone or phone
            )
            db.session.add(crew_member)
            db.session.commit()
            
            profession_ids = request.form.getlist('professions')
            for pid in profession_ids:
                try:
                    prof = Profession.query.get(int(pid))
                    if prof:
                        cp = CrewMemberProfession(crew_member_id=crew_member.id, profession_id=prof.id)
                        db.session.add(cp)
                except (ValueError, TypeError):
                    pass
            db.session.commit()
            
            flash('החשבון נוצר בהצלחה! כעת הגדר את שעות העבודה שלך.', 'success')
            return redirect(url_for('edit_working_hours', crew_member_id=crew_member.id))

        flash('החשבון נוצר בהצלחה!', 'success')
        return redirect(url_for('login'))
    
    professions = Profession.query.all()
    return render_template('signup.html', professions=professions)


# ========== INDEX / SEARCH ==========

@app.route('/')
def index():
    crew_members = CrewMember.query.all()
    professions = Profession.query.all()
    
    profession_filter = request.args.get('profession', '')
    search_query = sanitize_input(request.args.get('q', ''))
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')
    location_filter = sanitize_input(request.args.get('location', ''))
    availability_filter = request.args.get('available', '')
    
    if search_query:
        crew_members = [cm for cm in crew_members if 
                       search_query in cm.name or 
                       search_query in (cm.bio or '') or 
                       search_query in (cm.location or '')]
    
    if profession_filter:
        try:
            prof = Profession.query.filter_by(id=int(profession_filter)).first()
            if prof:
                prof_ids = [cp.crew_member_id for cp in CrewMemberProfession.query.filter_by(profession_id=prof.id).all()]
                crew_members = [cm for cm in crew_members if cm.id in prof_ids]
        except ValueError:
            pass
    
    if min_price:
        try:
            crew_members = [cm for cm in crew_members if cm.hourly_fee >= float(min_price)]
        except ValueError:
            pass
    
    if max_price:
        try:
            crew_members = [cm for cm in crew_members if cm.hourly_fee <= float(max_price)]
        except ValueError:
            pass
    
    if location_filter:
        crew_members = [cm for cm in crew_members if location_filter in (cm.location or '')]
    
    if availability_filter == '1':
        crew_members = [cm for cm in crew_members if cm.available]
    
    return render_template('index.html', crew_members=crew_members, 
                          professions=professions, request=request)


@app.route('/search_suggestions')
def search_suggestions():
    q = sanitize_input(request.args.get('q', '')).lower()
    if not q or len(q) < 2:
        return jsonify([])
    
    results = []
    profs = Profession.query.filter(Profession.name.contains(q)).limit(5).all()
    for p in profs:
        results.append({'type': 'profession', 'text': p.name, 
                       'url': url_for('index', profession=p.id)})
    
    members = CrewMember.query.filter(
        db.or_(CrewMember.name.contains(q), CrewMember.bio.contains(q), CrewMember.location.contains(q))
    ).limit(5).all()
    for m in members:
        results.append({'type': 'crew', 'text': f"{m.name} - {m.location or 'מיקום לא צוין'}", 
                       'url': url_for('crew_member_profile', crew_member_id=m.id)})
    
    return jsonify(results)


# ========== CREW MEMBER PROFILE ==========

@app.route('/crew_member_profile/<int:crew_member_id>', methods=['GET', 'POST'])
def crew_member_profile(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member:
        flash('חבר צוות לא נמצא', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        if 'user_id' not in session:
            flash('אנא התחבר קודם', 'warning')
            return redirect(url_for('login'))
        
        name = sanitize_input(request.form.get('name'))
        if name:
            crew_member.name = name
            crew_member.bio = sanitize_input(request.form.get('bio'))
            crew_member.hourly_fee = float(request.form.get('hourly_fee', 0))
            
            # Handle profile picture upload
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and file.filename:
                    uploaded_path = save_uploaded_file(file)
                    if uploaded_path:
                        crew_member.profile_picture = uploaded_path
            
            crew_member.location = sanitize_input(request.form.get('location'))
            crew_member.phone = sanitize_input(request.form.get('phone'))
            crew_member.available = 'available' in request.form
            db.session.commit()
            flash('הפרופיל עודכן בהצלחה', 'success')
        return redirect(url_for('crew_member_profile', crew_member_id=crew_member.id))
    
    reviews = Review.query.filter_by(crew_member_id=crew_member_id).order_by(Review.id.desc()).all()
    chat_messages = ChatMessage.query.filter_by(crew_member_id=crew_member_id).order_by(ChatMessage.timestamp).all()
    working_hours = WorkingHour.query.filter_by(crew_member_id=crew_member_id).all()
    professions = CrewMemberProfession.query.filter_by(crew_member_id=crew_member_id).all()
    
    return render_template('crew_member_profile.html', 
                          crew_member=crew_member, 
                          reviews=reviews, 
                          chat_messages=chat_messages,
                          working_hours=working_hours,
                          professions=professions)


# ========== WORKING HOURS ==========

@app.route('/edit_working_hours/<int:crew_member_id>', methods=['GET', 'POST'])
@login_required
def edit_working_hours(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member or session['user_id'] != crew_member.user_id:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        WorkingHour.query.filter_by(crew_member_id=crew_member_id).delete()
        
        days = request.form.getlist('day_of_week[]')
        start_times = request.form.getlist('start_time[]')
        end_times = request.form.getlist('end_time[]')
        
        for i, day in enumerate(days):
            if i < len(start_times) and i < len(end_times):
                wh = WorkingHour(
                    crew_member_id=crew_member_id,
                    day_of_week=int(day),
                    start_time=start_times[i],
                    end_time=end_times[i],
                    is_available=True
                )
                db.session.add(wh)
        
        db.session.commit()
        flash('שעות העבודה נשמרו בהצלחה!', 'success')
        return redirect(url_for('crew_member_profile', crew_member_id=crew_member_id))
    
    working_hours = WorkingHour.query.filter_by(crew_member_id=crew_member_id).all()
    return render_template('edit_working_hours.html', 
                          crew_member=crew_member, 
                          working_hours=working_hours,
                          days=WorkingHour.DAY_NAMES)


@app.route('/api/get_available_slots/<int:crew_member_id>/<date_str>')
def get_available_slots(crew_member_id, date_str):
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member:
        return jsonify([])
    
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify([])
    
    day_of_week = target_date.weekday()
    hours = WorkingHour.query.filter_by(
        crew_member_id=crew_member_id, 
        day_of_week=day_of_week,
        is_available=True
    ).all()
    
    existing_bookings = Booking.query.filter_by(
        crew_member_id=crew_member_id, 
        booking_date=target_date,
    ).filter(Booking.status.in_(['pending', 'confirmed'])).all()
    
    slots = []
    for wh in hours:
        start_h, start_m = map(int, wh.start_time.split(':'))
        end_h, end_m = map(int, wh.end_time.split(':'))
        
        current = start_h * 60 + start_m
        end = end_h * 60 + end_m
        
        while current + 60 <= end:
            slot_start_h = current // 60
            slot_start_m = current % 60
            slot_end = current + 60
            slot_end_h = slot_end // 60
            slot_end_m = slot_end % 60
            
            slot_start_str = f"{slot_start_h:02d}:{slot_start_m:02d}"
            slot_end_str = f"{slot_end_h:02d}:{slot_end_m:02d}"
            
            conflict = any(bk.start_time == slot_start_str for bk in existing_bookings)
            
            if not conflict:
                slots.append({
                    'start': slot_start_str,
                    'end': slot_end_str,
                    'label': f"{slot_start_str} - {slot_end_str}"
                })
            
            current = slot_end
    
    return jsonify(slots)


# ========== BOOKING SYSTEM ==========

@app.route('/book_crew_member', methods=['POST'])
@login_required
def book_crew_member():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400
    
    crew_member_id = data.get('crew_member_id')
    booking_date = data.get('date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    description = sanitize_input(data.get('description', ''))
    location = sanitize_input(data.get('location', ''))
    profession_id = data.get('profession_id')
    
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member:
        return jsonify({'success': False, 'error': 'חבר צוות לא נמצא'}), 404
    
    if not crew_member.available:
        return jsonify({'success': False, 'error': 'חבר הצוות לא זמין כרגע'}), 400
    
    try:
        bdate = datetime.strptime(booking_date, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'תאריך לא תקין'}), 400
    
    start_parts = start_time.split(':')
    end_parts = end_time.split(':')
    duration = (int(end_parts[0]) * 60 + int(end_parts[1]) - int(start_parts[0]) * 60 - int(start_parts[1])) / 60
    
    if duration <= 0:
        return jsonify({'success': False, 'error': 'שעות לא תקינות'}), 400
    
    existing = Booking.query.filter_by(
        crew_member_id=crew_member_id,
        booking_date=bdate,
        start_time=start_time
    ).filter(Booking.status.in_(['pending', 'confirmed'])).first()
    
    if existing:
        return jsonify({'success': False, 'error': 'השעה הזו כבר תפוסה'}), 400
    
    total_price = duration * crew_member.hourly_fee
    
    booking = Booking(
        crew_member_id=crew_member_id,
        customer_id=session['user_id'],
        profession_id=profession_id,
        booking_date=bdate,
        start_time=start_time,
        end_time=end_time,
        duration_hours=duration,
        total_price=total_price,
        status='pending',
        description=description,
        location=location
    )
    db.session.add(booking)
    db.session.commit()
    
    user = User.query.get(session['user_id'])
    create_notification(
        crew_member.user_id,
        'הזמנה חדשה!',
        f'{user.full_name()} הזמין אותך לתאריך {booking_date} בשעה {start_time}',
        url_for('my_bookings')
    )
    
    return jsonify({
        'success': True,
        'booking_id': booking.id,
        'message': 'ההזמנה בוצעה בהצלחה! ממתין לאישור חבר הצוות.'
    })


@app.route('/my_bookings')
@login_required
def my_bookings():
    user = User.query.get(session['user_id'])
    
    if user.is_crew_member:
        crew = CrewMember.query.filter_by(user_id=user.id).first()
        bookings_as_crew = Booking.query.filter_by(crew_member_id=crew.id).order_by(Booking.created_at.desc()).all() if crew else []
        bookings_as_customer = Booking.query.filter_by(customer_id=user.id).order_by(Booking.created_at.desc()).all()
        return render_template('my_bookings.html', 
                              bookings_as_crew=bookings_as_crew, 
                              bookings_as_customer=bookings_as_customer,
                              is_crew=True)
    else:
        bookings_as_customer = Booking.query.filter_by(customer_id=user.id).order_by(Booking.created_at.desc()).all()
        return render_template('my_bookings.html', 
                              bookings_as_customer=bookings_as_customer,
                              is_crew=False)


@app.route('/confirm_booking/<int:booking_id>')
@login_required
def confirm_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        flash('הזמנה לא נמצאה', 'danger')
        return redirect(url_for('my_bookings'))
    
    crew = CrewMember.query.get(booking.crew_member_id)
    if not crew or crew.user_id != session['user_id']:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('my_bookings'))
    
    booking.status = 'confirmed'
    booking.confirmed_at = datetime.utcnow()
    db.session.commit()
    
    create_notification(
        booking.customer_id,
        'ההזמנה אושרה!',
        f'ההזמנה שלך אצל {crew.name} בתאריך {booking.booking_date} אושרה!',
        url_for('my_bookings')
    )
    
    flash('ההזמנה אושרה בהצלחה!', 'success')
    return redirect(url_for('my_bookings'))


@app.route('/complete_booking/<int:booking_id>')
@login_required
def complete_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        flash('הזמנה לא נמצאה', 'danger')
        return redirect(url_for('my_bookings'))
    
    crew = CrewMember.query.get(booking.crew_member_id)
    if not crew or crew.user_id != session['user_id']:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('my_bookings'))
    
    booking.status = 'completed'
    booking.completed_at = datetime.utcnow()
    db.session.commit()
    
    transaction = Transaction(
        booking_id=booking.id,
        customer_id=booking.customer_id,
        crew_member_id=crew.id,
        amount=booking.total_price,
        status='completed',
        payment_method='מזומן'
    )
    db.session.add(transaction)
    
    db.session.commit()
    
    create_notification(
        booking.customer_id,
        'ההזמנה הושלמה!',
        f'העבודה אצל {crew.name} הושלמה. אנא השאר/י ביקורת!',
        url_for('crew_member_profile', crew_member_id=crew.id)
    )
    
    flash('ההזמנה הושלמה בהצלחה!', 'success')
    return redirect(url_for('my_bookings'))


@app.route('/cancel_booking/<int:booking_id>')
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if not booking:
        flash('הזמנה לא נמצאה', 'danger')
        return redirect(url_for('my_bookings'))
    
    user = User.query.get(session['user_id'])
    crew = CrewMember.query.get(booking.crew_member_id)
    
    if booking.customer_id == session['user_id'] or (crew and crew.user_id == session['user_id']):
        booking.status = 'cancelled'
        db.session.commit()
        
        if booking.customer_id == session['user_id']:
            create_notification(
                crew.user_id,
                'הזמנה בוטלה',
                f'{user.full_name()} ביטל/ה את ההזמנה לתאריך {booking.booking_date}',
                url_for('my_bookings')
            )
        else:
            customer = User.query.get(booking.customer_id)
            create_notification(
                booking.customer_id,
                'הזמנה בוטלה',
                f'{crew.name} ביטל/ה את ההזמנה לתאריך {booking.booking_date}',
                url_for('my_bookings')
            )
        
        flash('ההזמנה בוטלה', 'success')
    else:
        flash('גישה נדחתה', 'danger')
    
    return redirect(url_for('my_bookings'))


# ========== ERRANDS / JOB POSTING ==========

@app.route('/errands')
def errands():
    errands_list = Errand.query.filter_by(status='open').order_by(Errand.created_at.desc()).all()
    professions = Profession.query.all()
    return render_template('errands.html', errands=errands_list, professions=professions)


@app.route('/post_errand', methods=['GET', 'POST'])
@login_required
def post_errand():
    if request.method == 'POST':
        title = sanitize_input(request.form.get('title', ''))
        description = sanitize_input(request.form.get('description', ''))
        profession_id = request.form.get('profession_id')
        location = sanitize_input(request.form.get('location', ''))
        budget_min = request.form.get('budget_min')
        budget_max = request.form.get('budget_max')
        preferred_date_str = request.form.get('preferred_date')
        
        if not title:
            flash('נא להזין כותרת', 'danger')
            return render_template('post_errand.html', professions=Profession.query.all())
        
        preferred_date = None
        if preferred_date_str:
            try:
                preferred_date = datetime.strptime(preferred_date_str, '%Y-%m-%d').date()
            except ValueError:
                preferred_date = None
        
        errand = Errand(
            customer_id=session['user_id'],
            title=title,
            description=description,
            profession_id=int(profession_id) if profession_id else None,
            location=location,
            budget_min=float(budget_min) if budget_min else None,
            budget_max=float(budget_max) if budget_max else None,
            preferred_date=preferred_date
        )
        db.session.add(errand)
        db.session.commit()
        
        flash('המשימה פורסמה בהצלחה!', 'success')
        return redirect(url_for('errands'))
    
    professions = Profession.query.all()
    return render_template('post_errand.html', professions=professions)


@app.route('/submit_proposal/<int:errand_id>', methods=['POST'])
@login_required
def submit_proposal(errand_id):
    user = User.query.get(session['user_id'])
    if not user.is_crew_member:
        flash('רק חברי צוות יכולים להגיש הצעות', 'danger')
        return redirect(url_for('errands'))
    
    crew = CrewMember.query.filter_by(user_id=user.id).first()
    if not crew:
        flash('תחילה צור פרופיל חבר צוות', 'warning')
        return redirect(url_for('signup'))
    
    price = float(request.form.get('price', 0))
    description = sanitize_input(request.form.get('description', ''))
    
    if price <= 0:
        flash('נא להזין מחיר תקין', 'danger')
        return redirect(url_for('errands'))
    
    proposal = Proposal(
        errand_id=errand_id,
        crew_member_id=crew.id,
        price=price,
        description=description
    )
    db.session.add(proposal)
    db.session.commit()
    
    errand = Errand.query.get(errand_id)
    if errand:
        create_notification(
            errand.customer_id,
            'הצעה חדשה!',
            f'{crew.name} הגיש/ה הצעה למשימה "{errand.title}" במחיר ₪{price}',
            url_for('view_proposals', errand_id=errand_id)
        )
    
    flash('ההצעה נשלחה בהצלחה!', 'success')
    return redirect(url_for('errands'))


@app.route('/view_proposals/<int:errand_id>')
@login_required
def view_proposals(errand_id):
    errand = Errand.query.get(errand_id)
    if not errand or errand.customer_id != session['user_id']:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('errands'))
    
    proposals = Proposal.query.filter_by(errand_id=errand_id).all()
    return render_template('view_proposals.html', errand=errand, proposals=proposals)


@app.route('/accept_proposal/<int:proposal_id>')
@login_required
def accept_proposal(proposal_id):
    proposal = Proposal.query.get(proposal_id)
    if not proposal:
        flash('הצעה לא נמצאה', 'danger')
        return redirect(url_for('errands'))
    
    errand = Errand.query.get(proposal.errand_id)
    if not errand or errand.customer_id != session['user_id']:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('errands'))
    
    proposal.status = 'accepted'
    errand.status = 'assigned'
    
    for p in errand.proposals:
        if p.id != proposal_id:
            p.status = 'rejected'
    
    db.session.commit()
    
    create_notification(
        proposal.crew_member.user_id,
        'ההצעה התקבלה!',
        f'ההצעה שלך למשימה "{errand.title}" התקבלה!',
        url_for('my_bookings')
    )
    
    flash('ההצעה התקבלה!', 'success')
    return redirect(url_for('view_proposals', errand_id=errand.id))


# ========== REVIEWS ==========

@app.route('/submit_review/<int:crew_member_id>', methods=['POST'])
@login_required
def submit_review(crew_member_id):
    text = sanitize_input(request.form.get('text', ''))
    rating = int(request.form.get('rating', 5))
    booking_id = request.form.get('booking_id')
    
    if not text:
        flash('נא לכתוב ביקורת', 'danger')
        return redirect(url_for('crew_member_profile', crew_member_id=crew_member_id))
    
    review = Review(
        user_id=session['user_id'],
        crew_member_id=crew_member_id,
        text=text,
        rating=rating,
        booking_id=int(booking_id) if booking_id else None
    )
    db.session.add(review)
    
    crew = CrewMember.query.get(crew_member_id)
    reviews = Review.query.filter_by(crew_member_id=crew_member_id).all()
    if reviews:
        crew.rating_avg = sum(r.rating for r in reviews) / len(reviews)
        crew.rating_count = len(reviews)
    
    db.session.commit()
    flash('הביקורת נשלחה בהצלחה!', 'success')
    return redirect(url_for('crew_member_profile', crew_member_id=crew_member_id))


# ========== CHAT ==========
    
    if not content:
        return
    
    timestamp = datetime.utcnow()
    user = User.query.get(user_id)
    username = user.username if user else ''

    new_message = ChatMessage(
        user_id=user_id,
        crew_member_id=crew_member_id,
        content=content,
        timestamp=timestamp
    )
    db.session.add(new_message)
    db.session.commit()

    data['username'] = username
    data['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
    emit('message', data, room=str(crew_member_id))


@app.route('/chat_with_crew_member/<int:crew_member_id>', methods=['GET', 'POST'])
@login_required
def chat_with_crew_member(crew_member_id):
    user_id = session['user_id']
    crew_member = CrewMember.query.get(crew_member_id)
    user = User.query.get(user_id)

    if not crew_member:
        flash('חבר צוות לא נמצא', 'danger')
        return redirect(url_for('index'))

    # Allow both the crew member themselves and any logged-in user (customer) to chat
    if crew_member.user_id != user_id and not user:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        content = sanitize_input(request.form.get('content', ''))
        if content:
            chat = ChatMessage(user_id=user_id, crew_member_id=crew_member_id, content=content)
            db.session.add(chat)
            db.session.commit()

            data = {
                'user_id': user_id,
                'crew_member_id': crew_member_id,
                'content': content,
                'username': user.username if user else ''
            }
            socketio.emit('message', data, room=str(crew_member_id))

    chat_messages = ChatMessage.query.filter_by(
        crew_member_id=crew_member_id
    ).order_by(ChatMessage.timestamp).all()
    
    return render_template('crew_member_profile.html', crew_member=crew_member, chat_messages=chat_messages)


# ========== CREW MEMBER MANAGEMENT ==========

@app.route('/edit_crew_member/<int:crew_member_id>', methods=['GET', 'POST'])
@login_required
def edit_crew_member(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member or session['user_id'] != crew_member.user_id:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        crew_member.name = sanitize_input(request.form.get('name', crew_member.name))
        crew_member.bio = sanitize_input(request.form.get('bio'))
        crew_member.hourly_fee = float(request.form.get('hourly_fee', 0))
        
        # Handle profile picture upload
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename:
                uploaded_path = save_uploaded_file(file)
                if uploaded_path:
                    crew_member.profile_picture = uploaded_path
        
        crew_member.location = sanitize_input(request.form.get('location'))
        crew_member.phone = sanitize_input(request.form.get('phone'))
        crew_member.available = 'available' in request.form
        db.session.commit()
        
        flash('הפרופיל עודכן בהצלחה', 'success')
        return redirect(url_for('crew_member_profile', crew_member_id=crew_member.id))

    return render_template('edit_crew_member.html', crew_member=crew_member)


@app.route('/delete_crew_member/<int:crew_member_id>')
@login_required
def delete_crew_member(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member or session['user_id'] != crew_member.user_id:
        flash('גישה נדחתה', 'danger')
        return redirect(url_for('index'))

    user = crew_member.user
    user.is_crew_member = False
    db.session.delete(crew_member)
    db.session.commit()
    flash('הפרופיל נמחק בהצלחה', 'success')
    return redirect(url_for('index'))


@app.route('/toggle_availability/<int:crew_member_id>')
@login_required
def toggle_availability(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if crew_member:
        if session['user_id'] == crew_member.user_id:
            crew_member.available = not crew_member.available
            db.session.commit()
            status = 'זמין' if crew_member.available else 'לא זמין'
            flash(f'הסטטוס שונה ל{status}', 'success')
        else:
            flash('גישה נדחתה', 'danger')
    else:
        flash('חבר צוות לא נמצא', 'danger')
    return redirect(url_for('index'))


# ========== CART ==========

@app.route('/cart', methods=['GET', 'POST'])
@login_required
def cart():
    user = User.query.get(session['user_id'])
    cart_crew_members = user.cart_items.all()
    total = sum([item.crew_member_ref.hourly_fee * item.quantity for item in cart_crew_members])
    return render_template('cart.html', cart_crew_members=cart_crew_members, total=total)


@app.route('/hire_crew_member', methods=['POST'])
@login_required
def hire_crew_member():
    data = request.get_json() or {}
    crew_member_id = data.get('crew_member_id')
    crew_member = CrewMember.query.get(crew_member_id)

    if not crew_member:
        return jsonify({'success': False, 'error': 'Crew member not found'}), 404

    user = User.query.get(session['user_id'])
    cart_item = CartItem.query.filter_by(user_id=user.id, crew_member_id=crew_member_id).first()
    
    if cart_item:
        cart_item.quantity += 1
    else:
        cart_item = CartItem(user_id=user.id, crew_member_id=crew_member_id, quantity=1)
        db.session.add(cart_item)

    db.session.commit()
    return jsonify({'success': True})


@app.route('/unhire_crew_member/<int:crew_member_id>')
@login_required
def unhire_crew_member(crew_member_id):
    user = User.query.get(session['user_id'])
    cart_item = CartItem.query.filter_by(user_id=user.id, crew_member_id=crew_member_id).first()

    if cart_item:
        db.session.delete(cart_item)
        db.session.commit()
        flash('החבר הוסר מהעגלה', 'success')
    else:
        flash('החבר לא נמצא בעגלה', 'danger')

    return redirect(url_for('cart'))


# ========== USER PROFILE ==========

@app.route('/edit_user', methods=['GET', 'POST'])
@login_required
def edit_user():
    user = User.query.get(session['user_id'])
    if not user:
        flash('משתמש לא נמצא', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        user.first_name = sanitize_input(request.form.get('first_name', user.first_name))
        user.last_name = sanitize_input(request.form.get('last_name', user.last_name))
        user.email = sanitize_input(request.form.get('email', user.email))
        
        if not user.user_profile:
            user.user_profile = Profile()
        
        user.user_profile.bio = sanitize_input(request.form.get('bio'))
        
        # Handle profile picture upload
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename:
                uploaded_path = save_uploaded_file(file)
                if uploaded_path:
                    user.user_profile.profile_picture = uploaded_path
        
        user.user_profile.location = sanitize_input(request.form.get('location'))
        user.user_profile.phone_number = sanitize_input(request.form.get('phone_number'))
        user.phone = sanitize_input(request.form.get('phone_number', user.phone))

        db.session.commit()
        flash('הפרטים עודכנו בהצלחה!', 'success')
        return redirect(url_for('index'))

    return render_template('edit_user.html', current_user=user)


# ========== NOTIFICATIONS ==========

@app.route('/notifications')
@login_required
def notifications():
    user_notifications = Notification.query.filter_by(
        user_id=session['user_id']
    ).order_by(Notification.timestamp.desc()).all()
    
    for n in user_notifications:
        n.is_read = True
    db.session.commit()
    
    return render_template('notifications.html', notifications=user_notifications)


@app.route('/api/unread_notifications')
@login_required
def unread_notifications():
    count = Notification.query.filter_by(
        user_id=session['user_id'], is_read=False
    ).count()
    return jsonify({'count': count})


# ========== HEALTH CHECK ==========

@app.route('/health')
def health():
    """Health check endpoint for Azure Container Apps."""
    try:
        db.session.execute(db.text('SELECT 1'))
        db_status = 'connected'
    except Exception:
        db_status = 'disconnected'
    return jsonify({
        'status': 'healthy' if db_status == 'connected' else 'degraded',
        'database': db_status,
        'timestamp': datetime.utcnow().isoformat(),
    })


@app.route('/ready')
def ready():
    """Readiness probe — confirms DB is reachable."""
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ready', 'database': 'connected'}), 200
    except Exception as e:
        return jsonify({'status': 'not ready', 'error': str(e)}), 503


# ========== STATIC PAGES ==========

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/taxes')
def taxes():
    return render_template('taxes.html')


# ========== ERROR HANDLERS ==========

@app.errorhandler(404)
def not_found(e):
    return render_template('errors.html', error_code=404, message='הדף לא נמצא'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('errors.html', error_code=500, message='שגיאת שרת'), 500


# ========== RUN ==========

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    socketio.run(app, debug=debug_mode, allow_unsafe_werkzeug=debug_mode)