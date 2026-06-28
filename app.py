import os
import yt_dlp
import requests
from google import genai
from flask import Flask, render_template, request, jsonify
from secrets import GEMINI_API_KEY, WEBHOOK_CHANNEL_A, WEBHOOK_CHANNEL_B
import time

app = Flask(__name__)

# ================= CONFIGURATION =================
client = genai.Client(api_key=GEMINI_API_KEY)
# =================================================

# -----------------------------------------------------------------------
# Content-type specific instructions.
# Each entry tells Gemini what to focus on and what extra sections to add.
# These are injected into the prompt at runtime based on the user's selection.
# -----------------------------------------------------------------------
CONTENT_TYPE_INSTRUCTIONS = {

    "University Lecture": """
CONTENT TYPE: University Lecture

FOCUS ON:
- Every concept, term, and definition introduced — explain each one clearly
- Theoretical frameworks, models, or methodologies presented
- Examples, analogies, and case studies used to illustrate points
- Formulas, equations, diagrams, or technical details mentioned
- The logical structure and progression of the lecture
- Papers, books, authors, or studies cited by the lecturer
- Anything the lecturer explicitly marks as important, will be on the exam, or repeats for emphasis
- Student questions and the lecturer's answers (if present)

EXTRA SECTION TO ADD after Open Questions:
### 📖 Glossary
List every new term, concept, or piece of jargon introduced in this lecture with a clear definition as given (or implied) by the lecturer.

### 📝 Study Notes
3–5 concise points that capture the most testable or essential content from this lecture — what a student would write on a flashcard.
""",

    "Business Meeting": """
CONTENT TYPE: Business Meeting

FOCUS ON:
- Every decision made — state clearly WHAT was decided, WHO decided it, and any conditions attached
- All action items — WHO is responsible, WHAT they need to do, and WHEN it is due (if mentioned)
- Issues, blockers, and risks raised, along with proposed solutions or workarounds
- Project or initiative status updates discussed
- Budget, resource, or timeline discussions — include all specific numbers
- Disagreements or debates — note the different positions and how (or if) they were resolved
- Open questions explicitly left for follow-up

EXTRA SECTIONS TO ADD after Open Questions:
### ✅ Action Items
A clean, scannable list of every action item in this format:
- [ ] **[Owner]** — [Task description] *(deadline: [date/timeframe or "not specified"])*

This section is the most critical output of a meeting summary. Be exhaustive — missing an action item is worse than including too much.

### 🗓️ Next Steps & Follow-ups
Any next meeting, scheduled review, or follow-up process mentioned.
""",

    "Conference / Keynote": """
CONTENT TYPE: Conference / Keynote

FOCUS ON:
- The speaker's central thesis or main argument — state it clearly in one sentence
- All major announcements, product launches, or reveals
- Data, statistics, and research findings — always include exact numbers
- Industry trends, predictions, and forward-looking statements
- Case studies and real-world examples presented
- Surprising or counterintuitive claims made
- Notable and quotable statements
- Q&A session highlights (if present) — what was asked and what was answered
- References to other speakers, companies, research, or events

EXTRA SECTIONS TO ADD after Open Questions:
### 📣 Announcements & Reveals
A dedicated list of every announcement, launch, or reveal made during this talk — these are often the most share-worthy content.

### 🔮 Predictions & Forward-Looking Statements
Any statements about where the industry, technology, or field is heading, as expressed by the speaker.
""",

    "Podcast / Interview": """
CONTENT TYPE: Podcast / Interview

FOCUS ON:
- Guest's background and credentials (as introduced by the host)
- Every major topic thread discussed — cover all of them, not just the first few
- Personal stories, career experiences, and anecdotes shared
- Opinions, takes, and strong positions — note when they are controversial or unconventional
- Practical advice, frameworks, or mental models offered
- Books, tools, people, podcasts, or resources recommended
- Interesting tensions, pushbacks, or disagreements between host and guest
- Key quotes that capture the guest's personality or worldview

EXTRA SECTIONS TO ADD after Open Questions:
### 🎯 Practical Takeaways
Concrete, actionable advice or frameworks that a listener could apply immediately. Numbered list.

### 📌 Recommendations
Every book, tool, resource, or person mentioned by either the host or guest, with brief context on why it was mentioned.
""",

    "Webinar": """
CONTENT TYPE: Webinar

FOCUS ON:
- Stated learning objectives — and whether each was addressed
- Step-by-step processes, workflows, or tutorials demonstrated
- Software, platforms, or tools shown — include version numbers or specifics if mentioned
- Best practices and common mistakes covered
- All Q&A — list every question asked and the answer given
- Downloadable resources, templates, or links mentioned
- Practical takeaways the attendee can implement immediately

EXTRA SECTIONS TO ADD after Open Questions:
### 🛠️ Step-by-Step Guide
If any process or workflow was demonstrated, reproduce it here as a numbered step-by-step guide, in enough detail that someone could follow it without watching the recording.

### 💬 Q&A Summary
Every audience question with the presenter's answer. Format as:
**Q: [question]**
A: [answer]
""",

    "Live Stream": """
CONTENT TYPE: Live Stream

FOCUS ON:
- Main topics and segments covered — treat each major segment as its own section
- Key information, insights, or announcements shared
- Community questions answered during the stream
- Demonstrations, reviews, or walkthroughs performed
- Any products, services, or resources mentioned
- Moments where the streamer gave strong opinions or recommendations
- Notable chat interactions if referenced by the streamer

EXTRA SECTIONS TO ADD after Open Questions:
### ⏱️ Stream Segments
A chronological breakdown of the major segments or topic shifts during the stream, so someone can find specific content quickly.
""",

    "Workshop": """
CONTENT TYPE: Workshop

FOCUS ON:
- Skills and techniques taught — describe them in enough detail to be reproducible
- Exercises or activities performed — what was the task, what was the expected outcome
- Step-by-step processes — preserve the exact sequence (order matters)
- Tools, materials, or software needed and demonstrated
- Common mistakes or corrections made during practice
- Key principles or rules explained by the instructor
- What participants were expected to be able to do by the end

EXTRA SECTIONS TO ADD after Open Questions:
### 🛠️ Skills & Techniques Covered
A structured list of every skill or technique taught, with enough explanation that someone could practice it independently.

### 📋 Workshop Exercises
Each exercise described in enough detail to replicate: objective, instructions, and expected outcome.
""",

    "Other": """
CONTENT TYPE: General Content

Analyze this recording thoroughly. Organize your Detailed Notes based on the natural structure of the content itself.
Be comprehensive — cover all significant topics from start to finish.
""",

    "": """
No content type specified. Analyze this recording thoroughly and apply the standard structure.
"""
}


def chunk_text(text, limit=1900):
    """Split text into chunks to respect Discord's message length limit."""
    chunks = []
    while len(text) > limit:
        split_at = text.rfind('\n', 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:]
    if text:
        chunks.append(text)
    return chunks


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    url = data.get('url')

    content_type = data.get('content_type', '')
    speaker      = data.get('speaker', '')
    event_name   = data.get('event_name', '')
    date         = data.get('date', '')
    extra        = data.get('extra', '')

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    print(f"\n[INFO] 1/5 Starting processing for: {url}")
    print(f"[INFO]      Content type: {content_type or 'Not specified'}")

    try:
        with open("prompt.txt", "r", encoding="utf-8") as file:
            SYSTEM_PROMPT = file.read()

        # Fetch content-type specific instructions (fallback to "Other" if unknown)
        type_instructions = CONTENT_TYPE_INSTRUCTIONS.get(
            content_type,
            CONTENT_TYPE_INSTRUCTIONS["Other"]
        )

        DYNAMIC_INFO = (
            "=== RECORDING CONTEXT ===\n"
            f"Content type : {content_type or 'Not specified'}\n"
            f"Speaker      : {speaker or 'Not specified'}\n"
            f"Event / Title: {event_name or 'Not specified'}\n"
            f"Date & Time  : {date or 'Not specified'}\n"
            f"Extra notes  : {extra or 'None'}\n\n"
            f"{type_instructions}\n"
            "=========================\n\n"
        )

        FINAL_PROMPT = DYNAMIC_INFO + SYSTEM_PROMPT
        print("[INFO]    Prompt loaded and context injected successfully")

    except Exception as e:
        print(f"[ERROR] Failed to read prompt.txt: {e}")
        return jsonify({"error": f"Error loading prompt: {e}"}), 500

    base_filename  = "temp_audio"
    final_filename = "temp_audio.mp3"

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': base_filename,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': True,
        'no_warnings': True
    }

    try:
        print("[INFO] 2/5 Downloading audio via yt-dlp (this may take a moment)...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        print("[INFO] 3/5 Uploading audio file to Google Gemini servers...")
        audio_file = client.files.upload(file=final_filename)

        while "PROCESSING" in str(audio_file.state):
            print("       -> File is being processed by Google. Waiting 5 seconds...")
            time.sleep(5)
            audio_file = client.files.get(name=audio_file.name)

        if "FAILED" in str(audio_file.state):
            raise Exception("Google rejected the file (status: FAILED).")

        print("[INFO] 4/5 File processed. Generating summary...")
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=[FINAL_PROMPT, audio_file]
        )

        print("[INFO] 5/5 Summary generated. Cleaning up temporary files...")
        client.files.delete(name=audio_file.name)
        if os.path.exists(final_filename):
            os.remove(final_filename)

        print("[INFO] === SUCCESS! Returning result to client. ===")
        return jsonify({"result": response.text})

    except Exception as e:
        print(f"\n[ERROR] An error occurred: {str(e)}")
        if os.path.exists(final_filename):
            os.remove(final_filename)
        if os.path.exists(base_filename):
            os.remove(base_filename)
        return jsonify({"error": str(e)}), 500


@app.route('/send', methods=['POST'])
def send_to_discord():
    data    = request.json
    text    = data.get('text')
    channel = data.get('channel')

    webhook_url = WEBHOOK_CHANNEL_A if channel == 'channel_a' else WEBHOOK_CHANNEL_B

    if not text or not webhook_url:
        return jsonify({"error": "Missing text or webhook URL"}), 400

    print(f"\n[INFO] Sending message to channel: {channel}")
    chunks = chunk_text(text)

    for chunk in chunks:
        payload  = {"content": chunk}
        response = requests.post(webhook_url, json=payload)
        if response.status_code not in [200, 204]:
            print(f"[ERROR] Discord rejected the message. Status code: {response.status_code}")
            return jsonify({"error": f"Discord error: {response.status_code}"}), 500
        time.sleep(1)

    print("[INFO] Message sent to Discord successfully.")
    return jsonify({"status": "Success"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
