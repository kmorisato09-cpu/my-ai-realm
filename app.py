import base64
import json
import re
import requests
import streamlit as st
from google import genai
from google.genai import types

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="AI Dungeon Master",
    page_icon="🐉",
    layout="wide"
)

# --- GITHUB AUTO-SAVE HELPERS ---
def get_github_save():
    """Fetches campaign_save.json from GitHub if it exists."""
    if "GITHUB_TOKEN" not in st.secrets or "GITHUB_REPO" not in st.secrets:
        return None
    
    token = st.secrets["GITHUB_TOKEN"]
    repo = st.secrets["GITHUB_REPO"]
    url = f"https://api.github.com/repos/{repo}/contents/campaign_save.json"
    headers = {"Authorization": f"token {token}"}
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content), data["sha"]
    return None, None

def save_to_github():
    """Saves current HP, inventory, and chat history to campaign_save.json on GitHub."""
    if "GITHUB_TOKEN" not in st.secrets or "GITHUB_REPO" not in st.secrets:
        return
    
    token = st.secrets["GITHUB_TOKEN"]
    repo = st.secrets["GITHUB_REPO"]
    url = f"https://api.github.com/repos/{repo}/contents/campaign_save.json"
    headers = {"Authorization": f"token {token}"}
    
    # Get file SHA if it already exists (required for updating files on GitHub)
    _, sha = get_github_save()
    
    save_data = {
        "hp": st.session_state.hp,
        "max_hp": st.session_state.max_hp,
        "inventory": st.session_state.inventory,
        "messages": st.session_state.messages
    }
    
    encoded_content = base64.b64encode(json.dumps(save_data, indent=2).encode("utf-8")).decode("utf-8")
    
    payload = {
        "message": "Auto-save campaign state",
        "content": encoded_content
    }
    if sha:
        payload["sha"] = sha
        
    requests.put(url, headers=headers, json=payload)

# --- SESSION STATE INITIALIZATION & LOADING ---
if "loaded" not in st.session_state:
    saved_data, _ = get_github_save()
    if saved_data:
        st.session_state.hp = saved_data.get("hp", 20)
        st.session_state.max_hp = saved_data.get("max_hp", 20)
        st.session_state.inventory = saved_data.get("inventory", ["Broadsword", "Leather Armor", "Small Health Potion"])
        st.session_state.messages = saved_data.get("messages", [])
        st.toast("⚡ Campaign auto-loaded from GitHub!", icon="📜")
    else:
        st.session_state.hp = 20
        st.session_state.max_hp = 20
        st.session_state.inventory = ["Broadsword", "Leather Armor", "Small Health Potion"]
        st.session_state.messages = []
    st.session_state.loaded = True

# --- UI SIDEBAR ---
with st.sidebar:
    st.title("🐉 Game Dashboard")
    
    # API Key Input
    api_key = st.text_input(
        "Gemini API Key", 
        type="password", 
        help="Get a key from Google AI Studio (aistudio.google.com)"
    )
    
    st.divider()
    st.header("Character Stats")
    
    char_name = st.text_input("Character Name", value="Valerius")
    char_class = st.text_input("Class", value="Rogue")
    
    # Health Points Display
    st.subheader(f"Health Points: {st.session_state.hp} / {st.session_state.max_hp}")
    hp_ratio = max(0.0, min(1.0, st.session_state.hp / st.session_state.max_hp))
    st.progress(hp_ratio)
    
    st.divider()
    
    # Inventory List Display
    st.header("🎒 Inventory")
    if st.session_state.inventory:
        for item in st.session_state.inventory:
            st.markdown(f"- {item}")
    else:
        st.caption("Inventory is empty.")

# --- HELPER FUNCTION TO PARSE STATE UPDATES ---
def parse_and_apply_state_updates(response_text: str) -> str:
    json_pattern = r"```json\s*(\{.*?\})\s*```"
    match = re.search(json_pattern, response_text, re.DOTALL)
    
    if match:
        json_str = match.group(1)
        try:
            updates = json.loads(json_str)
            
            # Apply HP Changes
            if "hp_change" in updates and updates["hp_change"] is not None:
                st.session_state.hp = max(0, min(st.session_state.max_hp, st.session_state.hp + int(updates["hp_change"])))
                
            # Apply Item Additions
            if "item_added" in updates and updates["item_added"]:
                item_to_add = str(updates["item_added"]).strip()
                if item_to_add not in st.session_state.inventory:
                    st.session_state.inventory.append(item_to_add)
                    
            # Apply Item Removals
            if "item_removed" in updates and updates["item_removed"]:
                item_to_remove = str(updates["item_removed"]).strip()
                if item_to_remove in st.session_state.inventory:
                    st.session_state.inventory.remove(item_to_remove)
                    
        except json.JSONDecodeError:
            pass
            
        clean_narrative = re.sub(json_pattern, "", response_text, flags=re.DOTALL).strip()
        return clean_narrative

    return response_text

# --- MAIN CHAT INTERFACE ---
st.title("🧙‍♂️ AI Realm: Dungeon Master")

if not api_key:
    st.info("👈 Please enter your Gemini API Key in the sidebar to begin your adventure.")
    st.stop()

try:
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error(f"Error initializing client: {e}")
    st.stop()

# System Instructions
inv_str = ", ".join(st.session_state.inventory)
system_instruction = (
    f"You are an expert Dungeon Master running an interactive tabletop RPG adventure.\n\n"
    f"Player Stats Context:\n"
    f"- Player Name: {char_name}\n"
    f"- Class: {char_class}\n"
    f"- Current HP: {st.session_state.hp}\n"
    f"- Current Inventory: {inv_str}\n\n"
    f"RULES:\n"
    f"1. Provide vivid, narrative prose, describing scenes, NPCs, and combat outcomes.\n"
    f"2. Never control the player's choices—always prompt them for their next action.\n"
    f"3. At the VERY END of every single response, you MUST append a hidden JSON state block inside markdown code tags.\n"
    f"4. Format the state update EXACTLY like this:\n"
    f"```json\n"
    f'{{\n  "hp_change": -3,\n  "item_added": "Rusty Key",\n  "item_removed": null\n}}\n'
    f"```\n"
    f"- hp_change: Integer representing HP gained or lost (e.g., -5 for taking damage, +3 for healing, 0 if unchanged).\n"
    f"- item_added: String name of item picked up, or null if none.\n"
    f"- item_removed: String name of item dropped or lost, or null if none."
)

# Display existing chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Process User Chat Input
if prompt := st.chat_input("What do you do next?"):
    
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    contents = []
    for msg in st.session_state.messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))

    with st.chat_message("assistant"):
        with st.spinner("The DM is thinking..."):
            try:
                response = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.7,
                    )
                )
                
                raw_response_text = response.text
                clean_text = parse_and_apply_state_updates(raw_response_text)
                
                st.markdown(clean_text)
                st.session_state.messages.append({"role": "assistant", "content": clean_text})
                
                # Auto-save current session state to GitHub
                save_to_github()
                
                st.rerun()

            except Exception as e:
                st.error(f"Failed to generate response: {e}")
