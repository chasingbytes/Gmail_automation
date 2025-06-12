import streamlit as st
import json
import os
import openai
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
from rapidfuzz import fuzz
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import base64
import re

# Load secrets
openai.api_key = st.secrets["OPENAI_API_KEY"]
signature = st.secrets["general"]["signature"]

# Load response templates from JSON
@st.cache_data
def load_templates():
    with open("templates/gmailGPTreply.json", "r") as f:
        return json.load(f)

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
    

FUZZY_THRESHOLD = 85 

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
def create_gmail_draft(service, to, subject, body, thread_id=None, original_message_id=None):
    message = MIMEText(body, "html", _charset="utf-8")
    message['to'] = to
    message['subject'] = subject

    if original_message_id:
        message['In-Reply-To'] = original_message_id
        message['References'] = original_message_id

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    msg_dict = {'raw': raw}

    if thread_id:
        msg_dict['threadId'] = thread_id

    draft = service.users().drafts().create(userId='me', body={'message': msg_dict}).execute()
    return draft
    
# with 1 image
def create_draft_with_image(to, subject, html_body, image_path, thread_id=None, original_message_id=None):

    message = MIMEMultipart('related')
    message['To'] = to
    message['Subject'] = subject

    if original_message_id:
        message['In-Reply-To'] = original_message_id
        message['References'] = original_message_id

    alt = MIMEMultipart('alternative')
    message.attach(alt)
    alt.attach(MIMEText(html_body, 'html'))

    # Attach image
    with open(image_path, 'rb') as img_file:
        img = MIMEImage(img_file.read())
        content_id = os.path.splitext(os.path.basename(image_path))[0]
        img.add_header('Content-ID', f'<{content_id}>')
        img.add_header('Content-Disposition', 'inline', filename=image_filename)
        message.attach(img)

    # Return base64-encoded email content
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    msg_dict = {'raw': raw}
    if thread_id:
        msg_dict['threadId'] = thread_id

    draft = service.users().drafts().create(userId='me', body={'message': msg_dict}).execute()
    return draft

# With multiple images
def create_draft_with_images(service, to, subject, html_body, image_list, thread_id=None, original_message_id=None):

    # Create root message
    message = MIMEMultipart('related')
    message['To'] = to
    message['Subject'] = subject

    if original_message_id:
        message['In-Reply-To'] = original_message_id
        message['References'] = original_message_id
        
    alt = MIMEMultipart('alternative')
    message.attach(alt)
    alt.attach(MIMEText(html_body, 'html', _charset='utf-8'))

    # Attach each image with proper CID
    for image_filename in image_list:
        image_path = os.path.join("images", image_filename)
        if not os.path.exists(image_path):
            continue
        with open(image_path, 'rb') as img_file:
            mime_image = MIMEImage(img_file.read())
            content_id = os.path.splitext(image_filename)[0]
            mime_image.add_header('Content-ID', f'<{content_id}>')
            mime_image.add_header('Content-Disposition', 'inline', filename=image_filename)
            message.attach(mime_image)
            
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    msg_dict = {'raw': raw}
    if thread_id:
        msg_dict['threadId'] = thread_id

    draft = service.users().drafts().create(userId='me', body={'message': msg_dict}).execute()
    return draft
                

# Get unread emails
def fetch_unread_emails(service, max_results=50):
    results = service.users().messages().list(userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=max_results).execute()
    messages = results.get('messages', [])
    email_contents = []
    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['From', 'Subject', 'Message-ID']).execute()
        headers = msg_data.get('payload', {}).get('headers', [])
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        message_id = next((h['value'] for h in headers if h['name'] == 'Message-ID'), None)
        thread_id = msg_data.get('threadId')
        snippet = msg_data.get('snippet', '')
        email_contents.append({
            'id': msg['id'],
            'from': sender,
            'subject': subject,
            'body': snippet,
            'thread_id': thread_id,
            'message_id': message_id
        })
    return email_contents
    
def auto_reply_to_unread_emails(service):
    unread_emails = fetch_unread_emails(service)

    for email in unread_emails:
        sender_email = email['from']
        original_subject = email['subject']
        original_body = email['body']
        thread_id = email['thread_id']
        message_id = email['message_id']

        # Skip if essential metadata is missing
        if not sender_email or not message_id or not thread_id:
            continue

        # Generate reply
        html_response = generate_auto_reply(original_body)
        
        create_gmail_draft(
            service=service,
            to=sender_email,
            subject="Re: " + original_subject,
            body=html_response,
            thread_id=thread_id,
            original_message_id=message_id
        )


# Build GPT-based email reply
from openai import OpenAI

client = OpenAI()

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
    return response.choices[0].message.content.strip()

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
                            # add signature
                            reply_text += signature
                            st.write("Generated Reply:", reply_text) # TEMP DEBUG

                            # Fill editable text area with the generated reply
                            edited_reply = st.text_area(
                                "Reply Preview",
                                value=reply_text,
                                height=300,
                                key=f"{email['id']}_text_area"
                            )

                            # Send draft using edited reply
                            if "images" in selected_template:
                                draft = create_draft_with_images(
                                    service=service,
                                    to=email['from'],
                                    subject=email['subject'],
                                    htlm_body=edited_reply,
                                    image_path=image_path,
                                    thread_id=email['thread_id'],
                                    original_message_id=email['original_message_id']
                                )
                            elif "image" in selected_template:
                                image_path = os.path.join("images", selected_template["image"])
                                draft = create_draft_with_image(
                                    service=service,
                                    to=email['from'],
                                    subject=email['subject'],
                                    htlm_body=edited_reply,
                                    image_path=image_path,
                                    thread_id=email['thread_id'],
                                    original_message_id=email['original_message_id']
                                )
                            else:
                                draft = create_gmail_draft(
                                    service=service,
                                    to=email['from'],
                                    subject=email['subject'],
                                    body=edited_reply,
                                    thread_id=email['thread_id'],
                                    original_message_id=email['message_id']
                                )

                            st.success(f"✅ Draft created for {email['from']} – Draft ID: {draft['id']}")

            else:
                st.warning("No matching template found for this email.")
