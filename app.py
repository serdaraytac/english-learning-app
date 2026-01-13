import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from supabase import create_client, Client
from functools import wraps
import anthropic
import base64
import json
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

# Supabase setup
supabase: Client = create_client(
    os.environ.get('SUPABASE_URL', ''),
    os.environ.get('SUPABASE_KEY', '')
)

# Anthropic setup
claude_client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))

ALLOWED_EXTENSIONS = {'docx', 'doc', 'pdf', 'jpg', 'jpeg', 'png'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Auth decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Lütfen giriş yapın.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not session.get('is_super_admin'):
            flash('Bu sayfaya erişim yetkiniz yok.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ============ AUTH ROUTES ============

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')
        
        supabase.table('users').insert({
            'email': email,
            'name': name,
            'password_hash': generate_password_hash(password),
            'is_super_admin': True,
            'current_level': 'B1'
        }).execute()
        flash('Kayıt başarılı, giriş yapabilirsin.', 'success')
        return redirect(url_for('login'))
    return render_template('login.html')
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        result = supabase.table('users').select('*').eq('email', email).execute()
        
        if result.data and check_password_hash(result.data[0]['password_hash'], password):
            user = result.data[0]
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['is_super_admin'] = user['is_super_admin']
            session['current_level'] = user['current_level']
            return redirect(url_for('dashboard'))
        
        flash('Email veya şifre hatalı.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============ USER ROUTES ============

@app.route('/dashboard')
@login_required
def dashboard():
    # Kullanıcının son submissions
    submissions = supabase.table('submissions')\
        .select('*, evaluations(*), exercises(*)')\
        .eq('user_id', session['user_id'])\
        .order('created_at', desc=True)\
        .limit(5)\
        .execute()
    
    # Progress bilgisi
    progress = supabase.table('user_progress')\
        .select('*')\
        .eq('user_id', session['user_id'])\
        .execute()
    
    progress_data = progress.data[0] if progress.data else {
        'total_exercises': 0, 'average_score': 0, 'level_assessments_done': 0
    }
    
    return render_template('dashboard.html', 
                         submissions=submissions.data,
                         progress=progress_data)

@app.route('/exercises')
@login_required
def exercises():
    level = session.get('current_level', 'A2')
    # Kullanıcının seviyesine uygun veya bir alt seviye
    levels = ['A1', 'A2'] if level == 'A2' else ['A2', 'B1'] if level == 'B1' else [level]
    
    exercises = supabase.table('exercises')\
        .select('*')\
        .eq('type', 'writing')\
        .eq('is_active', True)\
        .in_('level', levels)\
        .execute()
    
    return render_template('exercises.html', exercises=exercises.data)

@app.route('/exercise/<exercise_id>', methods=['GET', 'POST'])
@login_required
def exercise_detail(exercise_id):
    exercise = supabase.table('exercises').select('*').eq('id', exercise_id).single().execute()
    
    if not exercise.data:
        flash('Egzersiz bulunamadı.', 'error')
        return redirect(url_for('exercises'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Dosya seçilmedi.', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('Dosya seçilmedi.', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            storage_path = f"{session['user_id']}/{timestamp}_{filename}"
            
            # Supabase Storage'a yükle
            file_content = file.read()
            supabase.storage.from_('submissions').upload(storage_path, file_content)
            
            file_url = supabase.storage.from_('submissions').get_public_url(storage_path)
            file_ext = filename.rsplit('.', 1)[1].lower()
            
            # Submission oluştur
            submission = supabase.table('submissions').insert({
                'user_id': session['user_id'],
                'exercise_id': exercise_id,
                'file_url': file_url,
                'file_type': file_ext,
                'status': 'pending'
            }).execute()
            
            # AI değerlendirmesi başlat
            evaluate_submission(submission.data[0]['id'], file_content, file_ext, exercise.data)
            
            flash('Ödeviniz yüklendi ve değerlendiriliyor!', 'success')
            return redirect(url_for('submission_result', submission_id=submission.data[0]['id']))
        
        flash('Geçersiz dosya formatı.', 'error')
    
    return render_template('exercise_detail.html', exercise=exercise.data)

@app.route('/submission/<submission_id>')
@login_required
def submission_result(submission_id):
    submission = supabase.table('submissions')\
        .select('*, evaluations(*), exercises(*)')\
        .eq('id', submission_id)\
        .eq('user_id', session['user_id'])\
        .single()\
        .execute()
    
    if not submission.data:
        flash('Sonuç bulunamadı.', 'error')
        return redirect(url_for('dashboard'))
    
    return render_template('submission_result.html', submission=submission.data)

@app.route('/my-submissions')
@login_required
def my_submissions():
    submissions = supabase.table('submissions')\
        .select('*, evaluations(*), exercises(*)')\
        .eq('user_id', session['user_id'])\
        .order('created_at', desc=True)\
        .execute()
    
    return render_template('my_submissions.html', submissions=submissions.data)

# ============ AI EVALUATION ============

def evaluate_submission(submission_id, file_content, file_type, exercise):
    """Claude API ile değerlendirme yap"""
    try:
        # Prompt'u DB'den al
        prompt_result = supabase.table('settings')\
            .select('value')\
            .eq('key', 'writing_evaluator_prompt')\
            .single()\
            .execute()
        
        system_prompt = prompt_result.data['value'] if prompt_result.data else "Değerlendir."
        
        # Dosya tipine göre içerik hazırla
        if file_type in ['jpg', 'jpeg', 'png']:
            # Görsel - Claude Vision kullan
            base64_image = base64.b64encode(file_content).decode('utf-8')
            media_type = f"image/{file_type}" if file_type != 'jpg' else "image/jpeg"
            
            message = claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_image
                            }
                        },
                        {
                            "type": "text",
                            "text": f"Görev: {exercise['title']}\nTalimat: {exercise['instructions']}\nBeklenen kelime sayısı: {exercise['word_count_min']}-{exercise['word_count_max']}\n\nYukarıdaki el yazısını oku ve değerlendir."
                        }
                    ]
                }]
            )
        else:
            # Word/PDF - text çıkar (basit yaklaşım, ileride geliştirilebilir)
            # Şimdilik sadece görsel desteği
            message = claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"Görev: {exercise['title']}\nTalimat: {exercise['instructions']}\n\nNot: Word/PDF dosyası yüklendi. Lütfen kullanıcıya fotoğraf olarak yüklemesini önerin."
                }]
            )
        
        # Response'u parse et
        response_text = message.content[0].text
        
        # JSON bul ve parse et
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                eval_data = json.loads(response_text[json_start:json_end])
            else:
                raise ValueError("JSON bulunamadı")
        except:
            eval_data = {
                "grammar_score": 5, "vocabulary_score": 5, "task_completion_score": 5,
                "coherence_score": 5, "overall_score": 5, "estimated_level": "A2",
                "feedback": response_text, "errors": []
            }
        
        # Evaluation kaydet
        supabase.table('evaluations').insert({
            'submission_id': submission_id,
            'grammar_score': eval_data.get('grammar_score', 5),
            'vocabulary_score': eval_data.get('vocabulary_score', 5),
            'task_completion_score': eval_data.get('task_completion_score', 5),
            'coherence_score': eval_data.get('coherence_score', 5),
            'overall_score': eval_data.get('overall_score', 5),
            'estimated_level': eval_data.get('estimated_level', 'A2'),
            'feedback_text': eval_data.get('feedback', ''),
            'errors_json': eval_data.get('errors', [])
        }).execute()
        
        # Submission durumunu güncelle
        supabase.table('submissions').update({'status': 'evaluated'}).eq('id', submission_id).execute()
        
        # User progress güncelle
        update_user_progress(submission_id)
        
    except Exception as e:
        print(f"Evaluation error: {e}")
        supabase.table('submissions').update({'status': 'error'}).eq('id', submission_id).execute()

def update_user_progress(submission_id):
    """Kullanıcının progress'ini güncelle"""
    submission = supabase.table('submissions').select('user_id').eq('id', submission_id).single().execute()
    user_id = submission.data['user_id']
    
    # Tüm evaluations
    evals = supabase.table('evaluations')\
        .select('overall_score, submissions!inner(user_id)')\
        .eq('submissions.user_id', user_id)\
        .execute()
    
    total = len(evals.data)
    avg_score = sum(e['overall_score'] for e in evals.data) / total if total > 0 else 0
    
    # Upsert progress
    supabase.table('user_progress').upsert({
        'user_id': user_id,
        'total_exercises': total,
        'average_score': round(avg_score, 2),
        'level_assessments_done': min(total, 3),
        'last_activity': datetime.now().isoformat()
    }, on_conflict='user_id').execute()
    
    # İlk 3 egzersizden sonra seviye güncelle
    if total == 3:
        detect_and_update_level(user_id)

def detect_and_update_level(user_id):
    """İlk 3 egzersizden sonra seviye belirle"""
    evals = supabase.table('evaluations')\
        .select('estimated_level, submissions!inner(user_id)')\
        .eq('submissions.user_id', user_id)\
        .limit(3)\
        .execute()
    
    if len(evals.data) >= 3:
        levels = [e['estimated_level'] for e in evals.data]
        # En çok tekrar eden seviye
        from collections import Counter
        most_common = Counter(levels).most_common(1)[0][0]
        supabase.table('users').update({'current_level': most_common}).eq('id', user_id).execute()

# ============ ADMIN ROUTES ============

@app.route('/admin')
@admin_required
def admin_dashboard():
    users = supabase.table('users').select('*').execute()
    exercises = supabase.table('exercises').select('*').execute()
    return render_template('admin/dashboard.html', users=users.data, exercises=exercises.data)

@app.route('/admin/users', methods=['GET', 'POST'])
@admin_required
def admin_users():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')
        level = request.form.get('level', 'A2')
        
        supabase.table('users').insert({
            'email': email,
            'name': name,
            'password_hash': generate_password_hash(password),
            'current_level': level,
            'is_super_admin': False
        }).execute()
        flash(f'{name} kullanıcısı oluşturuldu.', 'success')
    
    users = supabase.table('users').select('*').order('created_at', desc=True).execute()
    return render_template('admin/users.html', users=users.data)

@app.route('/admin/users/delete/<user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    supabase.table('users').delete().eq('id', user_id).execute()
    flash('Kullanıcı silindi.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/exercises', methods=['GET', 'POST'])
@admin_required
def admin_exercises():
    if request.method == 'POST':
        supabase.table('exercises').insert({
            'type': 'writing',
            'level': request.form.get('level'),
            'title': request.form.get('title'),
            'instructions': request.form.get('instructions'),
            'word_count_min': int(request.form.get('word_count_min', 50)),
            'word_count_max': int(request.form.get('word_count_max', 150))
        }).execute()
        flash('Egzersiz oluşturuldu.', 'success')
    
    exercises = supabase.table('exercises').select('*').order('level').execute()
    return render_template('admin/exercises.html', exercises=exercises.data)

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        for key in request.form:
            if key.startswith('setting_'):
                setting_key = key.replace('setting_', '')
                supabase.table('settings').update({
                    'value': request.form.get(key),
                    'updated_at': datetime.now().isoformat()
                }).eq('key', setting_key).execute()
        flash('Ayarlar güncellendi.', 'success')
    
    settings = supabase.table('settings').select('*').execute()
    return render_template('admin/settings.html', settings=settings.data)

if __name__ == '__main__':
    app.run(debug=True)
