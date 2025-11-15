# 🎙️ Human-in-the-Loop AI Supervisor

An intelligent voice agent system for Glamour Salon that escalates complex questions to human supervisors in real-time.

## 🌟 Features

- **Voice AI Agent**: Answers customer questions via LiveKit voice calls
- **Knowledge Base**: Auto-responds to common questions (hours, pricing, services)
- **Smart Escalation**: Routes complex questions to human supervisors
- **Real-time Callbacks**: Delivers supervisor answers during active calls
- **Web Dashboard**: Supervisor interface to answer escalated questions
- **Learning System**: Adds supervisor answers to knowledge base automatically

---

## 📋 Prerequisites

- Python 3.10+
- FFmpeg installed on your system
- LiveKit account ([cloud.livekit.io](https://cloud.livekit.io))
- Groq API key ([console.groq.com](https://console.groq.com))

---

## 🚀 Quick Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
# LiveKit Configuration
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret

# Groq API (for STT, LLM, TTS)
GROQ_API_KEY=your_groq_api_key
```

### 3. Install FFmpeg

**Windows:**
- Download from [ffmpeg.org](https://ffmpeg.org/download.html)
- Extract to `C:\ffmpeg\`
- Update path in `voice_agent.py` if needed

**Mac/Linux:**
```bash
# Mac
brew install ffmpeg

# Linux
sudo apt install ffmpeg
```

### 4. Start the System

**Terminal 1 - Voice Agent:**
```bash
python final_solution.py
```

**Terminal 2 - Supervisor Dashboard:**
```bash
python web/dashboard.py
```

**Access Dashboard:** http://localhost:5000

---

## 🎯 How It Works

### Call Flow

```
1. Customer calls → Agent answers with welcome message
2. Customer asks: "What are your hours?"
   → Agent responds instantly from knowledge base ✅

3. Customer asks: "Is Sarah available Friday?"
   → Agent: "Let me check with my supervisor..." 🔺
   → Question appears in supervisor dashboard
   
4. Supervisor answers in dashboard
   → Answer added to knowledge base
   → If customer still on call: Agent delivers answer immediately
   → SMS notification sent (simulated in console)

5. Next caller asks same question
   → Agent now knows the answer! ✅
```

### Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Customer  │◄───────►│  Voice Agent │◄───────►│  Groq API   │
│   (Phone)   │ LiveKit │  (Python)    │         │  (STT/TTS)  │
└─────────────┘         └──────┬───────┘         └─────────────┘
                               │
                               │ Escalates
                               ▼
                        ┌──────────────┐
                        │   Database   │
                        │   (SQLite)   │
                        └──────┬───────┘
                               │
                               │ Polls
                               ▼
                        ┌──────────────┐
                        │  Supervisor  │
                        │  Dashboard   │
                        │   (Flask)    │
                        └──────────────┘
```

---

## 📁 Project Structure

```
Human-in-the-Loop AI Supervisor/
├── agent/
│   └── voice_agent.py          # Main agent logic
├── database/
│   └── db.py                   # SQLite database
├── web/
│   └── dashboard.py            # Flask supervisor UI
├── supervisor/
│   └── templates/              # HTML templates
├── config.py                   # Configuration
├── final_solution.py           # Agent entry point
├── requirements.txt            # Dependencies
├── .env                        # Environment variables
└── README.md                   # This file
```

---

## 🧠 Design Decisions

### 1. **Why Groq Instead of OpenAI?**
- **Faster**: Whisper transcription is 10x faster
- **Cheaper**: More cost-effective for voice processing
- **Better TTS**: PlayAI voices sound natural

### 2. **Why SQLite?**
- **Simple**: No database server needed
- **Fast**: Perfect for single-instance deployment
- **Portable**: Database is a single file

### 3. **Why LiveKit?**
- **Real-time**: Sub-second latency for voice
- **Scalable**: Can handle many concurrent calls
- **Reliable**: Production-grade WebRTC

### 4. **Why Human-in-the-Loop?**
- **Accuracy**: AI isn't perfect, humans catch edge cases
- **Learning**: System gets smarter from supervisor answers
- **Compliance**: Sensitive questions need human oversight

### 5. **Audio Processing Pipeline**
```
User Speech → LiveKit → 16kHz PCM → Groq Whisper → Text
Text → Knowledge Base / LLM → Response Text
Response Text → Groq TTS → MP3 → FFmpeg → PCM → LiveKit → User
```

### 6. **Escalation Strategy**
The agent escalates when:
- Question not in knowledge base
- LLM says "I'm not sure" or "check with supervisor"
- LLM provides potentially wrong information (safety filter)

### 7. **Real-time Callback Mechanism**
- Agent polls database every 2 seconds during call
- When supervisor answers, agent speaks response immediately
- Status changes: `pending` → `resolved` → `delivered`

---

## 🎨 Key Features Explained

### Smart Filtering
The agent ignores:
- **Noise**: "um", "uh", "hello"
- **Too short**: Single words
- **Non-questions**: Statements without question words

### Knowledge Base Matching
Uses 4-tier matching:
1. **Exact match**: Normalized question matches exactly
2. **Substring**: Question contains KB entry or vice versa
3. **Fuzzy**: 80%+ similarity using SequenceMatcher
4. **Keyword overlap**: 2+ common keywords

### Audio Quality
- **Sample rate**: 24kHz for natural voice
- **Format**: PCM for LiveKit, MP3 for API
- **Chunking**: 40ms frames for smooth playback

---

## 🧪 Testing Questions

### Instant Answers (Knowledge Base)
✅ "What are your hours?"
✅ "How much is a haircut?"
✅ "Do you accept walk-ins?"
✅ "Where are you located?"

### Escalated Questions
🔺 "Is Sarah available on Friday?"
🔺 "How much does balayage cost?"
🔺 "Do you offer bridal packages?"
🔺 "What's your refund policy?"

---

## 📊 Database Schema

```sql
-- Customers
CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    phone_number TEXT UNIQUE,
    name TEXT,
    created_at TIMESTAMP
);

-- Help Requests
CREATE TABLE help_requests (
    id TEXT PRIMARY KEY,
    question TEXT,
    caller_id TEXT,
    phone_number TEXT,
    status TEXT,              -- pending/resolved/delivered
    supervisor_answer TEXT,
    created_at TIMESTAMP
);

-- Knowledge Base
CREATE TABLE knowledge_base (
    id INTEGER PRIMARY KEY,
    question TEXT,
    answer TEXT,
    created_at TIMESTAMP
);
```

---

## 🐛 Troubleshooting

### Agent not joining calls
```bash
# Clean up the room
python cleanup_room.py
# Restart agent
python final_solution.py
```

### Audio not playing
- Check FFmpeg is installed: `ffmpeg -version`
- Verify FFmpeg path in `voice_agent.py`
- Check Groq API key is valid

### Questions not escalating
- Check logs for "IGNORED" messages
- Question might be too short or not detected as question
- LLM might be answering confidently (check prompt)

### Dashboard shows wrong stats
- Refresh page (stats update on page load)
- Check database: `sqlite3 salon_ai.db "SELECT status, COUNT(*) FROM help_requests GROUP BY status"`

---

## 🚀 Production Deployment

### Recommended Stack
- **Hosting**: Railway, Heroku, or AWS
- **Database**: PostgreSQL (replace SQLite)
- **Voice**: LiveKit Cloud (already configured)
- **Monitoring**: Sentry for error tracking

### Environment Variables for Production
```env
DATABASE_URL=postgresql://...
LIVEKIT_URL=wss://prod.livekit.cloud
SENTRY_DSN=https://...
```

---

## 📝 License

MIT License - feel free to use for your own projects!

---

## 🤝 Contributing

Pull requests welcome! Areas for improvement:
- Add authentication to dashboard
- Support multiple languages
- Integrate real SMS (Twilio)
- Add analytics dashboard
- Support video calls

---

## 📧 Support

Having issues? Check:
1. Logs in terminal (very detailed)
2. Database: `sqlite3 salon_ai.db`
3. LiveKit dashboard for connection status
4. Groq console for API usage

---

**Built with ❤️ for Glamour Salon**