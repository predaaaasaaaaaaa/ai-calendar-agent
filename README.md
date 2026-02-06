# 🤖 Calendar AI Agent

A natural language calendar assistant that creates Google Calendar events using AI.

## ✨ Features

- 📝 Natural language input (e.g., "Schedule a meeting next Tuesday at 2pm")
- 📅 Automatically creates Google Calendar events
- 👥 Sends calendar invites to participants
- 🧠 Powered by Llama 3.3 70B via Groq
- ⚡ Fast and accurate event extraction

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- A Groq API key ([Get one here](https://console.groq.com/))
- A Google Cloud account

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/YOUR_USERNAME/calendar-ai-agent.git
cd calendar-ai-agent
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Set up Groq API:**
   - Get your API key from [Groq Console](https://console.groq.com/)
   - Create a `.env` file:
```bash
   cp .env.example .env
```
   - Add your Groq API key to `.env`:
```
   GROQ_API_KEY=your_actual_api_key_here
```

4. **Set up Google Calendar API:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable the Google Calendar API
   - Create OAuth 2.0 credentials (Desktop app)
   - Download the credentials and save as `credentials.json` in the project folder

### Usage

Run the agent:
```bash
python calendar_agent.py
```

The first time you run it, a browser window will open asking you to authorize Google Calendar access.

### Examples
```
📅 Enter your calendar request: Schedule a team meeting next Tuesday at 2pm for 1 hour

✅ SUCCESS!
Dear Team, this is to confirm that the team meeting is scheduled for 2024-02-13T14:00:00 
and will last for 60 minutes.

🔗 View in Google Calendar: https://calendar.google.com/calendar/event?eid=...
```
```
📅 Enter your calendar request: Book a dentist appointment on Feb 15th at 10am

✅ SUCCESS!
Your dentist appointment has been scheduled for February 15th at 10:00 AM.

🔗 View in Google Calendar: https://calendar.google.com/calendar/event?eid=...
```

## 🛠️ How It Works

The agent uses a **prompt-chaining** approach with three LLM calls:

1. **Event Extraction**: Determines if the input is a calendar event (gate check)
2. **Event Parsing**: Extracts specific details (name, date, duration, participants)
3. **Event Creation**: Creates the Google Calendar event and generates confirmation

## 📝 License

MIT License - feel free to use this project however you want!

## 🤝 Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

## ⚠️ Security Note

Never commit your `credentials.json`, `token.json`, or `.env` files to GitHub. They contain sensitive information.

## 🙏 Acknowledgments

- Built with [Groq](https://groq.com/) for fast AI inference
- Uses [Instructor](https://github.com/jxnl/instructor) for structured outputs
- Powered by Meta's Llama 3.3 70B model