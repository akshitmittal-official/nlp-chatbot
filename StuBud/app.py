from flask import Flask, request, jsonify, render_template, make_response
from pymongo import MongoClient
import google.generativeai as genai
import os
import uuid
from dotenv import load_dotenv

# ---------- SETUP ----------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_key")

genai.configure(api_key=os.getenv("API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["stubud_db"]
users_collection = db["users"]

# ---------- INTENT ----------
def detect_intent(message):
    msg = message.lower()

    if any(q in msg for q in ["what do you know", "about me"]):
        return "memory_query"

    if "which class" in msg:
        return "ask_class"

    if "weak subject" in msg:
        return "ask_weak_subject"

    if any(w in msg for w in ["plan", "schedule", "timetable"]):
        return "study_plan"

    if any(w in msg for w in ["stress", "anxiety", "panic"]):
        return "emotional"

    if any(w in msg for w in ["career", "college", "future"]):
        return "career"

    return "general"

# ---------- STATE ----------
def detect_state(message):
    msg = message.lower()

    if any(w in msg for w in ["panic", "anxious", "overwhelmed"]):
        return "high_stress"

    if any(w in msg for w in ["confused", "lost", "don't know"]):
        return "confused"

    if any(w in msg for w in ["tired", "burnout"]):
        return "low_energy"

    return "normal"

# ---------- STRATEGY ----------
def get_response_strategy(intent, state):

    if state == "high_stress":
        return "- Calm first. Keep short. Reduce overload."

    if state == "confused":
        return "- Break into options. Guide thinking. Ask one sharp question."

    if intent == "career":
        return "- Compare options clearly. Keep practical."

    if intent == "study_plan":
        return "- Give structured steps with realistic flow."

    return "- Respond naturally and clearly."

# ---------- SUMMARIZATION ----------
def update_summary(chat_history):
    if len(chat_history) < 6:
        return None

    summary_prompt = f"""
Summarize this conversation in 2-3 lines focusing on:
- student's situation
- struggles
- goals

Conversation:
{chat_history[-10:]}
"""

    try:
        res = model.generate_content(summary_prompt)
        return res.text.strip()
    except:
        return None

# ---------- MAIN CHAT ----------
def studbud_chat(message, user_id):

    user_data = users_collection.find_one({"user_id": user_id})

    if not user_data:
        user_data = {
            "user_id": user_id,
            "chat_history": [],
            "summary": "",
            "student_profile": {
                "class": None,
                "weak_subject": None,
                "stress_level": None
            }
        }
        users_collection.insert_one(user_data)

    chat_history = user_data.get("chat_history", [])
    student_profile = user_data.get("student_profile", {})
    summary = user_data.get("summary", "")

    lower_msg = message.lower()

    # ---------- MEMORY UPDATE ----------
    for i in range(1, 13):
        if f"class {i}" in lower_msg:
            student_profile["class"] = f"Class {i}"

    for sub in ["physics", "chemistry", "math", "biology"]:
        if sub in lower_msg and any(w in lower_msg for w in ["weak", "hard"]):
            student_profile["weak_subject"] = sub.capitalize()

    # ---------- INTENT + STATE ----------
    intent = detect_intent(message)
    state = detect_state(message)
    strategy = get_response_strategy(intent, state)

    # ---------- RULE RESPONSES ----------
    if intent == "ask_class" and student_profile.get("class"):
        return f"You are in {student_profile['class']}."

    if intent == "ask_weak_subject" and student_profile.get("weak_subject"):
        return f"You've been struggling with {student_profile['weak_subject']}."

    # ---------- CONTEXT ----------
    recent_history = "\n".join(chat_history[-6:])

    context = recent
    if summary:
        context += f"\nSummary: {summary}"

    # ---------- PROMPT ----------
    prompt = f"""
You are StuBud, a balanced , an intelligent, emotionally aware student mentor.

Personality:
- Calm, intelligent, grounded
- Not overly emotional
- Not robotic
- Speak like a thoughtful senior

Rules:
- Speak naturally like a thoughtful mentor
- Do NOT keep responses artificially short
- Expand ideas when useful
- Use spacing between thoughts (2–3 lines per idea)
- Avoid long unbroken paragraphs
- Ask at most one meaningful follow-up question
- Do NOT assume facts not explicitly stated
- If unsure, ask instead of concluding
Style:
- Speak naturally, not robotic
- Be supportive but not overly soft
- Give structured guidance when needed
- Avoid repeating same phrases
- Don’t over-focus on class/subject unless relevant
- Think like a real mentor, not a chatbot

Strategy:
{strategy}

Context:
{context}

Student: {message}
StuBud:
"""

# ---------- AI ----------
    try:
        response = model.generate_content(prompt)

        if response and hasattr(response, "text") and response.text:
            reply = response.text.strip()
        else:
            reply = "I couldn’t generate a proper response. Try again."

    except Exception as e:
        print("ERROR:", e)

        if "429" in str(e):
            reply = "I'm a bit overloaded right now. Give me ~40 seconds and try again."
        else:
            reply = "I'm having a small issue right now. Try again in a moment."

    # ---------- SAVE ----------
    chat_history.append(f"Student: {message}")
    chat_history.append(f"StuBud: {reply}")

    new_summary = update_summary(chat_history)
    if new_summary:
        summary = new_summary

    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "chat_history": chat_history,
                "student_profile": student_profile,
                "summary": summary
            }
        }
    )

    return reply

# ---------- ROUTES ----------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message")

    user_id = request.cookies.get("user_id")
    if not user_id:
        user_id = str(uuid.uuid4())

    reply = studbud_chat(message, user_id)

    res = make_response(jsonify({"reply": reply}))
    res.set_cookie("user_id", user_id)

    return res

# ---------- RUN ----------
if __name__ == "__main__":
    app.run(debug=True)
