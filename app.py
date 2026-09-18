import json
import re
import streamlit as st
from google import genai
from google.genai import types

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="AI Dungeon Master",
    page_icon="🐉",
    layout="wide"
)

# --- SESSION STATE INITIALIZATION ---
if "hp" not in st.session_state:
    st.session_state.hp = 20
if "max_hp" not in st.session_state:
    st.session_state.max_hp = 20
if "inventory" not in st.session_state:
    st.session_state.inventory = ["Broadsword", "Leather Armor", "Small Health Potion"]
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- UI SIDEBAR ---
with st.sidebar:
    st.title("🐉 Game Dashboard")
    
    # 1. API Key Input
    api_key = st.text_input(
        "Gemini API Key", 
        type="password", 
        help="Get a key from Google AI Studio (aistudio.google.com)"
    )
    
    st.divider()
    st.header("Character Stats")
    
    # Character Details Inputs
    char_name = st.text_input("Character Name", value="Valerius")
    char_class = st.text_input("Class", value="Rogue")
    
    # Health Points Bar & Display
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

# --- HELPER: HELPER FUNCTION TO PARSE HIDDEN JSON STATE UPDATES ---
def parse_and_apply_state_updates(response_text: str) -> str:
    """
    Extracts the JSON block at the end of Gemini's response, updates the session
    state (HP and Inventory), and returns the narrative string with JSON stripped.
    """
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
            pass  # Fallback gracefully if JSON parsing fails
            
        # Strip the JSON block so the raw data isn't displayed in the main chat narrative
        clean_narrative = re.sub(json_pattern, "", response_text, flags=re.DOTALL).strip()
        return clean_narrative

    return response_text

# --- MAIN CHAT INTERFACE ---
st.title("🧙‍♂️ AI Realm: Dungeon Master")

# API Key Validation Check
if not api_key:
    st.info("👈 Please enter your Gemini API Key in the sidebar to begin your adventure.")
    st.stop()

# Initialize Google GenAI SDK Client
try:
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error(f"Error initializing client: {e}")
    st.stop()

# System Instructions defining game rules & strict output formatting
system_instruction = f"""
You are an expert Dungeon Master running an interactive tabletop RPG adventure.

Player Stats Context:
- Player Name: {char_name}
- Class: {char_class}
- Current HP: {st.session_state.hp}
- Current Inventory: {', '.join(st.session_state.inventory)}

RULES:
1. Provide vivid, narrative prose, describing scenes, NPCs, and combat outcomes.
2. Never control the player's choices—always prompt them for their next action.
3. At the VERY END of every single response, you MUST append a hidden JSON state block inside markdown code tags.
4. Format the state update EXACTLY like this:
```json
{{
  "hp_change": -3, 
  "item_added": "Rusty Key", 
  "item_removed": null
}}
