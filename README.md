# 📫 Rising Tide Email Assistant

A Streamlit-based Gmail automation tool that uses OpenAI to draft intelligent email responses for customer inquiries at Rising Tide Car Wash.

---

## ✨ Features

- 🔐 Login screen with credential protection via `secrets.toml`
- 📥 Gmail API integration to fetch unread emails
- 🤖 GPT-powered reply generation based on email content
- 📎 Option to include promotional images and formatted HTML signatures
- 📤 Output ready-to-send replies with preview
- 🌐 Clean, user-friendly Streamlit web UI

---

## 📸 Screenshots
![Screenshot 2025-06-18 at 2 58 36 PM](https://github.com/user-attachments/assets/6cabd711-f1b9-4369-8354-5d8ba41d24a8)

![Screenshot 2025-06-18 at 2 59 03 PM](https://github.com/user-attachments/assets/577dc787-2e81-4d75-8e2e-ccfaf51fc16e)

---

## 🛠️ Technologies Used

- Python 3.10+
- [Streamlit](https://streamlit.io/)
- [OpenAI API](https://platform.openai.com/)
- [Google Gmail API](https://developers.google.com/gmail/api)
- RapidFuzz (for fuzzy matching trigger phrases)
- Pickled OAuth token for Gmail access

## AI Response Logic
Incoming email content is parsed and matched against JSON file templates, of predefined emails used for reoccurring emails. OpenAI is used to generate these replies with a personalized touch.

You can extend functionality by:
- Adding new templates as needed
- Attaching images to send with emails
- Tune GPT prompt to allow for more freedom/stick closer to the templates

---

## 🚀 Getting Started

### 1. Clone the repository
git clone https://github.com/yourusername/rtcw-email-assistant.git
cd rtcw-email-assistant

### 2. Install dependencies
pip install -r requirements.txt

### 3. Set up your Streamlit secrects.toml file (found on your Streamlit Account under Settings)
It will look something like this:
  
[auth]
username = "your username/email"
password = "your password"

OPENAI_API_KEY = "sk-xxx..."

token_pickle = """your pickled gmail token"""

[general]

OPTIONAL AS GMAIL API DOES NOT PULL GMAIL SIGNATURE NATURALLY

signature = """Your HTML email signature"""
