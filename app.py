import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.parse as urlparse
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'antigravity_secret_key')
DATABASE = 'database.db'

class DBWrapper:
    def __init__(self, conn, is_postgres):
        self.conn = conn
        self.is_postgres = is_postgres

    def execute(self, query, params=None):
        cursor = self.conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else self.conn.cursor()
        query = query.replace('?', '%s') if self.is_postgres else query
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor

    def commit(self): self.conn.commit()
    def close(self): self.conn.close()

def get_db():
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        # PostgreSQL Connection with SSL and Timeout for Vercel
        conn = psycopg2.connect(db_url, sslmode='require', connect_timeout=5)
        return DBWrapper(conn, True)
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return DBWrapper(conn, False)

def init_db():
    # Only run locally
    if not os.environ.get('DATABASE_URL') and not os.path.exists(DATABASE):
        db = get_db()
        with open('schema.sql', mode='r') as f:
            # Note: executescript is SQLite only, we use the SQL editor for Supabase
            db.conn.cursor().executescript(f.read())
        db.commit()
        db.close()

@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
    return dict(current_user=user)

def admin_required(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
        if not user or not user['is_admin']:
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@app.route('/')
def index():
    db = get_db()
    quizzes = db.execute('SELECT * FROM quizzes WHERE is_public = 1 ORDER BY created_at DESC').fetchall()
    db.close()
    return render_template('index.html', quizzes=quizzes)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name, email, mobile, inst, password = request.form['name'], request.form['email'], request.form['mobile'], request.form['institution'], request.form['password']
        # Secret: the first user or email 'admin@microbio.com' becomes admin
        is_admin = 1 if email.lower() == 'admin@quizforge.com' else 0
        
        hashed_pw = generate_password_hash(password)
        db = get_db()
        try:
            db.execute('INSERT INTO users (name, email, mobile, institution, password, is_admin) VALUES (?, ?, ?, ?, ?, ?)', 
                       (name, email, mobile, inst, hashed_pw, is_admin))
            db.commit()
            flash('Account created successfully!', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError: flash('Email registered.', 'danger')
        finally: db.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email, password = request.form['email'], request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        db.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['name']
            session['is_admin'] = bool(user['is_admin'])
            return redirect(url_for('index'))
        flash('Invalid login.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST' and 'update_profile' in request.form:
        name, email, mobile, inst = request.form['name'], request.form['email'], request.form['mobile'], request.form['institution']
        try:
            db.execute('UPDATE users SET name=?, email=?, mobile=?, institution=? WHERE id=?', (name, email, mobile, inst, session['user_id']))
            db.commit()
            session['username'] = name
            flash('Profile updated!', 'success')
        except sqlite3.IntegrityError: flash('Email in use.', 'danger')
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Quiz Search
    search = request.args.get('search', '').strip()
    if search:
        my_quizzes = db.execute('SELECT * FROM quizzes WHERE creator_id = ? AND (title LIKE ? OR id LIKE ?) ORDER BY created_at DESC', 
                                (session['user_id'], f'%{search}%', f'%{search}%')).fetchall()
    else:
        my_quizzes = db.execute('SELECT * FROM quizzes WHERE creator_id = ? ORDER BY created_at DESC', (session['user_id'],)).fetchall()
        
    db.close()
    return render_template('profile.html', user=user, quizzes=my_quizzes)

@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    
    # User Search
    user_search = request.args.get('user_search', '').strip()
    if user_search:
        users = db.execute('SELECT * FROM users WHERE name LIKE ? OR email LIKE ? OR institution LIKE ?', 
                           (f'%{user_search}%', f'%{user_search}%', f'%{user_search}%')).fetchall()
    else:
        users = db.execute('SELECT * FROM users').fetchall()
    
    # Quiz Search
    quiz_search = request.args.get('quiz_search', '').strip()
    if quiz_search:
        quizzes = db.execute('''
            SELECT q.*, u.name as creator 
            FROM quizzes q 
            JOIN users u ON q.creator_id = u.id 
            WHERE q.title LIKE ? OR q.id LIKE ? OR u.name LIKE ?
        ''', (f'%{quiz_search}%', f'%{quiz_search}%', f'%{quiz_search}%')).fetchall()
    else:
        quizzes = db.execute('SELECT q.*, u.name as creator FROM quizzes q JOIN users u ON q.creator_id = u.id').fetchall()
        
    attempts = db.execute('SELECT * FROM quiz_attempts ORDER BY attempt_date DESC LIMIT 50').fetchall()
    db.close()
    return render_template('admin.html', users=users, quizzes=quizzes, attempts=attempts)

@app.route('/admin/delete_user/<int:user_id>')
@admin_required
def delete_user(user_id):
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    db.close()
    flash('User deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_quiz/<quiz_id>')
@admin_required
def delete_quiz(quiz_id):
    db = get_db()
    db.execute('DELETE FROM questions WHERE quiz_id = ?', (quiz_id,))
    db.execute('DELETE FROM quizzes WHERE id = ?', (quiz_id,))
    db.commit()
    db.close()
    flash('Quiz deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/toggle_visibility/<quiz_id>')
def toggle_visibility(quiz_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    quiz = db.execute('SELECT * FROM quizzes WHERE id = ?', (quiz_id,)).fetchone()
    if quiz and (quiz['creator_id'] == session['user_id'] or session.get('is_admin')):
        new_status = 1 if quiz['is_public'] == 0 else 0
        db.execute('UPDATE quizzes SET is_public = ? WHERE id = ?', (new_status, quiz_id))
        db.commit()
    db.close()
    return redirect(request.referrer or url_for('profile'))

@app.route('/create_quiz', methods=['GET', 'POST'])
def create_quiz():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        title, q_id = request.form['title'], str(uuid.uuid4())[:8]
        db = get_db()
        db.execute('INSERT INTO quizzes (id, title, creator_id) VALUES (?, ?, ?)', (q_id, title, session['user_id']))
        db.commit()
        db.close()
        return redirect(url_for('add_question', quiz_id=q_id))
    return render_template('create_quiz.html')

@app.route('/add_question/<quiz_id>', methods=['GET', 'POST'])
def add_question(quiz_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    quiz = db.execute('SELECT * FROM quizzes WHERE id = ?', (quiz_id,)).fetchone()
    if not quiz or (quiz['creator_id'] != session['user_id'] and not session.get('is_admin')): return "Unauthorized", 403
    if request.method == 'POST':
        db.execute('INSERT INTO questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option) VALUES (?,?,?,?,?,?,?)',
                   (quiz_id, request.form['question_text'], request.form['option_a'], request.form['option_b'], 
                    request.form['option_c'], request.form['option_d'], request.form['correct_option']))
        db.commit()
        if 'finish' in request.form:
            db.close()
            return redirect(url_for('quiz_created', quiz_id=quiz_id))
    current_questions = db.execute('SELECT * FROM questions WHERE quiz_id = ?', (quiz_id,)).fetchall()
    db.close()
    return render_template('add_question.html', quiz=quiz, questions=current_questions)

@app.route('/quiz_created/<quiz_id>')
def quiz_created(quiz_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    quiz = db.execute('SELECT * FROM quizzes WHERE id = ?', (quiz_id,)).fetchone()
    db.close()
    quiz_url = request.url_root + 'quiz/' + quiz_id
    return render_template('quiz_created.html', quiz=quiz, quiz_url=quiz_url)

@app.route('/quiz_results/<quiz_id>')
def quiz_results(quiz_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    
    # Verify authorization
    user = db.execute('SELECT is_admin FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    quiz = db.execute('SELECT * FROM quizzes WHERE id = ?', (quiz_id,)).fetchone()
    
    is_admin = user and user['is_admin']
    is_creator = quiz and quiz['creator_id'] == session['user_id']

    if not quiz or (not is_creator and not is_admin): 
        db.close()
        return "Unauthorized", 403
    
    # Get all unique institutions for filters
    institutions = db.execute('SELECT DISTINCT participant_institution FROM quiz_attempts WHERE quiz_id = ?', (quiz_id,)).fetchall()
    institutions = [r['participant_institution'] for r in institutions if r['participant_institution']]

    query = "SELECT * FROM quiz_attempts WHERE quiz_id = ? "
    params = [quiz_id]
    
    # Search Filter
    search = request.args.get('search')
    if search:
        query += "AND (participant_name LIKE ? OR participant_email LIKE ? OR participant_institution LIKE ? OR participant_mobile LIKE ?) "
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%'])
    
    # Institution Filter
    inst = request.args.get('institution')
    if inst:
        query += "AND participant_institution = ? "
        params.append(inst)
    
    # Score Filter
    score_f = request.args.get('score_filter')
    if score_f == 'passed':
        query += "AND total > 0 AND (CAST(score AS FLOAT) / total) >= 0.8 "
    elif score_f == 'average':
        query += "AND total > 0 AND (CAST(score AS FLOAT) / total) >= 0.5 AND (CAST(score AS FLOAT) / total) < 0.8 "
    elif score_f == 'failed':
        query += "AND total > 0 AND (CAST(score AS FLOAT) / total) < 0.5 "

    # Date Filter
    date_f = request.args.get('date_filter')
    if date_f == 'today':
        query += "AND attempt_date::date = CURRENT_DATE " if db.is_postgres else "AND date(attempt_date) = date('now') "
    elif date_f == 'last_7_days':
        query += "AND attempt_date >= CURRENT_DATE - INTERVAL '7 days' " if db.is_postgres else "AND attempt_date >= date('now', '-7 days') "
    elif date_f == 'this_month':
        query += "AND attempt_date >= date_trunc('month', CURRENT_DATE) " if db.is_postgres else "AND attempt_date >= date('now', 'start of month') "

    # Sorting
    sort = request.args.get('sort', 'date_desc')
    if sort == 'score_desc': query += "ORDER BY score DESC"
    elif sort == 'score_asc': query += "ORDER BY score ASC"
    elif sort == 'date_asc': query += "ORDER BY attempt_date ASC"
    else: query += "ORDER BY attempt_date DESC"
    
    attempts = db.execute(query, params).fetchall()
    db.close()
    return render_template('quiz_analytics.html', quiz=quiz, attempts=attempts, institutions=institutions)

@app.route('/find_quiz', methods=['GET', 'POST'])
def find_quiz():
    if request.method == 'POST':
        quiz_id = request.form['quiz_id'].strip()
        db = get_db()
        quiz = db.execute('SELECT * FROM quizzes WHERE id = ?', (quiz_id,)).fetchone()
        db.close()
        if quiz: return redirect(url_for('quiz', quiz_id=quiz_id))
        flash('Quiz ID not found.', 'danger')
    return render_template('find_quiz.html')

@app.route('/quiz/<quiz_id>')
def quiz(quiz_id):
    db = get_db()
    quiz = db.execute('SELECT * FROM quizzes WHERE id = ?', (quiz_id,)).fetchone()
    questions = db.execute('SELECT * FROM questions WHERE quiz_id = ?', (quiz_id,)).fetchall()
    db.close()
    if not quiz: return "Quiz not found", 404
    return render_template('quiz.html', quiz=quiz, questions=questions)

@app.route('/submit_quiz/<quiz_id>', methods=['POST'])
def submit_quiz(quiz_id):
    db = get_db()
    if 'user_id' in session:
        user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        p_name, p_email, p_mobile, p_inst, u_id = user['name'], user['email'], user['mobile'], user['institution'], user['id']
    else:
        p_name, p_email, p_mobile, p_inst, u_id = request.form.get('p_name'), request.form.get('p_email'), request.form.get('p_mobile'), request.form.get('p_institution'), None
        if not all([p_name, p_email, p_mobile, p_inst]):
            flash('All details required.', 'warning')
            return redirect(url_for('quiz', quiz_id=quiz_id))
    quiz_questions = db.execute('SELECT * FROM questions WHERE quiz_id = ?', (quiz_id,)).fetchall()
    score, total, results = 0, len(quiz_questions), []
    for q in quiz_questions:
        ans = request.form.get(f'q_{q["id"]}')
        correct = (ans == q['correct_option'])
        if correct: score += 1
        results.append({'question': q['question_text'], 'user_answer': ans or "Not Answered", 'correct_answer': q['correct_option'], 'correct_text': q[f'option_{q["correct_option"].lower()}'], 'is_correct': correct})
    db.execute('INSERT INTO quiz_attempts (quiz_id, user_id, participant_name, participant_email, participant_mobile, participant_institution, score, total) VALUES (?,?,?,?,?,?,?,?)', (quiz_id, u_id, p_name, p_email, p_mobile, p_inst, score, total))
    db.commit()
    db.close()
    return render_template('results.html', score=score, total=total, results=results, quiz_id=quiz_id)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
