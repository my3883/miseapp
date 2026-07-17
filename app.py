"""
Mise - a cooking workflow app that separates prep from cooking.

Run with:
    streamlit run app.py
"""

import json
import os
import re
import uuid
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Constants and small helpers
# ---------------------------------------------------------------------------

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mise_data.json")

UNITS = {
    "cup", "cups", "tbsp", "tbsps", "tablespoon", "tablespoons",
    "tsp", "tsps", "teaspoon", "teaspoons", "oz", "ounce", "ounces",
    "lb", "lbs", "pound", "pounds", "g", "gram", "grams", "kg",
    "kilogram", "kilograms", "ml", "milliliter", "milliliters",
    "l", "liter", "liters", "clove", "cloves", "pinch", "pinches",
    "can", "cans", "slice", "slices", "stick", "sticks", "bunch",
    "bunches", "head", "heads",
}

PAST_TO_IMPERATIVE = {
    "chopped": "chop", "diced": "dice", "minced": "mince", "sliced": "slice",
    "grated": "grate", "measured": "measure", "crushed": "crush",
    "peeled": "peel", "zested": "zest", "juiced": "juice", "shredded": "shred",
    "melted": "melt", "softened": "soften", "beaten": "beat", "whisked": "whisk",
    "drained": "drain", "rinsed": "rinse", "trimmed": "trim", "halved": "halve",
    "quartered": "quarter", "cubed": "cube", "julienned": "julienne",
    "seeded": "seed", "cored": "core", "washed": "wash", "dried": "dry",
}

GROCERY_CATEGORIES = ["Produce", "Dairy", "Meat & Seafood", "Pantry", "Frozen", "Other"]

CATEGORY_HINTS = {
    "Produce": ["onion", "garlic", "tomato", "pepper", "lettuce", "spinach", "carrot",
                "potato", "lemon", "lime", "herb", "basil", "cilantro", "parsley",
                "apple", "avocado", "cucumber", "broccoli", "mushroom", "ginger"],
    "Dairy": ["milk", "cheese", "butter", "cream", "yogurt", "egg"],
    "Meat & Seafood": ["chicken", "beef", "pork", "fish", "shrimp", "salmon", "bacon",
                        "sausage", "turkey"],
    "Frozen": ["frozen"],
    "Pantry": ["flour", "sugar", "salt", "oil", "rice", "pasta", "beans", "broth",
               "stock", "vinegar", "sauce", "spice", "baking"],
}


def new_id():
    return str(uuid.uuid4())[:8]


def guess_category(name):
    name_l = name.lower()
    for cat, hints in CATEGORY_HINTS.items():
        if any(h in name_l for h in hints):
            return cat
    return "Other"


def extract_timer_seconds(text):
    m = re.search(r"(\d+)\s*(hour|hr|minute|min|second|sec)s?\b", text, re.I)
    if not m:
        return None
    num = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("hour") or unit == "hr":
        return num * 3600
    if unit.startswith("min"):
        return num * 60
    if unit.startswith("sec"):
        return num
    return None


def parse_ingredient_line(line):
    raw = line.strip()
    if not raw:
        return None

    # Pull out a parenthetical note, e.g. "(chopped)"
    paren_match = re.search(r"\(([^)]*)\)", raw)
    paren_note = paren_match.group(1) if paren_match else ""
    text_wo_paren = re.sub(r"\([^)]*\)", "", raw).strip()

    parts = text_wo_paren.split(",")
    main = parts[0].strip()
    trailing = ",".join(parts[1:]).strip()

    action_word = ""
    for candidate in [trailing, paren_note]:
        cand_l = candidate.lower().strip()
        if not cand_l:
            continue
        if cand_l in PAST_TO_IMPERATIVE:
            action_word = PAST_TO_IMPERATIVE[cand_l]
            break
        for w in re.findall(r"[a-zA-Z]+", cand_l):
            if w in PAST_TO_IMPERATIVE:
                action_word = PAST_TO_IMPERATIVE[w]
                break
        if action_word:
            break

    qty_match = re.match(r"^\s*((?:\d+\s+)?\d+/\d+|\d*\.\d+|\d+)\s*(.*)$", main)
    qty = ""
    rest = main
    if qty_match and qty_match.group(1):
        qty = qty_match.group(1).strip()
        rest = qty_match.group(2).strip()

    unit = ""
    name = rest
    words = rest.split(" ", 1)
    if words and words[0].lower().strip(".") in UNITS:
        unit = words[0]
        name = words[1] if len(words) > 1 else ""

    return {
        "id": new_id(),
        "raw": raw,
        "qty": qty,
        "unit": unit,
        "name": name.strip(),
        "action": action_word,
        "done": False,
    }


def format_prep_task(ing):
    action = ing["action"].capitalize() if ing["action"] else "Prep"
    bits = [action]
    if ing["qty"]:
        bits.append(ing["qty"])
    if ing["unit"]:
        bits.append(ing["unit"])
    bits.append(ing["name"] or ing["raw"])
    return " ".join(b for b in bits if b)


def parse_steps_text(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    action_pattern = r"\b(" + "|".join(PAST_TO_IMPERATIVE.keys()) + r")\b\s*"
    steps = []
    for l in lines:
        cleaned = re.sub(r"^\s*\d+[\.\)]\s*", "", l)
        timer = extract_timer_seconds(cleaned)
        display = re.sub(action_pattern, "", cleaned, flags=re.I)
        display = re.sub(r"\s{2,}", " ", display).strip()
        display = display[0].upper() + display[1:] if display else display
        steps.append({
            "id": new_id(),
            "raw": cleaned,
            "display": display or cleaned,
            "timer_seconds": timer,
            "done": False,
        })
    return steps


def parse_ingredients_text(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    result = []
    for l in lines:
        parsed = parse_ingredient_line(l)
        if parsed:
            result.append(parsed)
    return result


def parse_recipe_from_url(url):
    """
    Fetch a recipe page and extract title / ingredients / steps.

    Uses the recipe-scrapers library, which has purpose-built parsers for
    hundreds of recipe sites and falls back to generic schema.org recipe
    markup for everything else. Raises RuntimeError with a plain-language
    message on any failure, so the UI can just show it.
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("The 'requests' package isn't installed. Run: pip install -r requirements.txt")
    try:
        from recipe_scrapers import scrape_html
    except ImportError:
        raise RuntimeError("The 'recipe-scrapers' package isn't installed. Run: pip install -r requirements.txt")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Couldn't reach that page: {e}")

    try:
        scraper = scrape_html(resp.text, org_url=url, supported_only=False)
    except Exception:
        raise RuntimeError(
            "Couldn't find recipe data on that page. Some sites block automated "
            "requests, or don't mark up their recipe in a format this can read. "
            "Try Paste / Import instead: copy the recipe text and paste it there."
        )

    def safe(fn, default=None):
        try:
            val = fn()
            return val if val else default
        except Exception:
            return default

    title = safe(scraper.title, "Untitled Recipe")
    ingredients_raw = safe(scraper.ingredients, []) or []
    instructions_raw = safe(scraper.instructions, "") or ""
    total_time = safe(scraper.total_time)
    yields = safe(scraper.yields, "")

    ingredients = [parse_ingredient_line(l) for l in ingredients_raw if l and l.strip()]
    ingredients = [i for i in ingredients if i]
    steps = parse_steps_text(instructions_raw)

    return {
        "title": (title or "Untitled Recipe").strip(),
        "servings": (yields or "").strip(),
        "prep_time": "",
        "cook_time": f"{total_time} min" if total_time else "",
        "ingredients": ingredients,
        "steps": steps,
        "source_url": url,
    }


def naive_recipe_parse(blob):

    """
    Very lightweight parser for pasted / imported recipe text.
    Looks for an 'Ingredients' and 'Steps'/'Instructions' section header.
    Falls back to treating the whole thing as steps if no headers are found.
    """
    title = "Untitled Recipe"
    lines = blob.strip().split("\n")
    if lines:
        title = lines[0].strip()[:120] or title

    ing_section = ""
    step_section = ""

    ing_idx = None
    step_idx = None
    for i, l in enumerate(lines):
        l_low = l.strip().lower().strip(":")
        if l_low in ("ingredients",):
            ing_idx = i
        if l_low in ("steps", "instructions", "directions", "method"):
            step_idx = i

    if ing_idx is not None and step_idx is not None:
        ing_section = "\n".join(lines[ing_idx + 1:step_idx])
        step_section = "\n".join(lines[step_idx + 1:])
    elif ing_idx is not None:
        ing_section = "\n".join(lines[ing_idx + 1:])
    elif step_idx is not None:
        step_section = "\n".join(lines[step_idx + 1:])
        ing_section = "\n".join(lines[1:ing_idx if ing_idx else step_idx])
    else:
        # No headers found — best effort: assume no ingredient list, whole
        # body is steps, minus the title line.
        step_section = "\n".join(lines[1:])

    return {
        "title": title,
        "ingredients": parse_ingredients_text(ing_section),
        "steps": parse_steps_text(step_section),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "recipes": {},
        "grocery": [],
        "settings": {"units": "imperial", "default_mode": "recipe"},
    }


def save_data():
    payload = {
        "recipes": st.session_state.recipes,
        "grocery": st.session_state.grocery,
        "settings": st.session_state.settings,
    }
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

def init_state():
    if "initialized" in st.session_state:
        return
    data = load_data()
    st.session_state.recipes = data.get("recipes", {})
    st.session_state.grocery = data.get("grocery", [])
    st.session_state.settings = data.get("settings", {"units": "imperial", "default_mode": "recipe"})
    st.session_state.page = "home"
    st.session_state.current_id = None
    st.session_state.cooking_step_idx = 0
    st.session_state.mise_sort = "list"
    st.session_state.initialized = True


def goto(page, recipe_id=None):
    st.session_state.page = page
    if recipe_id is not None:
        st.session_state.current_id = recipe_id
    if page == "cooking":
        st.session_state.cooking_step_idx = 0


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

def inject_css():
    st.markdown(
        """
        <style>
        .stButton > button {
            font-size: 1.05rem;
            padding: 0.6rem 1rem;
            border-radius: 10px;
            width: 100%;
        }
        div[data-testid="stVerticalBlock"] > div:has(> div > div > div > label) {
            padding-top: 0.15rem;
        }
        .mise-step-text {
            font-size: 2rem;
            font-weight: 600;
            line-height: 1.35;
            margin: 1.2rem 0;
        }
        .mise-step-counter {
            font-size: 1rem;
            color: #888;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        .mise-card {
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 12px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.6rem;
        }
        .mise-title {
            font-size: 1.15rem;
            font-weight: 700;
            margin-bottom: 0.15rem;
        }
        .mise-meta {
            color: #888;
            font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def countdown_widget(seconds, key):
    components.html(
        f"""
        <div style="font-family: -apple-system, sans-serif;">
          <div id="mise-timer-{key}" style="font-size:2.4rem; font-weight:700; text-align:center; padding:0.5rem;">
            {seconds // 60:02d}:{seconds % 60:02d}
          </div>
        </div>
        <script>
        (function() {{
            let remaining = {seconds};
            const el = document.getElementById("mise-timer-{key}");
            const timer = setInterval(function() {{
                remaining -= 1;
                if (remaining < 0) {{
                    clearInterval(timer);
                    el.innerHTML = "Time's up";
                    el.style.color = "#e05a5a";
                    return;
                }}
                const m = Math.floor(remaining / 60).toString().padStart(2, '0');
                const s = (remaining % 60).toString().padStart(2, '0');
                el.innerHTML = m + ":" + s;
            }}, 1000);
        }})();
        </script>
        """,
        height=70,
    )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_home():
    st.title("Mise")
    st.caption("Prep separately. Cook without interruption.")

    search = st.text_input("Search recipes", placeholder="Search by title or tag", label_visibility="collapsed")

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("+ Add Recipe"):
            goto("add")

    recipes = list(st.session_state.recipes.values())
    if search:
        s_low = search.lower()
        recipes = [
            r for r in recipes
            if s_low in r["title"].lower() or any(s_low in t.lower() for t in r.get("tags", []))
        ]

    if not recipes:
        st.info("No recipes yet. Tap **Add Recipe** to get started.")
        return

    recipes.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    for r in recipes:
        with st.container():
            st.markdown('<div class="mise-card">', unsafe_allow_html=True)
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f'<div class="mise-title">{r["title"]}</div>', unsafe_allow_html=True)
                meta_bits = []
                if r.get("prep_time"):
                    meta_bits.append(f"Prep {r['prep_time']}")
                if r.get("cook_time"):
                    meta_bits.append(f"Cook {r['cook_time']}")
                if r.get("tags"):
                    meta_bits.append(", ".join(r["tags"]))
                if meta_bits:
                    st.markdown(f'<div class="mise-meta">{" · ".join(meta_bits)}</div>', unsafe_allow_html=True)
            with c2:
                if st.button("Open", key=f"open_{r['id']}"):
                    goto("detail", r["id"])
            st.markdown("</div>", unsafe_allow_html=True)


def page_add():
    st.title("Add Recipe")
    if st.button("← Back"):
        goto("home")

    tab_url, tab_paste, tab_manual = st.tabs(["From URL", "Paste / Import", "Manual Entry"])

    with tab_url:
        st.caption(
            "Paste a link to a recipe page. Works best on recipe blogs and food "
            "sites, since most of them mark up their ingredients and steps in a "
            "standard format behind the scenes."
        )
        url = st.text_input("Recipe URL", key="url_input", placeholder="https://www.example.com/some-recipe")
        if st.button("Import from URL", key="import_url_btn"):
            if not url.strip():
                st.warning("Paste a URL first.")
            else:
                with st.spinner("Reading the recipe..."):
                    try:
                        parsed = parse_recipe_from_url(url.strip())
                        error = None
                    except RuntimeError as e:
                        parsed = None
                        error = str(e)
                if error:
                    st.error(error)
                elif parsed:
                    rid = new_id()
                    recipe = {
                        "id": rid,
                        "title": parsed["title"],
                        "servings": parsed["servings"],
                        "prep_time": parsed["prep_time"],
                        "cook_time": parsed["cook_time"],
                        "tags": [],
                        "ingredients": parsed["ingredients"],
                        "steps": parsed["steps"],
                        "mise_sort": "list",
                        "source_url": parsed.get("source_url", ""),
                        "created_at": datetime.now().isoformat(),
                    }
                    st.session_state.recipes[rid] = recipe
                    save_data()
                    if not parsed["ingredients"] and not parsed["steps"]:
                        st.warning(
                            "Found the page but couldn't pull out ingredients or steps. "
                            "You can add them on the Edit page now."
                        )
                    goto("detail", rid)
                    st.rerun()

    with tab_paste:
        st.caption("Paste a full recipe (title on the first line, then Ingredients / Steps sections if you have them).")
        blob = st.text_area("Recipe text", height=280, key="paste_blob")
        if st.button("Parse Recipe", key="parse_btn"):
            if not blob.strip():
                st.warning("Paste some recipe text first.")
            else:
                parsed = naive_recipe_parse(blob)
                rid = new_id()
                recipe = {
                    "id": rid,
                    "title": parsed["title"],
                    "servings": "",
                    "prep_time": "",
                    "cook_time": "",
                    "tags": [],
                    "ingredients": parsed["ingredients"],
                    "steps": parsed["steps"],
                    "mise_sort": "list",
                    "source_url": "",
                    "created_at": datetime.now().isoformat(),
                }
                st.session_state.recipes[rid] = recipe
                save_data()
                if not parsed["ingredients"] and not parsed["steps"]:
                    st.warning("Couldn't find clear ingredients or steps. You can edit the recipe manually now.")
                goto("detail", rid)
                st.rerun()

    with tab_manual:
        title = st.text_input("Title", key="manual_title")
        c1, c2, c3 = st.columns(3)
        with c1:
            servings = st.text_input("Servings", key="manual_servings")
        with c2:
            prep_time = st.text_input("Prep time", key="manual_prep")
        with c3:
            cook_time = st.text_input("Cook time", key="manual_cook")
        tags_raw = st.text_input("Tags (comma separated)", key="manual_tags")
        ing_text = st.text_area(
            "Ingredients (one per line)",
            placeholder="2 cups onions, chopped\n1 tbsp olive oil\n3 cloves garlic, minced",
            height=150,
            key="manual_ing",
        )
        steps_text = st.text_area(
            "Steps (one per line, in order)",
            placeholder="Heat oil in a pan over medium heat\nAdd onions and cook 5 minutes\nAdd garlic and cook 1 minute",
            height=150,
            key="manual_steps",
        )
        if st.button("Save Recipe", key="save_manual"):
            if not title.strip():
                st.warning("Give the recipe a title.")
            else:
                rid = new_id()
                recipe = {
                    "id": rid,
                    "title": title.strip(),
                    "servings": servings.strip(),
                    "prep_time": prep_time.strip(),
                    "cook_time": cook_time.strip(),
                    "tags": [t.strip() for t in tags_raw.split(",") if t.strip()],
                    "ingredients": parse_ingredients_text(ing_text),
                    "steps": parse_steps_text(steps_text),
                    "mise_sort": "list",
                    "source_url": "",
                    "created_at": datetime.now().isoformat(),
                }
                st.session_state.recipes[rid] = recipe
                save_data()
                goto("detail", rid)
                st.rerun()


def get_current_recipe():
    rid = st.session_state.current_id
    return st.session_state.recipes.get(rid) if rid else None


def page_detail():
    recipe = get_current_recipe()
    if not recipe:
        st.warning("Recipe not found.")
        goto("home")
        return

    if st.button("← All Recipes"):
        goto("home")

    st.title(recipe["title"])
    meta_bits = []
    if recipe.get("servings"):
        meta_bits.append(f"Serves {recipe['servings']}")
    if recipe.get("prep_time"):
        meta_bits.append(f"Prep {recipe['prep_time']}")
    if recipe.get("cook_time"):
        meta_bits.append(f"Cook {recipe['cook_time']}")
    if meta_bits:
        st.caption(" · ".join(meta_bits))
    if recipe.get("source_url"):
        st.caption(f"Source: {recipe['source_url']}")

    st.subheader("Ingredients")
    if recipe["ingredients"]:
        for ing in recipe["ingredients"]:
            bits = [ing["qty"], ing["unit"], ing["name"] or ing["raw"]]
            st.markdown("- " + " ".join(b for b in bits if b))
    else:
        st.caption("No ingredients recorded.")

    st.subheader("Steps")
    if recipe["steps"]:
        for i, step in enumerate(recipe["steps"], 1):
            st.markdown(f"{i}. {step['raw']}")
    else:
        st.caption("No steps recorded.")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Start Mise Mode", key="start_mise"):
            goto("mise")
    with c2:
        if st.button("Edit Recipe", key="edit_recipe"):
            goto("edit")
    with c3:
        if st.button("Delete Recipe", key="delete_recipe"):
            del st.session_state.recipes[recipe["id"]]
            save_data()
            goto("home")
            st.rerun()


def page_edit():
    recipe = get_current_recipe()
    if not recipe:
        goto("home")
        return

    st.title(f"Edit: {recipe['title']}")
    if st.button("← Cancel"):
        goto("detail")
        st.rerun()

    title = st.text_input("Title", value=recipe["title"])
    c1, c2, c3 = st.columns(3)
    with c1:
        servings = st.text_input("Servings", value=recipe.get("servings", ""))
    with c2:
        prep_time = st.text_input("Prep time", value=recipe.get("prep_time", ""))
    with c3:
        cook_time = st.text_input("Cook time", value=recipe.get("cook_time", ""))
    tags_raw = st.text_input("Tags (comma separated)", value=", ".join(recipe.get("tags", [])))

    ing_lines = "\n".join(i["raw"] for i in recipe["ingredients"])
    ing_text = st.text_area("Ingredients (one per line)", value=ing_lines, height=150)

    step_lines = "\n".join(s["raw"] for s in recipe["steps"])
    steps_text = st.text_area("Steps (one per line)", value=step_lines, height=150)

    if st.button("Save Changes"):
        recipe["title"] = title.strip() or recipe["title"]
        recipe["servings"] = servings.strip()
        recipe["prep_time"] = prep_time.strip()
        recipe["cook_time"] = cook_time.strip()
        recipe["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
        recipe["ingredients"] = parse_ingredients_text(ing_text)
        recipe["steps"] = parse_steps_text(steps_text)
        save_data()
        goto("detail")
        st.rerun()


def page_mise():
    recipe = get_current_recipe()
    if not recipe:
        goto("home")
        return

    if st.button("← Back to Recipe"):
        goto("detail")
        st.rerun()

    st.title(recipe["title"])
    st.caption("Mise Mode — get everything prepped before you start cooking.")

    ingredients = recipe["ingredients"]
    total = len(ingredients)
    done = sum(1 for i in ingredients if i["done"])

    if total:
        st.progress(done / total, text=f"{done}/{total} completed")
    else:
        st.info("No ingredients to prep for this recipe.")

    sort_mode = st.radio(
        "Group by",
        ["List order", "Action", "Ingredient"],
        horizontal=True,
        index=["List order", "Action", "Ingredient"].index(
            {"list": "List order", "action": "Action", "ingredient": "Ingredient"}.get(
                recipe.get("mise_sort", "list"), "List order"
            )
        ),
    )
    sort_key = {"List order": "list", "Action": "action", "Ingredient": "ingredient"}[sort_mode]
    if sort_key != recipe.get("mise_sort"):
        recipe["mise_sort"] = sort_key
        save_data()

    if sort_key == "list":
        ordered = list(enumerate(ingredients))
    elif sort_key == "action":
        ordered = sorted(enumerate(ingredients), key=lambda p: (p[1]["action"] or "zzz", p[1]["name"]))
    else:
        ordered = sorted(enumerate(ingredients), key=lambda p: p[1]["name"].lower())

    for idx, ing in ordered:
        label = format_prep_task(ing)
        checked = st.checkbox(label, value=ing["done"], key=f"prep_{ing['id']}")
        if checked != ing["done"]:
            ing["done"] = checked
            save_data()
            st.rerun()

    st.divider()
    if st.button("Start Cooking", type="primary"):
        goto("cooking")
        st.rerun()


def page_cooking():
    recipe = get_current_recipe()
    if not recipe:
        goto("home")
        return

    steps = recipe["steps"]
    if not steps:
        st.warning("This recipe has no steps yet.")
        if st.button("← Back to Recipe"):
            goto("detail")
        return

    idx = st.session_state.cooking_step_idx
    idx = max(0, min(idx, len(steps) - 1))
    st.session_state.cooking_step_idx = idx
    step = steps[idx]

    top_l, top_r = st.columns([3, 1])
    with top_r:
        if st.button("Exit"):
            goto("detail")
            st.rerun()

    st.markdown(f'<div class="mise-step-counter">Step {idx + 1} of {len(steps)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="mise-step-text">{step["display"]}</div>', unsafe_allow_html=True)

    if step.get("timer_seconds"):
        if st.button("Start Timer", key=f"timer_{step['id']}"):
            st.session_state[f"show_timer_{step['id']}"] = True
        if st.session_state.get(f"show_timer_{step['id']}"):
            countdown_widget(step["timer_seconds"], step["id"])

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Previous", disabled=(idx == 0), use_container_width=True):
            st.session_state.cooking_step_idx = idx - 1
            st.rerun()
    with c2:
        if idx == len(steps) - 1:
            if st.button("Finish", type="primary", use_container_width=True):
                goto("detail")
                st.rerun()
        else:
            if st.button("Next →", type="primary", use_container_width=True):
                st.session_state.cooking_step_idx = idx + 1
                st.rerun()


def page_grocery():
    st.title("Grocery List")

    with st.expander("Add item"):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            item_name = st.text_input("Item", key="grocery_new_name")
        with c2:
            item_qty = st.text_input("Qty", key="grocery_new_qty")
        with c3:
            item_cat = st.selectbox("Category", GROCERY_CATEGORIES, key="grocery_new_cat")
        if st.button("Add to list"):
            if item_name.strip():
                st.session_state.grocery.append({
                    "id": new_id(),
                    "name": item_name.strip(),
                    "qty": item_qty.strip(),
                    "category": item_cat,
                    "checked": False,
                })
                save_data()
                st.rerun()

    st.caption("Sync ingredients from a recipe:")
    recipe_options = {r["title"]: r["id"] for r in st.session_state.recipes.values()}
    if recipe_options:
        chosen = st.selectbox("Recipe", list(recipe_options.keys()), key="grocery_sync_recipe")
        if st.button("Sync ingredients"):
            recipe = st.session_state.recipes[recipe_options[chosen]]
            for ing in recipe["ingredients"]:
                name = ing["name"] or ing["raw"]
                existing = next((g for g in st.session_state.grocery if g["name"].lower() == name.lower()), None)
                if existing:
                    if ing["qty"] or ing["unit"]:
                        existing["qty"] = (existing["qty"] + " + " if existing["qty"] else "") + " ".join(
                            b for b in [ing["qty"], ing["unit"]] if b
                        )
                else:
                    st.session_state.grocery.append({
                        "id": new_id(),
                        "name": name,
                        "qty": " ".join(b for b in [ing["qty"], ing["unit"]] if b),
                        "category": guess_category(name),
                        "checked": False,
                    })
            save_data()
            st.rerun()
    else:
        st.caption("No recipes yet to sync from.")

    st.divider()

    if not st.session_state.grocery:
        st.info("Your grocery list is empty.")
        return

    if st.button("Clear completed"):
        st.session_state.grocery = [g for g in st.session_state.grocery if not g["checked"]]
        save_data()
        st.rerun()

    for cat in GROCERY_CATEGORIES:
        items = [g for g in st.session_state.grocery if g["category"] == cat]
        if not items:
            continue
        st.markdown(f"**{cat}**")
        for item in items:
            c1, c2 = st.columns([5, 1])
            with c1:
                label = item["name"] + (f" — {item['qty']}" if item["qty"] else "")
                checked = st.checkbox(label, value=item["checked"], key=f"grocery_{item['id']}")
                if checked != item["checked"]:
                    item["checked"] = checked
                    save_data()
                    st.rerun()
            with c2:
                if st.button("Remove", key=f"remove_{item['id']}"):
                    st.session_state.grocery = [g for g in st.session_state.grocery if g["id"] != item["id"]]
                    save_data()
                    st.rerun()


def page_settings():
    st.title("Settings")

    units = st.radio(
        "Units",
        ["imperial", "metric"],
        index=0 if st.session_state.settings.get("units", "imperial") == "imperial" else 1,
        format_func=lambda x: "Imperial (cups, oz, lb)" if x == "imperial" else "Metric (g, ml, kg)",
    )
    default_mode = st.radio(
        "Default mode when opening a recipe",
        ["recipe", "mise"],
        index=0 if st.session_state.settings.get("default_mode", "recipe") == "recipe" else 1,
        format_func=lambda x: "Recipe detail" if x == "recipe" else "Mise mode",
    )

    if units != st.session_state.settings.get("units") or default_mode != st.session_state.settings.get("default_mode"):
        st.session_state.settings["units"] = units
        st.session_state.settings["default_mode"] = default_mode
        save_data()

    st.divider()
    st.caption(f"Data is stored locally at: `{DATA_FILE}`")
    if st.button("Clear all data", type="secondary"):
        st.session_state.recipes = {}
        st.session_state.grocery = []
        save_data()
        st.success("Cleared.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Mise", page_icon="🔪", layout="centered")
    init_state()
    inject_css()

    with st.sidebar:
        st.markdown("### Mise")
        if st.button("🍽 Recipes", use_container_width=True):
            goto("home")
        if st.button("🛒 Grocery List", use_container_width=True):
            goto("grocery")
        if st.button("⚙️ Settings", use_container_width=True):
            goto("settings")

    page = st.session_state.page
    if page == "home":
        page_home()
    elif page == "add":
        page_add()
    elif page == "detail":
        page_detail()
    elif page == "edit":
        page_edit()
    elif page == "mise":
        page_mise()
    elif page == "cooking":
        page_cooking()
    elif page == "grocery":
        page_grocery()
    elif page == "settings":
        page_settings()
    else:
        page_home()


if __name__ == "__main__":
    main()
