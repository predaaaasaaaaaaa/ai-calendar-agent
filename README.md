# 🤖 Calendar AI Agent

> A natural language calendar assistant that creates **real** Google Calendar events using AI. Just tell it what you want to schedule in plain English, and watch the magic happen! ✨

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Groq](https://img.shields.io/badge/Powered%20by-Groq-orange.svg)](https://groq.com/)

## ✨ Features

- 🗣️ **Natural Language Processing** - Talk to it like a human
  - "Schedule a team meeting next Tuesday at 2pm for 1 hour"
  - "Book a dentist appointment on Feb 15th at 10am"  
  - "Create a lunch meeting with john@example.com tomorrow at noon"
- 📅 **Real Calendar Integration** - Creates actual Google Calendar events
- 👥 **Smart Participant Handling** - Automatically sends invites when emails are provided
- 🧠 **Intelligent Parsing** - Understands relative dates ("tomorrow", "next Monday")
- ⚡ **Lightning Fast** - Powered by Llama 3.3 70B via Groq
- 🎯 **Gate-Check Validation** - Only creates events when it's confident about your request
- 🔒 **Secure** - Uses OAuth 2.0 for Google Calendar access

## 🎬 How It Works

The agent uses a **3-stage prompt-chaining architecture**:
```
User Input → [Stage 1: Extraction] → [Stage 2: Parsing] → [Stage 3: Creation] → Calendar Event
```

1. **Event Extraction** (Gate Check)
   - Analyzes if input describes a calendar event
   - Calculates confidence score (must be ≥ 0.7)
   - Rejects non-calendar requests

2. **Event Parsing**
   - Extracts: name, date, time, duration, participants, location
   - Handles relative dates using current date context
   - Converts to ISO 8601 format for precision

3. **Event Creation**
   - Creates the actual Google Calendar event via API
   - Sends calendar invites to participants (if emails provided)
   - Returns shareable event link

## 🚀 Installation Guide

### Prerequisites

Before you begin, make sure you have:
- **Python 3.8+** installed ([Download here](https://www.python.org/downloads/))
- A **Google account** with Google Calendar
- A **Groq API key** (free tier available)

---

### Step 1: Clone the Repository
```bash
git clone https://github.com/YOUR_USERNAME/calendar-ai-agent.git
cd calendar-ai-agent
```

---

### Step 2: Set Up Python Environment

**Windows:**
```bash
# Create virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate
```

**Mac/Linux:**
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate
```

You should see `(venv)` at the start of your terminal prompt.

---

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

---

### Step 4: Get Your Groq API Key

1. Go to [Groq Console](https://console.groq.com/)
2. Sign up or log in (it's free!)
3. Navigate to **API Keys** in the sidebar
4. Click **"Create API Key"**
5. Give it a name (e.g., "Calendar Agent")
6. Click **"Submit"**
7. **Copy the API key immediately** (you won't see it again!)

---

### Step 5: Configure Environment Variables

1. Create a `.env` file in the project root:
```bash
   cp .env.example .env
```

2. Open `.env` and add your Groq API key:
```
   GROQ_API_KEY=gsk_your_actual_groq_api_key_here
```

---

### Step 6: Set Up Google Calendar API

This is the most important part! Follow carefully:

#### 6.1 Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown (top left, next to "Google Cloud")
3. Click **"NEW PROJECT"**
4. Project name: `Calendar AI Agent` (or anything you like)
5. Click **"CREATE"**
6. Wait for creation, then **select your new project** from the dropdown

#### 6.2 Enable Google Calendar API

1. In the left sidebar: **APIs & Services** → **Library**
   - Or use this direct link: [API Library](https://console.cloud.google.com/apis/library)
2. Search for: `Google Calendar API`
3. Click on it
4. Click the blue **"ENABLE"** button
5. Wait for "API enabled" confirmation

#### 6.3 Configure OAuth Consent Screen

1. Go to: **APIs & Services** → **OAuth consent screen**
   - Or direct link: [OAuth Consent](https://console.cloud.google.com/apis/credentials/consent)
2. Choose **"External"** user type
3. Click **"CREATE"**
4. Fill in the required fields:
   - **App name:** `Calendar AI Agent`
   - **User support email:** Your email address
   - **Developer contact information:** Your email address
5. Click **"SAVE AND CONTINUE"**
6. On **Scopes** page: Click **"SAVE AND CONTINUE"** (skip for now)
7. On **Test users** page: Click **"+ ADD USERS"**
   - **⚠️ CRITICAL:** Add the **exact email address** you'll use to sign in
   - Click **"ADD"**
   - Click **"SAVE AND CONTINUE"**
8. On **Summary** page: Click **"BACK TO DASHBOARD"**

#### 6.4 Create OAuth Credentials

1. Go to: **APIs & Services** → **Credentials**
   - Or direct link: [Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **"+ CREATE CREDENTIALS"** (top of page)
3. Select **"OAuth client ID"**
4. Application type: **"Desktop app"** ⚠️ (NOT "Web application"!)
5. Name: `Calendar Agent CLI`
6. Click **"CREATE"**
7. A popup appears - click **"DOWNLOAD JSON"**
8. The file downloads as `client_secret_xxxxx.json`

#### 6.5 Add Credentials to Project

1. Rename the downloaded file to **exactly**: `credentials.json`
2. Move it to your project folder:
```
   calendar-ai-agent/
   ├── calendar_agent.py
   ├── credentials.json    ← Put it here!
   ├── .env
   └── ...
```

3. **⚠️ IMPORTANT: Verify the file structure**

   Open `credentials.json` in VS Code or any text editor. The downloaded file might be all on one line. It should look like this:

   **✅ CORRECT structure:**
```json
   {
     "installed": {
       "client_id": "xxxxx.apps.googleusercontent.com",
       "project_id": "calendar-ai-agent",
       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
       "token_uri": "https://oauth2.googleapis.com/token",
       "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
       "client_secret": "GOCSPX-xxxxxxxxxxxxxxxxxxxxx",
       "redirect_uris": ["http://localhost"]
     }
   }
```

   **❌ WRONG - If it says "web" instead of "installed":**
```json
   {
     "web": {
       ...
     }
   }
```
   This means you created **Web application** credentials instead of **Desktop app**. Go back to Step 6.4 and create Desktop app credentials.

   **📝 Note:** If your `credentials.json` is all on one line (like `{"installed":{"client_id":"xxxxx",...}}`), that's okay - it will still work! But formatting it makes it easier to read and verify. In VS Code, you can auto-format it:
   - Open `credentials.json`
   - Press `Shift + Alt + F` (Windows/Linux) or `Shift + Option + F` (Mac)
   - Or right-click → "Format Document"
```

---

### Step 7: Run the Agent! 🎉
```bash
python calendar_agent.py
```

**First-time authentication:**
1. A browser window opens automatically
2. Select your Google account (must be the one you added as a test user!)
3. You'll see: "Google hasn't verified this app" - this is normal!
4. Click **"Continue"** (or "Advanced" → "Go to Calendar AI Agent (unsafe)")
5. Click **"Allow"** to grant calendar access
6. Browser shows: "The authentication flow has completed"
7. Return to your terminal - you're ready to go! ✨

---

## 📚 Usage Examples
```
============================================================
🤖 Calendar AI Agent - Natural Language Calendar Events
============================================================

📅 Enter your calendar request (or 'quit' to exit): Schedule a team meeting next Tuesday at 2pm for 1 hour

🔄 Processing your request...

✅ SUCCESS!

Your team meeting has been scheduled for next Tuesday at 2:00 PM and will last for 60 minutes.

🔗 View in Google Calendar: https://calendar.google.com/calendar/event?eid=...
```

### More Examples
```bash
✅ "Schedule a dentist appointment tomorrow at 10am"
✅ "Book a 2 hour workshop next Friday at 3pm"
✅ "Create a lunch meeting with alice@example.com tomorrow at noon"
✅ "Team standup at Conference Room A next Monday at 9am for 30 minutes"

❌ "Send an email to the team" (correctly rejected - not a calendar event)
❌ "What's the weather tomorrow?" (correctly rejected)
```

### Tips for Best Results

- ✅ **Be specific about time:** "tomorrow at 3pm" is better than "tomorrow afternoon"
- ✅ **Include duration if important:** "for 2 hours" or "30 minute meeting"
- ✅ **Use email addresses for participants:** "with john@company.com"
- ✅ **Mention location if relevant:** "at Downtown Office" or "in Room 301"

---

## 🛠️ Troubleshooting

### "Error 403: access_denied" in Browser

**Solution:** You forgot to add yourself as a test user!

1. Go to [OAuth Consent Screen](https://console.cloud.google.com/apis/credentials/consent)
2. Scroll to **"Test users"**
3. Click **"+ ADD USERS"**
4. Add your email address
5. Delete `token.json` from project folder
6. Try again

### "GROQ_API_KEY not found"

**Solution:** Your `.env` file is missing or incorrect.

1. Make sure `.env` exists in project root
2. Open it and verify it contains: `GROQ_API_KEY=gsk_xxxxx`
3. No spaces around the `=` sign
4. No quotes around the key

### "credentials.json not found"

**Solution:** Download credentials from Google Cloud Console.

1. Make sure you created **Desktop app** credentials (not Web app)
2. Download and rename to `credentials.json`
3. Place in same folder as `calendar_agent.py`

### Browser Doesn't Open for Authentication

**Solution:** Try manual authentication.

1. Look for the URL in terminal output starting with `https://accounts.google.com/o/oauth2/auth...`
2. Copy and paste it into your browser
3. Complete the authorization
4. Copy the code from the browser
5. Paste it back into the terminal

### Events Not Appearing in Calendar

**Solution:** Check your timezone.

The agent uses UTC by default. You can modify the timezone in `calendar_agent.py`:
```python
# Find this in create_google_calendar_event function:
'timeZone': 'UTC',  # Change to 'America/New_York', 'Europe/London', etc.
```

---

## 🏗️ Project Structure
```
calendar-ai-agent/
├── calendar_agent.py      # Main application
├── credentials.json       # Google OAuth credentials (do not commit!)
├── token.json            # Auto-generated auth token (do not commit!)
├── .env                  # API keys (do not commit!)
├── .env.example          # Template for .env
├── .gitignore           # Prevents committing secrets
├── requirements.txt     # Python dependencies
├── README.md           # This file
└── LICENSE            # MIT License
```

---

## 🔒 Security & Privacy

### Files You Should NEVER Commit to GitHub

- ❌ `.env` - Contains your Groq API key
- ❌ `credentials.json` - Contains Google OAuth secrets
- ❌ `token.json` - Contains your Google auth token

These are already in `.gitignore` to prevent accidental commits.

### What This App Can Access

The agent only requests access to:
- ✅ Create, read, update, and delete events in your Google Calendar
- ❌ NO access to Gmail, Drive, or any other Google services
- ❌ NO access to read your contacts or personal information

You can revoke access anytime at: https://myaccount.google.com/permissions

---

## 🛠️ Built With

- **[Groq](https://groq.com/)** - Ultra-fast LLM inference
- **[Instructor](https://github.com/jxnl/instructor)** - Structured outputs from LLMs  
- **[Pydantic](https://docs.pydantic.dev/)** - Data validation and settings management
- **[Google Calendar API](https://developers.google.com/calendar)** - Calendar integration
- **Llama 3.3 70B** - Meta's powerful language model

---

## 🚀 Future Enhancements

Ideas for contributors:

- [ ] Recurring events support (daily, weekly, monthly)
- [ ] Automatic timezone detection
- [ ] Support for multiple calendars
- [ ] Event editing and deletion via natural language
- [ ] Web interface (Flask/Streamlit)
- [ ] Slack/Discord bot integration
- [ ] Voice input support
- [ ] Event analytics and summaries
- [ ] Integration with other calendar services (Outlook, Apple Calendar)

---

## 🤝 Contributing

Contributions are welcome! Here's how:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please make sure to:
- Follow the existing code style
- Add tests for new features
- Update documentation as needed

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

This means you can:
- ✅ Use it commercially
- ✅ Modify it
- ✅ Distribute it
- ✅ Use it privately

Just include the original license and copyright notice.

---

## 🙏 Acknowledgments

- Thanks to **Groq** for providing blazing-fast and free LLM inference
- **Google** for the Calendar API
- The amazing **open-source community** for incredible tools and libraries
- My 5+ years of Software Developement & Engineering Experience lol

---

## 📧 Support

Having issues? Here's how to get help:

1. **Check the [Troubleshooting](#-troubleshooting) section** above
2. **Search existing [Issues](https://github.com/predaaaasaaaaaaa/ai-calendar-agent/issues)
   - Your operating system
   - Python version (`python --version`)
   - Full error message
   - Steps to reproduce

---

## ⭐ Show Your Support

If you found this project helpful, please consider:
- ⭐ Starring this repository
- 🐦 Sharing it on social media
- 🤝 Contributing improvements
- 💬 Spreading the word!

---

<div align="center">


· [Report Bug](https://github.com/predaaaasaaaaaaa/ai-calendar-agent/issues)

· [Request Feature](https://github.com/predaaaasaaaaaaa/ai-calendar-agent/issues) 

· [Documentation](https://github.com/predaaaasaaaaaaa/ai-calendar-agent/wiki) 

</div>