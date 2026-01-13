-- English Learning App - Supabase Schema
-- V1: Writing exercises only

-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    is_super_admin BOOLEAN DEFAULT FALSE,
    current_level VARCHAR(10) DEFAULT 'A2', -- A1, A2, B1, B2, C1, C2
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Exercise templates (görev havuzu)
CREATE TABLE exercises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(20) NOT NULL DEFAULT 'writing', -- writing, speaking, reading, listening
    level VARCHAR(10) NOT NULL, -- A1, A2, B1, B2
    title VARCHAR(255) NOT NULL,
    instructions TEXT NOT NULL,
    word_count_min INT DEFAULT 50,
    word_count_max INT DEFAULT 150,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User submissions (yüklenen ödevler)
CREATE TABLE submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    exercise_id UUID REFERENCES exercises(id) ON DELETE SET NULL,
    file_url TEXT, -- Supabase storage URL
    file_type VARCHAR(20), -- docx, jpg, png, pdf
    extracted_text TEXT, -- AI tarafından çıkarılan metin
    status VARCHAR(20) DEFAULT 'pending', -- pending, evaluated, error
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- AI evaluations
CREATE TABLE evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
    grammar_score INT CHECK (grammar_score >= 0 AND grammar_score <= 10),
    vocabulary_score INT CHECK (vocabulary_score >= 0 AND vocabulary_score <= 10),
    task_completion_score INT CHECK (task_completion_score >= 0 AND task_completion_score <= 10),
    coherence_score INT CHECK (coherence_score >= 0 AND coherence_score <= 10),
    overall_score INT CHECK (overall_score >= 0 AND overall_score <= 10),
    estimated_level VARCHAR(10), -- A1, A2, B1, B2
    feedback_text TEXT, -- Detaylı geri bildirim
    errors_json JSONB, -- Hata listesi [{error, correction, explanation}]
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- System settings (prompts, API keys reference)
CREATE TABLE settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description VARCHAR(255),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User progress tracking
CREATE TABLE user_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    total_exercises INT DEFAULT 0,
    average_score DECIMAL(4,2) DEFAULT 0,
    level_assessments_done INT DEFAULT 0, -- İlk 3 egzersiz için
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Indexes
CREATE INDEX idx_submissions_user ON submissions(user_id);
CREATE INDEX idx_submissions_status ON submissions(status);
CREATE INDEX idx_exercises_level_type ON exercises(level, type);
CREATE INDEX idx_evaluations_submission ON evaluations(submission_id);

-- Initial super admin (şifre: admin123 - deployment'ta değiştir)
-- Password hash için: python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('admin123'))"
INSERT INTO users (email, name, is_super_admin, current_level) 
VALUES ('admin@example.com', 'Super Admin', TRUE, 'B1');

-- Initial settings (prompts)
INSERT INTO settings (key, value, description) VALUES 
('writing_evaluator_prompt', 
'Sen deneyimli bir İngilizce öğretmenisin. A2-B1 seviyesindeki Türk öğrencilere yardım ediyorsun.

Öğrencinin yazısını değerlendir ve şu formatta JSON döndür:
{
  "grammar_score": 0-10,
  "vocabulary_score": 0-10,
  "task_completion_score": 0-10,
  "coherence_score": 0-10,
  "overall_score": 0-10,
  "estimated_level": "A1/A2/B1/B2",
  "feedback": "Türkçe samimi geri bildirim",
  "errors": [
    {"error": "hatalı ifade", "correction": "doğrusu", "explanation": "Türkçe açıklama"}
  ]
}

Değerlendirme kriterleri:
- Grammar: Dilbilgisi doğruluğu
- Vocabulary: Kelime çeşitliliği ve uygunluğu
- Task Completion: Göreve uygunluk
- Coherence: Akış ve tutarlılık

Samimi, motive edici ol. Hataları nazikçe belirt.', 
'Writing değerlendirme promptu'),

('level_detection_prompt',
'Öğrencinin son 3 yazılı çalışmasına dayanarak genel İngilizce seviyesini belirle.

Seviye kriterleri:
- A1: Çok basit cümleler, temel kelimeler
- A2: Basit cümleler, günlük konular, temel bağlaçlar
- B1: Bileşik cümleler, görüş belirtme, çeşitli zamanlar
- B2: Karmaşık yapılar, soyut konular, geniş kelime hazinesi

JSON döndür: {"level": "A2", "confidence": "high/medium/low", "explanation": "Türkçe açıklama"}',
'Seviye belirleme promptu');

-- Storage bucket için Supabase Dashboard'dan oluştur: submissions
