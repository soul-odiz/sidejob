from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room



app = Flask(__name__)
app.secret_key = 'a_random_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['WTF_CSRF_SECRET_KEY'] = 'a_random_csrf_secret_key'

db = SQLAlchemy(app)
socketio = SocketIO(app)


class CrewMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', back_populates='crew_member')
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300), nullable=True)
    hourly_fee = db.Column(db.Float, nullable=False)
    profile_picture = db.Column(db.String(100), nullable=False)
    star_rating = db.Column(db.Integer, nullable=False)
    available = db.Column(db.Boolean, default=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    user_profile = db.relationship('Profile', back_populates='user', uselist=False)
    hires = db.relationship('CrewMemberHire', backref='customer', lazy='dynamic')
    is_crew_member = db.Column(db.Boolean, default=False)
    crew_member = db.relationship('CrewMember', back_populates='user', uselist=False)


class CrewMemberHire(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    crew_member = db.relationship('CrewMember', backref=db.backref('hires', lazy=True))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('customer_hires', lazy=True), overlaps="customer,hires")


class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', back_populates='user_profile')
    bio = db.Column(db.String(300), nullable=True)
    profile_picture = db.Column(db.String(100), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    crew_member = db.relationship('CrewMember', foreign_keys=[crew_member_id])



class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    profile_picture = db.Column(db.String(100), nullable=True)

    user = db.relationship('User', backref=db.backref('reviews_written', lazy=True))
    crew_member = db.relationship('CrewMember', backref=db.backref('reviews_received', lazy=True))


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('cart_items', lazy=True))
    crew_member_id = db.Column(db.Integer, db.ForeignKey('crew_member.id'), nullable=False)
    crew_member = db.relationship('CrewMember', backref=db.backref('in_carts', lazy=True))
    quantity = db.Column(db.Integer, nullable=False)


with app.app_context():
 db.create_all()

@app.route('/')
def index():
    crew_members = CrewMember.query.all()
    return render_template('index.html', crew_members=crew_members)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            if user.is_crew_member:
                crew_member = CrewMember.query.filter_by(user_id=user.id).first()
                if crew_member:
                    return redirect(url_for('crew_member_profile', crew_member_id=crew_member.id))
                else:
                    flash('Crew member not found.', 'danger')
                    return redirect(url_for('index'))
            else:
                return redirect(url_for('index'))
        else:
            flash('שם משתמש או סיסמה לא נכונים', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        is_crew_member = 'is_crew_member' in request.form
        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, password_hash=hashed_password, first_name=first_name, last_name=last_name, is_crew_member=is_crew_member)

        # Create a user profile
        profile = Profile()
        user.user_profile = profile

        db.session.add(user)
        db.session.commit()

        if is_crew_member:
            # Get crew member information from the form
            name = request.form['name']
            description = request.form['description']
            hourly_fee = float(request.form['hourly_fee'])
            profile_picture = request.form['profile_picture']
            star_rating = float(request.form['star_rating'])

            # Create a new crew member
            crew_member = CrewMember(user_id=user.id, name=name, description=description, hourly_fee=hourly_fee, profile_picture=profile_picture, star_rating=star_rating)
            db.session.add(crew_member)
            db.session.commit()

        flash('Account created successfully!', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')



@app.route('/toggle_availability/<int:crew_member_id>')
def toggle_availability(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if crew_member:
        crew_member.available = not crew_member.available
        db.session.commit()
    else:
        flash("Crew member not found.", "danger")
    return redirect(url_for('index'))


@app.route('/cart', methods=['GET', 'POST'])
def cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    cart_crew_members = user.cart_items
    total = sum([item.crew_member.hourly_fee * item.quantity for item in cart_crew_members])

    return render_template('cart.html', cart_crew_members=cart_crew_members, total=total)


@app.route('/hire_crew_member', methods=['POST'])
def hire_crew_member():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "User not logged in."}), 401

    crew_member_id = request.json.get('crew_member_id')
    crew_member = CrewMember.query.get(crew_member_id)

    if not crew_member:
        return jsonify({"success": False, "error": "Crew member not found."}), 404

    user = User.query.get(session['user_id'])

    cart_item = CartItem.query.filter_by(user_id=user.id, crew_member_id=crew_member_id).first()
    if cart_item:
        cart_item.quantity += 1
    else:
        cart_item = CartItem(user_id=user.id, crew_member_id=crew_member_id, quantity=1)
        db.session.add(cart_item)

    db.session.commit()

    return jsonify({"success": True})


@app.route('/unhire_crew_member/<int:crew_member_id>')
def unhire_crew_member(crew_member_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    cart_item = CartItem.query.filter_by(user_id=user.id, crew_member_id=crew_member_id).first()

    if cart_item:
        db.session.delete(cart_item)
        db.session.commit()
        flash("Crew member removed from the cart.", "success")
    else:
        flash("Crew member not found in the cart.", "danger")

    return redirect(url_for('cart'))



@app.route('/crew_member_profile/<int:crew_member_id>', methods=['GET', 'POST'])
def crew_member_profile(crew_member_id):
    if request.method == 'POST':
        crew_member = db.session.get(CrewMember, crew_member_id)
        if crew_member:
            name = request.form.get('name')
            if name:
                crew_member.name = name
                crew_member.description = request.form.get('description')
                crew_member.hourly_fee = float(request.form.get('hourly_fee', 0.0))
                crew_member.profile_picture = request.form.get('profile_picture')
                crew_member.star_rating = float(request.form.get('star_rating', 0.0))
                crew_member.available = 'available' in request.form
                db.session.commit()
                flash("Crew member information updated successfully.", "success")
            else:
                flash("Name is required.", "danger")
            return redirect(url_for('crew_member_profile', crew_member_id=crew_member.id))
        else:
            flash("Crew member not found.", "danger")
            return redirect(url_for('index'))
    else:
        crew_member = CrewMember.query.get(crew_member_id)
        if crew_member:
            reviews = Review.query.filter_by(crew_member_id=crew_member_id).all()
            chat_messages = ChatMessage.query.filter_by(crew_member_id=crew_member_id).order_by(ChatMessage.timestamp).all()
            return render_template('crew_member_profile.html', crew_member=crew_member, reviews=reviews, chat_messages=chat_messages)
        else:
            flash("Crew member not found.", "danger")
            return redirect(url_for('index'))



@app.route('/edit_crew_member/<int:crew_member_id>', methods=['GET', 'POST'])
def edit_crew_member(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member or session.get('user_id') != crew_member.user_id:
        flash("Access denied.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        crew_member.name = request.form['name']
        crew_member.description = request.form['description']
        crew_member.hourly_fee = float(request.form['hourly_fee'])
        crew_member.profile_picture = request.form['profile_picture']
        crew_member.star_rating = float(request.form['star_rating'])
        crew_member.available = 'available' in request.form

        db.session.commit()
        flash("Crew member information updated successfully.", "success")
        return redirect(url_for('crew_member_profile', crew_member_id=crew_member.id))

    return render_template('edit_crew_member.html', crew_member=crew_member)


@app.route('/delete_crew_member/<int:crew_member_id>')
def delete_crew_member(crew_member_id):
    crew_member = CrewMember.query.get(crew_member_id)
    if not crew_member or session.get('user_id') != crew_member.user_id:
        flash("Access denied.", "danger")
        return redirect(url_for('index'))

    db.session.delete(crew_member)
    db.session.commit()
    flash("Crew member deleted successfully.", "success")
    return redirect(url_for('index'))


@app.route('/edit_user', methods=['GET', 'POST'])
def edit_user():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        user.first_name = request.form['first_name']
        user.last_name = request.form['last_name']
        user.email = request.form['email']
        user.user_profile.bio = request.form['bio']
        user.user_profile.profile_picture = request.form['profile_picture']
        user.user_profile.location = request.form['location']
        user.user_profile.phone_number = request.form['phone_number']

        db.session.commit()

        flash('User information updated successfully!', 'success')
        return redirect(url_for('index'))
    else:
        return render_template('edit_user.html', current_user=user)


@app.route('/submit_review/<int:crew_member_id>', methods=['POST'])
def submit_review(crew_member_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    text = request.form['text']
    rating = int(request.form['rating'])
    review = Review(user_id=session['user_id'], crew_member_id=crew_member_id, text=text, rating=rating)
    db.session.add(review)
    db.session.commit()
    flash('Review submitted successfully!', 'success')
    return redirect(url_for('crew_member_profile', crew_member_id=crew_member_id))


@app.route('/about')
def about():
    return render_template('about.html')


@socketio.on('message')
def handle_message(data):
    user_id = data['user_id']
    crew_member_id = data['crew_member_id']
    content = data['content']
    timestamp = datetime.utcnow()
    user = User.query.get(user_id)
    username = user.username if user else ''

    # Save the message in the database
    new_message = ChatMessage(user_id=user_id, crew_member_id=crew_member_id, content=content, timestamp=timestamp)
    db.session.add(new_message)
    db.session.commit()

    # Emit the message back to the client with additional data
    data['username'] = username
    data['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
    emit('message', data, room=data['room'])





@app.route('/chat_with_crew_member/<int:crew_member_id>', methods=['GET', 'POST'])
def chat_with_crew_member(crew_member_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    crew_member = CrewMember.query.filter_by(id=crew_member_id, user_id=user_id).first()

    if not crew_member:
        flash("Access denied.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            # Save the message to the database
            chat = ChatMessage(user_id=user_id, crew_member_id=crew_member_id, content=content)
            db.session.add(chat)
            db.session.commit()

            # Get the username
            user = User.query.get(user_id)
            username = user.username if user else ''

            # Include the username in the data object
            data = {'user_id': user_id, 'crew_member_id': crew_member_id, 'content': content, 'username': username}
            socketio.emit('message', data, room=str(crew_member_id))

    chat_messages = ChatMessage.query.filter_by(user_id=user_id, crew_member_id=crew_member_id).all()
    return render_template('crew_member_profile.html', crew_member=crew_member, chat_messages=chat_messages)


@app.route('/get_current_user')
def get_current_user():
    if 'username' in session:
        return jsonify(username=session['username'])
    else:
        return jsonify(error='Not logged in'), 401



if __name__ == '__main__':
    socketio.run(app, debug=True)
