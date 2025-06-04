import streamlit as st
import json
import os
import openai
from email.mime.text import MIMEText
import base64
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

openai.api_key = st.secrets["OPENAI_API_KEY"]

# Load response templates from JSON
@st.cache_data
def load_templates():
    with open("templates/gmailGPTreply.json", "r") as f:
        return json.load(f)

import re
def normalize(text):
    text = text.lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.split("—")[0]  # Cut signature

    # Remove soft filler phrases
    text = re.sub(
        r"\b(i would like to|i want to|i need to|please|my|the|can you|how do i|how can i|just|i|this is|thank you|thanks)\b",
        "",
        text
    )

    text = re.sub(r"[^\w\s]", "", text)  # remove punctuation
    text = re.sub(r"\s+", " ", text)
    return text.strip()


from rapidfuzz import fuzz

FUZZY_THRESHOLD = 85  # adjust for tolerance

def detect_intent(user_input, templates):
    normalized_input = normalize(user_input)

    for category, category_data in templates.items():
        trigger_phrases = category_data.get("trigger_phrases", [])
        for phrase in trigger_phrases:
            exact_match = phrase in normalized_input
            fuzzy_match = fuzz.partial_ratio(normalized_input, normalize(phrase)) >= FUZZY_THRESHOLD

            if exact_match or fuzzy_match:
                return {
                    "category": category,
                    "templates": category_data.get("templates", [])
                }

    return None
    
def preprocess_email(body):
    body = body.lower()
    body = body.replace("’", "'").replace("‘", "'")
    body = body.split("—")[0]  # Remove everything after an em dash (signature)
    return body.strip()

# Authenticate and create Gmail service
@st.cache_resource
def get_gmail_service():
    token_str = st.secrets["token_pickle"]
    creds = pickle.loads(base64.b64decode(token_str.encode("utf-8")))
    service = build("gmail", "v1", credentials=creds)
    return service


# Create Gmail draft (html only no images)
def create_gmail_draft(service, to, subject, body):
    message = MIMEText(body, "html", _charset="utf-8")
    message['to'] = to
    message['subject'] = subject
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'message': {'raw': encoded_message}}
    draft = service.users().drafts().create(userId='me', body=create_message).execute()
    return draft
# with 1 image
def create_draft_with_image(to, subject, html_body, image_path):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    import base64

    message = MIMEMultipart('related')
    message['To'] = to
    message['Subject'] = subject

    alt = MIMEMultipart('alternative')
    message.attach(alt)

    # Attach HTML content
    alt.attach(MIMEText(html_body, 'html'))

    # Attach image
    with open(image_path, 'rb') as img_file:
        img = MIMEImage(img_file.read())
        image_filename = os.path.basename(image_path)
        content_id = os.path.splitext(image_filename)[0]
        img.add_header('Content-ID', '<renewimage>')
        img.add_header('Content-Disposition', 'inline', filename=image_filename)
        message.attach(img)

    # Return base64-encoded email content
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw}

# With multiple images
def create_draft_with_images(service, to, subject, html_body, image_list):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    import base64
    import os

    message = MIMEMultipart('related')
    message['To'] = to
    message['Subject'] = subject

    alt = MIMEMultipart('alternative')
    message.attach(alt)

    alt.attach(MIMEText(html_body, 'html', _charset='utf-8'))

    for img_name in image_list:
        image_path = os.path.join("images", img_name)
        if os.path.exists(image_path):
            with open(image_path, 'rb') as img_file:
                img = MIMEImage(img_file.read())
                content_id = os.path.splitext(img_name)[0]
                img.add_header('Content-ID', f"<{content_id}>")
                img.add_header('Content-Disposition', 'inline', filename=img_name)
                message.attach(img)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'message': {'raw': raw}}
    draft = service.users().drafts().create(userId='me', body=create_message).execute()
    return draft

# Get unread emails
def fetch_unread_emails(service, max_results=50):
    results = service.users().messages().list(userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=max_results).execute()
    messages = results.get('messages', [])
    email_contents = []
    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = msg_data.get('payload', {}).get('headers', [])
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        snippet = msg_data.get('snippet', '')
        email_contents.append({
            'id': msg['id'],
            'from': sender,
            'subject': subject,
            'body': snippet
        })
    return email_contents


# Build GPT-based email reply
from openai import OpenAI

client = OpenAI()  # uses OPENAI_API_KEY from env

def generate_gpt_reply(user_email, template):
    prompt = f"""
You are a customer support assistant for Rising Tide Car Wash.

A customer has sent an email, and your job is to respond professionally.

Rules:
- Start with a short, polite intro acknowledging the issue.
- Then insert the template reply **exactly as written**.
- Do NOT include the subject line.
- Do NOT change formatting or emoji.
- Do NOT add a closing signature.

Customer Email:
{user_email}

Template Reply:
{template['reply']}

Respond below:
"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful customer service assistant. Use the reply template exactly as provided after your greeting. No subject, no signature."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )
    return response.choices[0].message.content.strip()  # ✅ Make sure you return and strip it

# Streamlit UI
st.title("📧 Email Reply Assistant")

service = get_gmail_service()
templates = load_templates()

if st.button("🔁 Refresh Inbox"):
    st.session_state["unread_emails"] = fetch_unread_emails(service)

if "unread_emails" in st.session_state:
    if not st.session_state["unread_emails"]:
        st.info("No unread emails found.")
    else:
        for email in st.session_state["unread_emails"]:
            st.markdown("---")
            st.subheader(f"✉️ From: {email['from']}")
            st.write(f"**Subject:** {email['subject']}")
            st.write(f"**Body:** {email['body']}")

            cleaned_body = preprocess_email(email['body'])
            intent_data = detect_intent(cleaned_body, templates)

            if intent_data:
                st.write(f"### Matched Category: {intent_data['category']}")
                templates_list = intent_data["templates"]

                if not templates_list:
                    st.warning("No templates found for this category.")
                    continue

                for i, tmpl in enumerate(templates_list):
                    with st.expander(f"Option {i+1}: {tmpl['subject']}"):
                        st.markdown(tmpl["reply"], unsafe_allow_html=True)

                        if st.button(f"✅ Use this Reply", key=f"{email['id']}_choose_{i}"):
                            selected_template = tmpl
                            reply_text = generate_gpt_reply(email['body'], selected_template)
                            st.write("Generated Reply:", reply_text) # TEMP DEBUG

                            # Fill the editable text area with the generated reply
                            edited_reply = st.text_area(
                                "Reply Preview",
                                value=reply_text,
                                height=200,
                                key=f"{email['id']}_text_area"
                            )

                            # Send the draft using edited (or unchanged) reply
                            if "images" in selected_template:
                                draft = create_draft_with_images(
                                    service,
                                    email['from'],
                                    selected_template['subject'],
                                    edited_reply,
                                    selected_template['images']
                                )
                            elif "image" in selected_template:
                                image_path = os.path.join("images", selected_template["image"])
                                draft = create_draft_with_image(
                                    service,
                                    email['from'],
                                    selected_template['subject'],
                                    edited_reply,
                                    image_path
                                )
                            else:
                                draft = create_gmail_draft(
                                    service,
                                    email['from'],
                                    selected_template['subject'],
                                    edited_reply
                                )

                            st.success(f"✅ Draft created for {email['from']} – Draft ID: {draft['id']}")

            else:
                st.warning("No matching template found for this email.")
